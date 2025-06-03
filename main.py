import platform
import requests
import os
import asyncio
import zipfile
import json

# 从 AstrBot API 导入必要的模块和类
from astrbot.api.event import filter, AstrMessageEvent  # MessageEventResult 未使用, 已移除
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig

# --- 核心常量定义 ---

# YumeCard 不同操作系统版本的下载链接
URL_WINDOWS = "https://github.com/YumeYuka/YumeCard/releases/download/0.0.1/build-windows-x64-dev.zip"
URL_LINUX = "https://github.com/YumeYuka/YumeCard/releases/download/0.0.1/build-linux-x64-dev.zip"

# YumeCard 核心文件解压后存放的子目录名称 (位于插件自身目录下)
# 例如: astrbot_plugin_YumeCard/YumeCard_core/
VENDOR_SUBDIR = "YumeCard_core"

# YumeCard 可执行文件相对于 VENDOR_SUBDIR 的路径
# 假设解压后, 可执行文件直接位于 VENDOR_SUBDIR 目录下
WINDOWS_EXECUTABLE_REL_PATH = "YumeCard.exe"
LINUX_EXECUTABLE_REL_PATH = "YumeCard"

# YumeCard 自身的配置文件 (config.json) 在 VENDOR_SUBDIR 内的路径信息
YUME_CARD_CONFIG_SUBDIR_IN_VENDOR = "config"  # config.json 存放的子目录, 例如 YumeCard_core/config/
YUME_CARD_CONFIG_FILENAME = "config.json"  # config.json 的文件名


# --- 文件下载与解压辅助函数 ---

def download_file_sync(url: str, save_dir: str, file_name: str) -> str | None:
    """
    同步下载文件到指定目录。

    参数:
        url (str): 文件的下载链接。
        save_dir (str): 文件保存的目标目录。
        file_name (str): 文件保存的名称。

    返回:
        str | None: 成功则返回完整保存路径, 失败则返回 None。
    """
    full_save_path = os.path.join(save_dir, file_name)
    # 确保目标目录存在, 如果不存在则尝试创建, 为后续文件写入做准备
    os.makedirs(save_dir, exist_ok=True)

    # 如果文件已经存在于目标路径, 则跳过下载, 避免重复操作
    if os.path.exists(full_save_path):
        logger.info(f"文件 {full_save_path} 已存在, 跳过下载。")
        return full_save_path
    try:
        logger.info(f"开始下载: {url} -> {full_save_path}")
        # 使用 requests 库进行流式下载, 设置超时防止永久等待
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()  # 如果 HTTP 请求返回错误状态码, 则抛出异常
        with open(full_save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):  # 按块写入, 适合大文件
                f.write(chunk)
        logger.info(f"文件 {file_name} 下载完成!")
        return full_save_path
    except requests.exceptions.RequestException as e:
        logger.error(f"下载文件 {url} 时发生网络错误: {e}")
    except Exception as e:
        logger.error(f"下载文件 {url} 时发生其他未知错误: {e}")
    return None


def unzip_file_sync(zip_path: str, extract_dir: str) -> bool:
    """
    同步解压 ZIP 文件到指定目录。

    参数:
        zip_path (str): ZIP 文件的完整路径。
        extract_dir (str): 文件解压的目标目录。

    返回:
        bool: 解压成功返回 True, 否则返回 False。
    """
    # 确保解压目标目录存在
    os.makedirs(extract_dir, exist_ok=True)
    try:
        logger.info(f"开始解压文件: {zip_path} 到 {extract_dir}")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)  # 将 ZIP 包内所有内容解压到目标目录
        logger.info(f"文件 {zip_path} 解压完成!")
        return True
    except zipfile.BadZipFile:  # 文件不是有效 ZIP 或已损坏
        logger.error(f"文件 {zip_path} 不是一个有效的 ZIP 文件或已损坏。")
    except Exception as e:
        logger.error(f"解压文件 {zip_path} 时发生错误: {e}")
    return False


