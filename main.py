import platform
import asyncio
import json
import hashlib
import os
import zipfile
import requests

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig

# --- 核心常量定义 ---

# YumeCard 不同操作系统版本的下载链接
URL_WINDOWS = "https://github.com/YumeYuka/YumeCard/releases/download/0.0.1/build-windows-x64-dev.zip"
URL_LINUX = "https://github.com/YumeYuka/YumeCard/releases/download/0.0.1/build-linux-x64-dev.zip"

# 预期的 ZIP 文件 SHA256 哈希值 (大写)
EXPECTED_SHA256_WINDOWS = "2F7E3D2DCC7421A6B8E3098269E2D1D2E830111B2B2C85F48F84D512F87C6F33"
EXPECTED_SHA256_LINUX = "7A536A0E73FB24ADBA5F61B0EB9921BFE2107F8871737CF27A5E41809130C197"

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


def calculate_sha256_for_zip(file_path: str) -> str | None:
    """
    计算指定文件的 SHA256 哈希值。
    针对中等大小文件 (如 60MB) 优化, 使用分块读取。

    参数:
        file_path (str): 文件的完整路径。

    返回:
        str: 文件的 SHA256 哈希值 (十六进制字符串), 如果发生错误则返回 None。
    """
    sha256_hasher = hashlib.sha256()
    block_size = 8192

    try:
        with open(file_path, 'rb') as f:
            while True:
                data_chunk = f.read(block_size)
                if not data_chunk:
                    break
                sha256_hasher.update(data_chunk)
        return sha256_hasher.hexdigest()  # 返回小写哈希值
    except FileNotFoundError:
        logger.error(f"错误: 文件 '{file_path}' 未找到。")
        return None
    except IOError as e:
        logger.error(f"读取文件 '{file_path}' 时发生IO错误: {e}")
        return None
    except Exception as e:
        logger.error(f"计算哈希时发生未知错误: {e}")
        return None


def unzip_file_sync(zip_path: str, extract_dir: str) -> bool:
    """
    同步解压 ZIP 文件到指定目录, 包含 SHA256 校验。

    参数:
        zip_path (str): ZIP 文件的完整路径。
        extract_dir (str): 文件解压的目标目录。

    返回:
        bool: 解压成功返回 True, 否则返回 False。
    """
    os.makedirs(extract_dir, exist_ok=True)

    current_os = platform.system()
    target_expected_sha256 = None
    if current_os == "Windows":
        target_expected_sha256 = EXPECTED_SHA256_WINDOWS
    elif current_os == "Linux":
        target_expected_sha256 = EXPECTED_SHA256_LINUX
    else:
        logger.warning(f"操作系统平台 '{current_os}' 没有预定义的 SHA256 用于文件 '{zip_path}'。将跳过哈希校验。")

    try:
        # 仅当定义了预期 SHA256 值时才进行校验
        if target_expected_sha256:
            logger.info(f"开始计算文件 '{zip_path}' 的 SHA256 哈希值...")
            actual_sha256_lowercase = calculate_sha256_for_zip(zip_path)

            if actual_sha256_lowercase is None:
                logger.error(f"无法计算文件 '{zip_path}' 的 SHA256 值。解压中止。")
                return False

            if actual_sha256_lowercase.upper() == target_expected_sha256:
                logger.info(f"文件 '{zip_path}' SHA256 校验成功。")
            else:
                logger.error(f"ZIP 文件 {zip_path} 的 SHA256 校验失败! "
                             f"预期 (大写): {target_expected_sha256}, "
                             f"实际计算得到 (转为大写后): {actual_sha256_lowercase.upper()} "
                             f"(原始计算值: {actual_sha256_lowercase}).")
                return False
        else:
            logger.info(f"由于 '{current_os}' 平台未定义预期 SHA256, 跳过对 '{zip_path}' 的哈希校验。")

        logger.info(f"开始解压文件: {zip_path} 到 {extract_dir}")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        logger.info(f"文件 {zip_path} 解压完成!")
        return True
    except zipfile.BadZipFile:
        logger.error(f"文件 {zip_path} 不是一个有效的 ZIP 文件或已损坏。")
    except Exception as e:
        logger.error(f"解压或校验文件 {zip_path} 时发生错误: {e}")
    return False


@register("astrbot_plugin_YumeCard", "FengYing1314", "让AstrBot接入YumeCard!", "1.0.1")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config: AstrBotConfig = config
        self.yume_card_executable: str | None = None
        self.plugin_root_dir: str = os.path.dirname(os.path.abspath(__file__))
        self.vendor_dir: str = os.path.join(self.plugin_root_dir, VENDOR_SUBDIR)
        self.yumecard_config_dir: str = os.path.join(self.vendor_dir, YUME_CARD_CONFIG_SUBDIR_IN_VENDOR)
        self.yumecard_config_file_path: str = os.path.join(self.yumecard_config_dir, YUME_CARD_CONFIG_FILENAME)

        logger.info(f"插件配置已加载。YumeCard 的 config.json 目标路径: {self.yumecard_config_file_path}")

    def _ensure_yumecard_config_dir_exists(self) -> bool:
        try:
            os.makedirs(self.yumecard_config_dir, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"创建 YumeCard 配置目录 {self.yumecard_config_dir} 失败: {e}")
            return False

    def _update_yumecard_config_file(self) -> bool:
        if not self._ensure_yumecard_config_dir_exists():
            logger.warning(
                f"YumeCard 配置目录 {self.yumecard_config_dir} 无法确保存在或创建失败, 跳过更新 config.json。")
            return False

        logger.info(f"准备从 AstrBot 配置更新 YumeCard 的 config.json 文件: {self.yumecard_config_file_path}")
        astrbot_github_config = self.config.get("GitHub")

        if not astrbot_github_config:
            logger.warning(
                "在 AstrBot 配置中未找到 'GitHub' 相关项。请检查插件的 _conf_schema.json 文件以及用户是否已在 AstrBot 面板正确配置。无法生成 YumeCard 的 config.json。")
            return False

        default_repo_list_from_schema_dicts = [
            {
                "owner": "FengYing1314",
                "repo": "astrbot_plugin_YumeCard",
                "branch": "main",
                "lastsha": ""
            }
        ]

        raw_repo_list = astrbot_github_config.get("repository", default_repo_list_from_schema_dicts)
        repo_list_of_dicts_for_yumecard = []

        if isinstance(raw_repo_list, list):
            for item in raw_repo_list:
                if isinstance(item, str):
                    try:
                        parsed_item = json.loads(item)
                        repo_list_of_dicts_for_yumecard.append(parsed_item)
                    except json.JSONDecodeError as e:
                        logger.error(f"无法将仓库配置项字符串 '{item}' 解析为 JSON 对象: {e}")
                elif isinstance(item, dict):
                    repo_list_of_dicts_for_yumecard.append(item)
                else:
                    logger.warning(f"仓库配置列表中遇到未知类型的项: {type(item)}, 内容: {item}")
        else:
            logger.warning(
                f"AstrBot 配置中的 'repository' 不是列表类型 (实际类型: {type(raw_repo_list)}) 或不存在, 将使用预设的默认仓库列表。")
            repo_list_of_dicts_for_yumecard = default_repo_list_from_schema_dicts

        yumecard_config_data = {
            "GitHub": {
                "username": astrbot_github_config.get("username", ""),
                "backgrounds": str(astrbot_github_config.get("backgrounds", True)).lower(),
                "token": astrbot_github_config.get("token", ""),
                "repository": repo_list_of_dicts_for_yumecard,
                "refresh_interval_seconds": astrbot_github_config.get("refresh_interval_seconds", 3600)
            }
        }

        try:
            with open(self.yumecard_config_file_path, 'w', encoding='utf-8') as f:
                json.dump(yumecard_config_data, f, ensure_ascii=False, indent=2)
            logger.info(f"YumeCard 的 config.json 文件已成功写入/更新: {self.yumecard_config_file_path}")
            return True
        except IOError as e:
            logger.error(f"写入 YumeCard 配置文件 {self.yumecard_config_file_path} 失败: {e}")
        except Exception as e:
            logger.error(f"生成 YumeCard 配置文件时发生未知错误: {e}")
        return False

    async def initialize(self):
        logger.info(f"YumeCard 插件初始化流程开始... 插件根目录: {self.plugin_root_dir}")
        logger.info(f"YumeCard 核心文件及依赖将存放在: {self.vendor_dir}")
        os.makedirs(self.vendor_dir, exist_ok=True)

        os_name = platform.system()
        download_url = None
        zip_filename = None
        expected_executable_rel_to_vendor_path = None

        if os_name == "Windows":
            logger.info("当前运行环境为 Windows 系统。")
            download_url = URL_WINDOWS
            zip_filename = URL_WINDOWS.split('/')[-1]
            expected_executable_rel_to_vendor_path = WINDOWS_EXECUTABLE_REL_PATH
        elif os_name == "Linux":
            logger.info("当前运行环境为 Linux 系统。")
            download_url = URL_LINUX
            zip_filename = URL_LINUX.split('/')[-1]
            expected_executable_rel_to_vendor_path = LINUX_EXECUTABLE_REL_PATH
        else:
            logger.warning(
                f"检测到当前操作系统为 {os_name}, 非 Windows 或 Linux, YumeCard 相关功能可能不受支持或无法运行。")
            return

        if not download_url or not zip_filename or not expected_executable_rel_to_vendor_path:
            logger.error("未能确定 YumeCard 的下载链接、ZIP 文件名或预期的可执行文件路径, 初始化失败。")
            return

        potential_executable_path = os.path.join(self.vendor_dir, expected_executable_rel_to_vendor_path)
        zip_file_path = os.path.join(self.vendor_dir, zip_filename)
        extract_to_dir = self.vendor_dir

        core_files_ready = False
        if os.path.exists(potential_executable_path):
            logger.info(f"YumeCard 主程序 {potential_executable_path} 已存在, 无需重复下载和解压。")
            self.yume_card_executable = potential_executable_path
            core_files_ready = True
        else:
            logger.info(f"YumeCard 主程序 {potential_executable_path} 未找到, 开始下载和解压流程。")
            loop = asyncio.get_event_loop()
            download_success = False

            if os.path.exists(zip_file_path):
                logger.info(f"ZIP 文件 {zip_file_path} 已存在, 跳过下载步骤。")
                # 即使文件已存在, 也应该进行SHA256校验, 防止文件损坏或被篡改
                # SHA256校验逻辑已移至 unzip_file_sync, 所以这里直接认为下载(文件准备)是成功的
                # 但如果 unzip_file_sync 中的校验失败, 依然会阻止解压。
                download_success = True  # 标记为 true 以便尝试解压
            else:
                logger.info(f"ZIP 文件 {zip_file_path} 不存在, 开始下载...")
                downloaded_path = await loop.run_in_executor(
                    None, download_file_sync, download_url, self.vendor_dir, zip_filename
                )
                if downloaded_path:
                    logger.info(f"ZIP 文件已成功下载到: {downloaded_path}")
                    download_success = True
                else:
                    logger.error(f"下载 ZIP 文件 {zip_filename} 失败。")

            if download_success:  # 无论 zip_file_path 是已存在还是新下载的
                logger.info(f"准备解压 ZIP 文件: {zip_file_path} 到目录: {extract_to_dir}")
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
                        logger.error(
                            f"ZIP 包已解压, 但在预期路径未能找到 YumeCard 主程序: {potential_executable_path}。\n"
                            f"请检查常量配置 `WINDOWS_EXECUTABLE_REL_PATH` 或 `LINUX_EXECUTABLE_REL_PATH` ('{expected_executable_rel_to_vendor_path}') \n"
                            f"是否与 ZIP 包实际解压后的文件结构 ({self.vendor_dir} 目录内) 一致。"
                        )
                else:
                    logger.error(f"解压 ZIP 文件 {zip_file_path} 失败 (可能由于SHA校验失败或文件损坏)。")
            else:
                logger.error("由于 ZIP 文件下载失败或不存在, 无法进行解压操作。")

        if os.path.exists(self.vendor_dir):
            logger.info("YumeCard 核心文件处理流程结束或目录已存在, 开始生成/更新其 config.json...")
            if self._update_yumecard_config_file():
                logger.info("YumeCard 的 config.json 已成功根据 AstrBot 用户配置更新。")
            else:
                logger.warning("未能成功更新 YumeCard 的 config.json。请检查以上日志获取详细信息。")
        else:
            logger.error(f"关键目录 {self.vendor_dir} 不存在, 无法处理 YumeCard 的配置文件。")

        if self.yume_card_executable:
            logger.info(f"YumeCard 插件初始化成功完成。YumeCard 主程序路径: {self.yume_card_executable}")
        else:
            logger.warning(
                "YumeCard 插件初始化完成, 但 YumeCard 主程序未能成功准备或找到。部分功能可能受限。请检查以上日志获取详细错误信息。")

    @filter.command("check_yumecard_local")
    async def check_yumecard_command(self, event: AstrMessageEvent):
        response_parts = []
        current_os_name = platform.system()
        expected_exec_path_for_os = LINUX_EXECUTABLE_REL_PATH if current_os_name == 'Linux' else WINDOWS_EXECUTABLE_REL_PATH

        if self.yume_card_executable and os.path.exists(self.yume_card_executable):
            response_parts.append(f"YumeCard 主程序状态: 已准备就绪\n  路径: {self.yume_card_executable}")
        else:
            response_parts.append(
                f"YumeCard 主程序状态: 未准备好或路径配置错误 (预期相对路径: {expected_exec_path_for_os} in {self.vendor_dir})")

        if os.path.exists(self.yumecard_config_file_path):
            response_parts.append(f"YumeCard 配置文件状态: 存在\n  路径: {self.yumecard_config_file_path}")
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

        status_message = "\n".join(response_parts)
        if self.vendor_dir:
            if os.path.exists(self.vendor_dir):
                status_message += f"\n\nYumeCard 核心文件目录 (YumeCard_core):\n  {self.vendor_dir} (存在)"
            else:
                status_message += f"\n\nYumeCard 核心文件目录 (YumeCard_core):\n  {self.vendor_dir} (不存在)"

        yield event.plain_result(status_message)

    async def terminate(self):
        logger.info("YumeCard 插件终止。")