@register("astrbot_plugin_YumeCard", "FengYing", "一个处理 YumeCard 依赖和配置的插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config: AstrBotConfig = config
        # 用于存储 YumeCard 可执行文件的路径, 初始化时为 None
        self.yume_card_executable: str | None = None

        # 获取当前插件文件 (例如 main.py) 所在的绝对目录路径
        self.plugin_root_dir: str = os.path.dirname(os.path.abspath(__file__))
        # YumeCard 核心文件和依赖的存放目录 (例如 .../astrbot_plugin_YumeCard/YumeCard_core/)
        self.vendor_dir: str = os.path.join(self.plugin_root_dir, VENDOR_SUBDIR)

        # YumeCard 自身配置文件的完整路径
        # 例如 .../YumeCard_core/config/config.json
        self.yumecard_config_dir: str = os.path.join(self.vendor_dir, YUME_CARD_CONFIG_SUBDIR_IN_VENDOR)
        self.yumecard_config_file_path: str = os.path.join(self.yumecard_config_dir, YUME_CARD_CONFIG_FILENAME)

        logger.info(f"插件配置已加载。YumeCard 的 config.json 目标路径: {self.yumecard_config_file_path}")
        # 可选: 打印 AstrBot 传入的完整配置, 用于调试
        # logger.debug(f"AstrBot 传入的初始配置: {json.dumps(self.config.data, indent=2, ensure_ascii=False)}")

    def _ensure_yumecard_config_dir_exists(self) -> bool:
        """
        辅助方法: 确保 YumeCard 自身配置文件 (config.json) 需要的父目录存在。
        例如, 如果 config.json 在 YumeCard_core/config/ 下, 此方法会尝试创建 config/ 目录。
        """
        try:
            os.makedirs(self.yumecard_config_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"创建 YumeCard 配置目录 {self.yumecard_config_dir} 失败: {e}")
            return False
        return True

    def _update_yumecard_config_file(self) -> bool:
        """
        核心逻辑: 根据 AstrBot 的用户配置来生成或更新 YumeCard 使用的 config.json 文件。
        此方法处理了从 AstrBot 配置 (self.config) 读取数据, 并将其转换为 YumeCard 期望的格式。
        特别注意: 此处假设从 self.config 中读取的 repository 项可能是 JSON 字符串 (基于用户反馈),
        而 YumeCard 的 config.json 文件期望 repository 是一个实际的 JSON 对象列表。
        因此, 代码中包含了将字符串项解析为 JSON 对象 (Python 字典) 的逻辑。
        """
        if not self._ensure_yumecard_config_dir_exists():
            logger.warning(
                f"YumeCard 配置目录 {self.yumecard_config_dir} 无法确保存在或创建失败, 跳过更新 config.json。")
            return False

        logger.info(f"准备从 AstrBot 配置更新 YumeCard 的 config.json 文件: {self.yumecard_config_file_path}")
        # 从 self.config 中获取名为 "GitHub" 的配置块
        astrbot_github_config = self.config.get("GitHub")

        if not astrbot_github_config:
            logger.warning(
                "在 AstrBot 配置中未找到 'GitHub' 相关项。请检查插件的 _conf_schema.json 文件以及用户是否已在 AstrBot 面板正确配置。无法生成 YumeCard 的 config.json。")
            return False

        # 定义一个默认的仓库列表结构, 这个结构应与 _conf_schema.json 中为 repository 字段定义的 default 一致。
        # 当 AstrBot 配置中 repository 列表为空或不存在时, 可以使用此默认值。
        default_repo_list_from_schema_dicts = [
            {
                "owner": "FengYing1314",  # 与用户提供的 schema default 匹配
                "repo": "astrbot_plugin_YumeCard",  # 与用户提供的 schema default 匹配
                "branch": "main",
                "lastsha": ""
            }
        ]

        # 从 AstrBot 配置中获取 'repository' 列表。
        # AstrBot 的 _conf_schema.json 定义 repository 的 items 为 object, 理想情况下这里应该是字典列表。
        # 但根据用户反馈, 有时列表中的项可能是字符串形式的 JSON, 因此后续需要处理。
        raw_repo_list = astrbot_github_config.get("repository", default_repo_list_from_schema_dicts)

        repo_list_of_dicts_for_yumecard = []  # 用于存放最终给 YumeCard 的、元素为字典的列表
        if isinstance(raw_repo_list, list):
            for item in raw_repo_list:
                if isinstance(item, str):  # 如果列表项是字符串, 说明它可能是个 JSON 字符串, 需要解析
                    try:
                        # 尝试将字符串解析为 Python 字典
                        parsed_item = json.loads(item)
                        repo_list_of_dicts_for_yumecard.append(parsed_item)
                    except json.JSONDecodeError as e:
                        # 如果解析失败, 记录错误, 并可以考虑是否跳过此项或添加错误标记
                        logger.error(f"无法将仓库配置项字符串 '{item}' 解析为 JSON 对象: {e}")
                elif isinstance(item, dict):  # 如果项已经是字典 (这是期望的格式), 直接使用
                    repo_list_of_dicts_for_yumecard.append(item)
                else:
                    # 记录仓库列表中遇到的非字符串也非字典的未知类型项
                    logger.warning(f"仓库配置列表中遇到未知类型的项: {type(item)}, 内容: {item}")
        else:
            # 如果从 AstrBot 配置中获取的 'repository' 根本不是一个列表 (例如是 None),
            # 则记录警告并使用上面定义的 schema 默认的仓库列表。
            logger.warning(
                f"AstrBot 配置中的 'repository' 不是列表类型 (实际类型: {type(raw_repo_list)}) 或不存在, 将使用预设的默认仓库列表。")
            repo_list_of_dicts_for_yumecard = default_repo_list_from_schema_dicts

        # 构建将要写入 YumeCard config.json 的数据结构
        # 使用 .get() 方法获取配置值, 并提供与 _conf_schema.json 中 default 一致的回退值
        yumecard_config_data = {
            "GitHub": {
                "username": astrbot_github_config.get("username", ""),  # schema default 为 ""
                "backgrounds": str(astrbot_github_config.get("backgrounds", True)).lower(),
                # schema default 为 true (布尔), 转为 "true"/"false" 字符串
                "token": astrbot_github_config.get("token", ""),  # schema default 为 ""
                "repository": repo_list_of_dicts_for_yumecard,  # 使用上面处理好的、元素为字典的列表
                "refresh_interval_seconds": astrbot_github_config.get("refresh_interval_seconds", 3600)
                # schema default 为 3600
            }
        }

        try:
            # 将构建好的数据以 JSON 格式写入文件, 使用 indent 实现格式化美观输出
            with open(self.yumecard_config_file_path, 'w', encoding='utf-8') as f:
                json.dump(yumecard_config_data, f, ensure_ascii=False, indent=2)
            logger.info(f"YumeCard 的 config.json 文件已成功写入/更新: {self.yumecard_config_file_path}")
            # 可选: 打印实际写入的内容, 用于调试 (注意 token 等敏感信息)
            # logger.debug(f"写入到 YumeCard config.json 的内容: {json.dumps(yumecard_config_data, indent=2, ensure_ascii=False)}")
            return True
        except IOError as e:  # 文件读写相关的错误
            logger.error(f"写入 YumeCard 配置文件 {self.yumecard_config_file_path} 失败: {e}")
        except Exception as e:  # 其他可能的未知错误
            logger.error(f"生成 YumeCard 配置文件时发生未知错误: {e}")
        return False

    async def initialize(self):
        """
        插件初始化方法。
        AstrBot 加载插件时会自动调用此异步方法。
        主要负责:
        1. 确定运行环境 (操作系统) 并设置相应下载链接。
        2. 检查 YumeCard 核心文件是否已存在, 若不存在则下载并解压。
        3. 根据用户在 AstrBot 面板的配置, 生成或更新 YumeCard 自身的 config.json 文件。
        """
        logger.info(f"YumeCard 插件初始化流程开始... 插件根目录: {self.plugin_root_dir}")
        logger.info(f"YumeCard 核心文件及依赖将存放在: {self.vendor_dir}")
        # 确保核心文件存放目录 (例如 YumeCard_core/) 存在
        os.makedirs(self.vendor_dir, exist_ok=True)

        # ---- 1. 确定下载参数 ----
        os_name = platform.system()
        download_url = None
        zip_filename = None
        # YumeCard 可执行文件相对于 vendor_dir (YumeCard_core/) 的路径
        expected_executable_rel_to_vendor_path = None

        if os_name == "Windows":
            logger.info("当前运行环境为 Windows 系统。")
            download_url = URL_WINDOWS
            zip_filename = URL_WINDOWS.split('/')[-1]  # 从 URL 中提取文件名
            expected_executable_rel_to_vendor_path = WINDOWS_EXECUTABLE_REL_PATH
        elif os_name == "Linux":
            logger.info("当前运行环境为 Linux 系统。")
            download_url = URL_LINUX
            zip_filename = URL_LINUX.split('/')[-1]
            expected_executable_rel_to_vendor_path = LINUX_EXECUTABLE_REL_PATH
        else:
            logger.warning(
                f"检测到当前操作系统为 {os_name}, 非 Windows 或 Linux, YumeCard 相关功能可能不受支持或无法运行。")
            return  # 不支持的操作系统, 提前结束初始化

        if not download_url or not zip_filename or not expected_executable_rel_to_vendor_path:
            # 基本参数缺失, 无法继续, 记录错误并返回
            logger.error("未能确定 YumeCard 的下载链接、ZIP 文件名或预期的可执行文件路径, 初始化失败。")
            return

        # 拼接出 YumeCard 可执行文件和 ZIP 包在本地的完整期望路径
        potential_executable_path = os.path.join(self.vendor_dir, expected_executable_rel_to_vendor_path)
        zip_file_path = os.path.join(self.vendor_dir, zip_filename)
        extract_to_dir = self.vendor_dir  # ZIP 包内容直接解压到 vendor_dir (YumeCard_core/)

        # ---- 2. 检查、下载、解压 YumeCard 核心文件 ----
        core_files_ready = False  # 标记 YumeCard 核心可执行文件是否已准备就绪
        if os.path.exists(potential_executable_path):
            logger.info(f"YumeCard 主程序 {potential_executable_path} 已存在, 无需重复下载和解压。")
            self.yume_card_executable = potential_executable_path
            core_files_ready = True
        else:
            logger.info(f"YumeCard 主程序 {potential_executable_path} 未找到, 开始下载和解压流程。")
            loop = asyncio.get_event_loop()  # 获取当前事件循环, 用于执行同步IO操作
            download_success = False

            # 检查 ZIP 文件是否已下载
            if os.path.exists(zip_file_path):
                logger.info(f"ZIP 文件 {zip_file_path} 已存在, 跳过下载步骤。")
                download_success = True
            else:
                logger.info(f"ZIP 文件 {zip_file_path} 不存在, 开始下载...")
                # 在线程池中执行同步的下载操作, 避免阻塞 asyncio 事件循环
                downloaded_path = await loop.run_in_executor(
                    None, download_file_sync, download_url, self.vendor_dir, zip_filename
                )
                if downloaded_path:
                    logger.info(f"ZIP 文件已成功下载到: {downloaded_path}")
                    download_success = True
                else:
                    logger.error(f"下载 ZIP 文件 {zip_filename} 失败。")

            # 如果 ZIP 文件存在 (或已成功下载)
            if download_success:
                logger.info(f"准备解压 ZIP 文件: {zip_file_path} 到目录: {extract_to_dir}")
                # 在线程池中执行同步的解压操作
                unzip_ok = await loop.run_in_executor(
                    None, unzip_file_sync, zip_file_path, extract_to_dir
                )
                if unzip_ok:
                    logger.info(f"ZIP 文件解压成功。现在检查目标可执行文件: {potential_executable_path}")
                    if os.path.exists(potential_executable_path):
                        self.yume_card_executable = potential_executable_path
                        logger.info(f"YumeCard 主程序已成功准备就绪: {self.yume_card_executable}")
                        core_files_ready = True
                    else:
                        # 解压成功但找不到预期的文件, 提示用户检查配置和 ZIP 包内容
                        logger.error(
                            f"ZIP 包已解压, 但在预期路径未能找到 YumeCard 主程序: {potential_executable_path}。\n"
                            f"请检查常量配置 `WINDOWS_EXECUTABLE_REL_PATH` 或 `LINUX_EXECUTABLE_REL_PATH` ('{expected_executable_rel_to_vendor_path}') \n"
                            f"是否与 ZIP 包实际解压后的文件结构 ({self.vendor_dir} 目录内) 一致。"
                        )
                else:
                    logger.error(f"解压 ZIP 文件 {zip_file_path} 失败。")
            else:
                # 下载失败则无法进行后续解压
                logger.error("由于 ZIP 文件下载失败, 无法进行解压操作。")

        # ---- 3. 更新/生成 YumeCard 的 config.json ----
        # 无论核心可执行文件是否最终找到 (可能用户只想用其资源或配置功能),
        # 只要 YumeCard_core 目录 (self.vendor_dir) 存在, 就应该尝试生成或更新其配置文件。
        if os.path.exists(self.vendor_dir):
            logger.info("YumeCard 核心文件处理流程结束或目录已存在, 开始生成/更新其 config.json...")
            if self._update_yumecard_config_file():
                logger.info("YumeCard 的 config.json 已成功根据 AstrBot 用户配置更新。")
            else:
                logger.warning("未能成功更新 YumeCard 的 config.json。请检查以上日志获取详细信息。")
        else:
            # 这种情况理论上不应发生, 因为 initialize 开始时会创建 self.vendor_dir
            logger.error(f"关键目录 {self.vendor_dir} 不存在, 无法处理 YumeCard 的配置文件。")

        # ---- 初始化完成总结 ----
        if self.yume_card_executable:
            logger.info(f"YumeCard 插件初始化成功完成。YumeCard 主程序路径: {self.yume_card_executable}")
        else:
            logger.warning(
                "YumeCard 插件初始化完成, 但 YumeCard 主程序未能成功准备或找到。部分功能可能受限。请检查以上日志获取详细错误信息。")

    @filter.command("check_yumecard_local")
    async def check_yumecard_command(self, event: AstrMessageEvent):
        """
        一个 AstrBot 命令, 用于检查 YumeCard 依赖和配置的当前状态。
        """
        response_parts = []
        # 检查可执行文件状态
        if self.yume_card_executable and os.path.exists(self.yume_card_executable):
            response_parts.append(f"YumeCard 主程序状态: 已准备就绪\n  路径: {self.yume_card_executable}")
        else:
            response_parts.append(
                f"YumeCard 主程序状态: 未准备好或路径配置错误 (预期路径: {os.path.join(self.vendor_dir, LINUX_EXECUTABLE_REL_PATH if platform.system() == 'Linux' else WINDOWS_EXECUTABLE_REL_PATH)})")

        # 检查 YumeCard 配置文件状态
        if os.path.exists(self.yumecard_config_file_path):
            response_parts.append(f"YumeCard 配置文件状态: 存在\n  路径: {self.yumecard_config_file_path}")
            # 可选: 读取少量配置内容用于快速验证, 但注意不要泄露敏感信息如 token
            try:
                with open(self.yumecard_config_file_path, 'r', encoding='utf-8') as f_conf:
                    conf_data_sample = json.load(f_conf)
                    gh_conf = conf_data_sample.get("GitHub", {})
                    response_parts.append(f"  配置的 GitHub 用户名: {gh_conf.get('username', '未在config.json中找到')}")
                    response_parts.append(f"  配置的仓库数量: {len(gh_conf.get('repository', []))}")
            except Exception as e:
                response_parts.append(f"  读取配置文件内容时出错: {e}")
        else:
            response_parts.append(f"YumeCard 配置文件状态: 不存在\n  预期路径: {self.yumecard_config_file_path}")

        # 报告 vendor 目录状态
        status_message = "\n".join(response_parts)
        if self.vendor_dir:  # 确保 self.vendor_dir 已被正确初始化
            if os.path.exists(self.vendor_dir):
                status_message += f"\n\nYumeCard 核心文件目录 (YumeCard_core):\n  {self.vendor_dir} (存在)"
            else:
                status_message += f"\n\nYumeCard 核心文件目录 (YumeCard_core):\n  {self.vendor_dir} (不存在)"

        yield event.plain_result(status_message)

    async def terminate(self):
        """
        插件停用/卸载时由 AstrBot 调用的方法。
        可用于执行一些清理工作, 例如关闭网络连接、释放资源等。
        """
        logger.info("YumeCard 插件终止。")