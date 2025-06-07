import platform
import asyncio
import json
import hashlib
import os
import zipfile
import subprocess
from typing import Any
from pathlib import Path
import time

import aiohttp  # 替换 requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig
import astrbot.api.message_components as Comp

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

async def download_file_async(url: str, save_dir: str, file_name: str) -> str | None:
    """
    异步下载文件到指定目录。

    参数:
        url (str): 文件的下载链接。
        save_dir (str): 文件保存的目标目录。
        file_name (str): 文件保存的名称。

    返回:
        str | None: 成功则返回完整保存路径, 失败则返回 None。
    """
    full_save_path = os.path.join(save_dir, file_name)
    os.makedirs(save_dir, exist_ok=True)

    if os.path.exists(full_save_path):
        logger.info(f"文件 {full_save_path} 已存在, 跳过下载。")
        return full_save_path
    
    try:
        logger.info(f"开始下载: {url} -> {full_save_path}")
        
        timeout = aiohttp.ClientTimeout(total=300)  # 5分钟超时
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                
                with open(full_save_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
        
        logger.info(f"文件 {file_name} 下载完成!")
        return full_save_path
        
    except aiohttp.ClientError as e:
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
                             f"(原始计��值: {actual_sha256_lowercase}).")
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


class ImageFileHandler(FileSystemEventHandler):
    """监听 YumeCard Style 目录中的图片文件创建事件"""
    
    def __init__(self, plugin_instance):
        super().__init__()
        self.plugin = plugin_instance
        self.last_processed = {}  # 防止重复处理同一文件
        
    def on_created(self, event):
        """当有新文件创建时触发"""
        if event.is_directory:
            return
            
        file_path = event.src_path
        if file_path.lower().endswith('.png'):
            # 防止重复处理
            current_time = time.time()
            if file_path in self.last_processed:
                if current_time - self.last_processed[file_path] < 5:  # 5秒内不重复处理
                    return
            
            self.last_processed[file_path] = current_time
            logger.info(f"检测到新生成的图片文件: {file_path}")
            
            # 使用线程安全的方式将任务提交到主事件循环
            try:
                # 获取主事件循环并在其中创建任务
                main_loop = self.plugin.main_loop
                if main_loop and not main_loop.is_closed():
                    # 使用 call_soon_threadsafe 来安全地从其他线程调度协程
                    asyncio.run_coroutine_threadsafe(
                        self.plugin.send_commit_notification(file_path), 
                        main_loop
                    )
                else:
                    logger.warning("主事件循环不可用，无法发送通知")
            except Exception as e:
                logger.error(f"提交发送通知任务失败: {e}")


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
        self.runNable = False
        
        # 保存主事件循环引用
        self.main_loop = None
        
        # watchdog 相关属性
        self.observer = None
        self.style_dir = os.path.join(self.vendor_dir, "Style")
        
        # 监控任务状态
        self.monitoring_task = None
        self.monitoring_active = False
        self.last_check_time = None
        self.check_count = 0
        self.error_count = 0
        
        # YumeCard 进程管理
        self.yumecard_process = None
        self.yumecard_running = False
        
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
        repo_list_of_dicts_for_yumecard: list[Any] = []

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
        # 保存当前事件循环引用
        self.main_loop = asyncio.get_event_loop()
        
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
            download_success = False

            if os.path.exists(zip_file_path):
                logger.info(f"ZIP 文件 {zip_file_path} 已存在, 跳过下载步骤。")
                download_success = True
            else:
                logger.info(f"ZIP 文件 {zip_file_path} 不存在, 开始下载...")
                # 使用异步下载函数
                downloaded_path = await download_file_async(download_url, self.vendor_dir, zip_filename)
                if downloaded_path:
                    logger.info(f"ZIP 文件已成功下载到: {downloaded_path}")
                    download_success = True
                else:
                    logger.error(f"下载 ZIP 文件 {zip_filename} 失败。")

            if download_success:
                logger.info(f"准备解压 ZIP 文件: {zip_file_path} 到目录: {extract_to_dir}")
                # 在线程池中执行解压操作，避免阻塞事件循环
                loop = asyncio.get_event_loop()
                unzip_ok = await loop.run_in_executor(None, unzip_file_sync, zip_file_path, extract_to_dir)
                
                if unzip_ok:
                    logger.info(f"ZIP 文件解压成功。现在检查目标可执行文件: {potential_executable_path}")
                    if os.path.exists(potential_executable_path):
                        self.yume_card_executable = potential_executable_path
                        logger.info(f"YumeCard 主程序已成功准备就绪: {self.yume_card_executable}")
                        core_files_ready = True
                    else:
                        logger.error(f"ZIP 包已解压, 但在预期路径未能找到 YumeCard 主程序: {potential_executable_path}")
                else:
                    logger.error(f"解压 ZIP 文件 {zip_file_path} 失败")

        if os.path.exists(self.vendor_dir):
            logger.info("YumeCard 核心文件处理流程结束或目录已存在, 开始生成/更新其 config.json...")
            if self._update_yumecard_config_file():
                logger.info("YumeCard 的 config.json 已成功根据 AstrBot 用户配置更新。")
            else:
                logger.warning("未能成功更新 YumeCard 的 config.json。请检查以上日志获取详细信息。")
        else:
            logger.error(f"关键目录 {self.vendor_dir} 不存在, 无法处理 YumeCard 的配置文件。")

        if self.yume_card_executable:
            self.runNable = True
            logger.info(f"YumeCard 插件初始化成功完成。YumeCard 主程序路径: {self.yume_card_executable}")
            
            # 启动文件系统监听
            await self._start_file_watcher()
            
            # 启动延迟监控任务
            self._start_delayed_monitoring()
        else:
            logger.warning("YumeCard 插件初始化完成, 但 YumeCard 主程序未能成功准备或找到。")

    def _start_delayed_monitoring(self):
        """启动延迟监控任务（同步方法）"""
        # 创建异步任务但不使用 await
        if self.main_loop:
            self.main_loop.create_task(self._delayed_start_monitoring())

    async def _delayed_start_monitoring(self):
        """延迟启动监控任务，等待初始化完成"""
        # 等待初始化完成
        await asyncio.sleep(10)
        
        if self.runNable:
            # 获取配置的监控间隔
            github_config = self.config.get("GitHub", {})
            interval = github_config.get("refresh_interval_seconds", 3600)
            
            # 启动监控任务并保存引用
            self.monitoring_task = asyncio.create_task(self.start_monitoring(interval))
            self.monitoring_active = True
            logger.info(f"延迟监控任务已启动，检查间隔: {interval} 秒")

    async def _start_file_watcher(self):
        """启动文件系统监听器，监控 Style 目录中的图片文件"""
        try:
            # 确保 Style 目录存在
            os.makedirs(self.style_dir, exist_ok=True)
            
            # 创建事件处理器
            event_handler = ImageFileHandler(self)
            
            # 创建观察者
            self.observer = Observer()
            self.observer.schedule(event_handler, self.style_dir, recursive=True)
            
            # 启动观察者
            self.observer.start()
            logger.info(f"文件系统监听器已启动，正在监控目录: {self.style_dir}")
            
        except Exception as e:
            logger.error(f"启动文件系统监听器时发生错误: {e}")

    async def check_repository_updates(self, owner: str, repo: str) -> bool:
        """
        检查仓库更新并触发 YumeCard 生成图片
        不再直接发送通知，而是通过 watchdog 监听图片生成后再发送
        """
        if not self.runNable or not self.yume_card_executable:
            logger.warning("YumeCard 未准备就绪，无法检查仓库更新")
            return False
        
        try:
            logger.info(f"检查仓库 {owner}/{repo} 的更新...")
            
            # 切换到 YumeCard 工作目录
            work_dir = self.vendor_dir
            
            # 在 Linux 系统上确保可执行权限
            if platform.system() == "Linux":
                os.chmod(self.yume_card_executable, 0o755)
            
            # 调用 YumeCard 检查仓库更新并生成图片
            # 假设 YumeCard 支持这样的命令行接口
            cmd = [self.yume_card_executable, "check", owner, repo]
            
            logger.info(f"执行 YumeCard 命令: {' '.join(cmd)}")
            
            # 异步执行命令
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"YumeCard 执行成功: {stdout.decode('utf-8', errors='ignore')}")
                return True
            else:
                logger.error(f"YumeCard 执行失败 (返回码: {process.returncode}): {stderr.decode('utf-8', errors='ignore')}")
                return False
                
        except Exception as e:
            logger.error(f"检查仓库更新时发生错误: {e}")
            return False

    async def send_commit_notification(self, image_path: str):
        """发送提交通知图片到配置的群组和私聊"""
        try:
            if not os.path.exists(image_path):
                logger.warning(f"图片文件不存在: {image_path}")
                return
            
            # 等待文件写入完成
            await asyncio.sleep(2)
            
            # 验证文件是否可读
            try:
                with open(image_path, 'rb') as f:
                    file_size = len(f.read())
                if file_size == 0:
                    logger.warning(f"图片文件为空: {image_path}")
                    return
                logger.info(f"检测到图片文件: {image_path}, 大小: {file_size} 字节")
            except Exception as e:
                logger.error(f"无法读取图片文件 {image_path}: {e}")
                return
            
            github_config = self.config.get("GitHub", {})
            targets = github_config.get("notification_targets", [])
            
            if not targets:
                logger.info("未配置推送目标，跳过发送通知")
                filename = os.path.basename(image_path)
                logger.info(f"YumeCard 已生成提交卡片: {filename}")
                return
            
            filename = os.path.basename(image_path)
            logger.info(f"准备发送提交通知图片: {filename} 到 {len(targets)} 个目标")
            
            success_count = 0
            for target in targets:
                try:
                    # 使用 MessageChain 构建消息
                    message_chain = MessageChain().message(f"📸 YumeCard 生成了新的提交卡片: {filename}").file_image(image_path)
                    
                    # 发送消息
                    await self.context.send_message(target, message_chain)
                    logger.info(f"成功发送提交通知图片到: {target}")
                    success_count += 1
                except Exception as e:
                    logger.error(f"发送提交通知到 {target} 失败: {e}")
            
            if success_count > 0:
                logger.info(f"提交卡片已成功发送到 {success_count}/{len(targets)} 个目标")
            else:
                logger.warning("提交卡片发送失败，未能发送到任何目标")
                    
        except Exception as e:
            logger.error(f"发送提交通知时发生错误: {e}")

    async def start_monitoring(self, interval: int = 600):
        """
        启动后台监控任务
        定期检查配置的仓库更新
        """
        if not self.runNable:
            logger.warning("YumeCard 未准备就绪，无法启动监控")
            return
        
        logger.info(f"启动 YumeCard 监控任务，检查间隔: {interval} 秒")
        self.monitoring_active = True
        
        while self.monitoring_active:
            try:
                self.last_check_time = time.time()
                self.check_count += 1
                
                github_config = self.config.get("GitHub", {})
                repositories = github_config.get("repository", [])
                
                for repo_config in repositories:
                    if isinstance(repo_config, dict):
                        owner = repo_config.get("owner", "")
                        repo = repo_config.get("repo", "")
                        
                        if owner and repo:
                            success = await self.check_repository_updates(owner, repo)
                            if not success:
                                self.error_count += 1
                        
                        # 仓库间检查间隔，避免频繁请求
                        await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"监控任务执行时发生错误: {e}")
                self.error_count += 1
            
            # 等待下一次检查
            await asyncio.sleep(interval)

    @filter.command("yumecard")
    async def yumecard_main_command(self, event: AstrMessageEvent, action: str = "status"):
        """YumeCard 主命令 - 支持多种操作"""
        try:
            if action.lower() == "status":
                async for result in self._handle_status(event):
                    yield result
            elif action.lower() == "start":
                async for result in self._handle_start_monitor(event):
                    yield result
            elif action.lower() == "stop":
                async for result in self._handle_stop_monitor(event):
                    yield result
            elif action.lower() == "restart":
                async for result in self._handle_restart_monitor(event):
                    yield result
            elif action.lower() == "config":
                async for result in self._handle_show_config(event):
                    yield result
            elif action.lower() == "test":
                async for result in self._handle_test_notification(event):
                    yield result
            elif action.lower() == "check":
                async for result in self._handle_check_local(event):
                    yield result
            else:
                # 显示帮助信息
                help_msg = """🌙 YumeCard 命令帮助

📋 基本命令:
   /yumecard status   - 查看运行状态
   /yumecard start    - 启动监控模式
   /yumecard stop     - 停止监控模式
   /yumecard restart  - 重启监控模式
   /yumecard config   - 查看配置信息
   /yumecard test     - 测试通知功能
   /yumecard check    - 检查本地状态

🔧 管理命令:
   /yumecard_manage   - 仓库管理菜单
   /yumecard_notify   - 通知管理菜单

💡 快速开始:
   1. 使用 /yumecard check 检查状态
   2. 使用 /yumecard_notify subscribe 订阅通知
   3. 使用 /yumecard start 启动监控"""
                
                yield event.plain_result(help_msg)
        except Exception as e:
            logger.error(f"执行 yumecard 命令时发生错误: {e}")
            yield event.plain_result(f"❌ 操作失败: {str(e)}")

    async def _handle_status(self, event: AstrMessageEvent):
        """处理状态查询"""
        status_parts = []
        status_parts.append("🌙 YumeCard 运行状态")
        status_parts.append("=" * 25)
        
        # 基本状态
        if self.runNable:
            status_parts.append("✅ 插件状态: 已就绪")
        else:
            status_parts.append("❌ 插件状态: 未就绪")
        
        # 监控状态
        if self.monitoring_active and self.monitoring_task and not self.monitoring_task.done():
            status_parts.append("✅ 监控模式: 运行中")
            if self.last_check_time:
                last_check = time.strftime('%H:%M:%S', time.localtime(self.last_check_time))
                status_parts.append(f"   上次检查: {last_check}")
            if self.check_count > 0:
                success_rate = ((self.check_count - self.error_count) / self.check_count) * 100
                status_parts.append(f"   成功率: {success_rate:.1f}% ({self.check_count}次)")
        else:
            status_parts.append("❌ 监控模式: 未运行")
        
        # 文件监听状态
        if self.observer and self.observer.is_alive():
            status_parts.append("✅ 文件监听: 运行中")
        else:
            status_parts.append("❌ 文件监听: 未启动")
        
        # 配置摘要
        github_config = self.config.get("GitHub", {})
        repo_count = len(github_config.get("repository", []))
        target_count = len(github_config.get("notification_targets", []))
        
        status_parts.append(f"\n📊 配置摘要:")
        status_parts.append(f"   监控仓库: {repo_count} 个")
        status_parts.append(f"   通知目标: {target_count} 个")
        
        interval = github_config.get("refresh_interval_seconds", 3600)
        interval_str = f"{interval // 60}分钟" if interval >= 60 else f"{interval}秒"
        status_parts.append(f"   检查间隔: {interval_str}")
        
        yield event.plain_result("\n".join(status_parts))

    async def _handle_start_monitor(self, event: AstrMessageEvent):
        """处理启动监控"""
        if not self.runNable:
            yield event.plain_result("❌ YumeCard 未准备就绪，无法启动监控")
            return
        
        if self.yumecard_running and self.yumecard_process and self.yumecard_process.returncode is None:
            yield event.plain_result("ℹ️ YumeCard 监控模式已在运行中")
            return
        
        # 获取监控间隔并启动
        github_config = self.config.get("GitHub", {})
        interval_seconds = github_config.get("refresh_interval_seconds", 3600)
        interval_minutes = max(1, interval_seconds // 60)
        
        success = await self.start_yumecard_monitor_mode(interval_minutes)
        
        if success:
            yield event.plain_result(f"✅ YumeCard 监控已启动\n"
                                   f"⏰ 检查间隔: {interval_minutes}分钟\n"
                                   f"📁 工作目录: {os.path.basename(self.vendor_dir)}")
        else:
            yield event.plain_result("❌ 监控启动失败，请使用 /yumecard check 检查状态")

    async def _handle_stop_monitor(self, event: AstrMessageEvent):
        """处理停止监控"""
        stopped = False
        
        # 停止 YumeCard 进程
        if self.yumecard_process and self.yumecard_process.returncode is None:
            try:
                self.yumecard_process.terminate()
                await asyncio.wait_for(self.yumecard_process.wait(), timeout=5)
                self.yumecard_process = None
                self.yumecard_running = False
                stopped = True
            except asyncio.TimeoutError:
                self.yumecard_process.kill()
                await self.yumecard_process.wait()
                self.yumecard_process = None
                self.yumecard_running = False
                stopped = True
        
        # 停止内部监控任务
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_active = False
            self.monitoring_task.cancel()
            stopped = True
        
        if stopped:
            yield event.plain_result("✅ YumeCard 监控已停止")
        else:
            yield event.plain_result("ℹ️ YumeCard 监控未在运行")

    async def _handle_restart_monitor(self, event: AstrMessageEvent):
        """处理重启监控"""
        # 先停止
        async for result in self._handle_stop_monitor(event):
            yield result
        await asyncio.sleep(1)
        
        # 重置统计
        self.check_count = 0
        self.error_count = 0
        self.last_check_time = None
        
        # 再启动
        async for result in self._handle_start_monitor(event):
            yield result

    async def _handle_show_config(self, event: AstrMessageEvent):
        """处理显示配置"""
        config_parts = []
        config_parts.append("⚙️ YumeCard 配置")
        config_parts.append("=" * 20)
        
        github_config = self.config.get("GitHub", {})
        
        if not github_config:
            yield event.plain_result("❌ 未找到 GitHub 配置")
            return
        
        # 基本信息
        username = github_config.get("username", "未设置")
        has_token = "已设置" if github_config.get("token") else "未设置"
        config_parts.append(f"👤 用户: {username}")
        config_parts.append(f"🔑 Token: {has_token}")
        
        # 仓库列表
        repositories = github_config.get("repository", [])
        config_parts.append(f"\n📚 监控仓库 ({len(repositories)}个):")
        for i, repo in enumerate(repositories[:5], 1):  # 只显示前5个
            if isinstance(repo, dict):
                owner = repo.get("owner", "")
                repo_name = repo.get("repo", "")
                branch = repo.get("branch", "main")
                config_parts.append(f"   {i}. {owner}/{repo_name} ({branch})")
        
        if len(repositories) > 5:
            config_parts.append(f"   ... 还有 {len(repositories) - 5} 个仓库")
        
        # 通知目标
        targets = github_config.get("notification_targets", [])
        config_parts.append(f"\n📢 通知目标 ({len(targets)}个):")
        for i, target in enumerate(targets[:3], 1):  # 只显示前3个
            display_target = target
            if ":" in target:
                parts = target.split(":")
                if len(parts) >= 3:
                    target_type = "群组" if "Group" in parts[1] else "私聊"
                    display_target = f"{target_type}({parts[2]})"
            config_parts.append(f"   {i}. {display_target}")
        
        if len(targets) > 3:
            config_parts.append(f"   ... 还有 {len(targets) - 3} 个目标")
        
        yield event.plain_result("\n".join(config_parts))

    async def _handle_test_notification(self, event: AstrMessageEvent):
        """处理测试通知"""
        github_config = self.config.get("GitHub", {})
        targets = github_config.get("notification_targets", [])
        
        if not targets:
            yield event.plain_result("❌ 未配置通知目标\n💡 请使用 /yumecard_notify subscribe 订阅通知")
            return
        
        # 查找测试图片
        test_image_path = None
        if os.path.exists(self.style_dir):
            for file in os.listdir(self.style_dir):
                if file.lower().endswith('.png'):
                    test_image_path = os.path.join(self.style_dir, file)
                    break
        
        success_count = 0
        for target in targets:
            try:
                if test_image_path:
                    message_chain = MessageChain().message("🧪 YumeCard 测试通知").file_image(test_image_path)
                else:
                    message_chain = MessageChain().message("🧪 YumeCard 测试通知\n✅ 通知功能正常")
                
                await self.context.send_message(target, message_chain)
                success_count += 1
            except Exception as e:
                logger.error(f"发送测试通知失败: {e}")
        
        result = f"📊 测试完成: {success_count}/{len(targets)} 成功"
        if test_image_path:
            result += f"\n🖼️ 使用图片: {os.path.basename(test_image_path)}"
        
        yield event.plain_result(result)

    async def _handle_check_local(self, event: AstrMessageEvent):
        """处理本地状态检查"""
        status_parts = []
        status_parts.append("🔍 YumeCard 本地检查")
        status_parts.append("=" * 25)
        
        # 检查主程序
        if self.yume_card_executable and os.path.exists(self.yume_card_executable):
            status_parts.append("✅ 主程序: 已准备")
            if platform.system() == "Linux":
                import stat
                file_stat = os.stat(self.yume_card_executable)
                is_executable = bool(file_stat.st_mode & stat.S_IEXEC)
                status_parts.append(f"   🔐 执行权限: {'✅' if is_executable else '❌'}")
        else:
            status_parts.append("❌ 主程序: 未找到")
        
        # 检查配置文件
        if os.path.exists(self.yumecard_config_file_path):
            status_parts.append("✅ 配置文件: 已生成")
        else:
            status_parts.append("❌ 配置文件: 未生成")
        
        # 检查目录
        if os.path.exists(self.vendor_dir):
            status_parts.append("✅ 核心目录: 存在")
        else:
            status_parts.append("❌ 核心目录: 不存在")
        
        if os.path.exists(self.style_dir):
            try:
                png_count = len([f for f in os.listdir(self.style_dir) if f.lower().endswith('.png')])
                status_parts.append(f"✅ Style目录: 存在 ({png_count}张图片)")
            except:
                status_parts.append("⚠️ Style目录: 无法读取")
        else:
            status_parts.append("❌ Style目录: 不存在")
        
        # 运行状态
        status_parts.append(f"\n🚀 运行状态:")
        status_parts.append(f"   插件就绪: {'✅' if self.runNable else '❌'}")
        status_parts.append(f"   文件监听: {'✅' if self.observer and self.observer.is_alive() else '❌'}")
        
        # 建议
        if not self.runNable:
            status_parts.append(f"\n💡 建议: 检查上述错误项并重启插件")
        else:
            github_config = self.config.get("GitHub", {})
            targets = github_config.get("notification_targets", [])
            if not targets:
                status_parts.append(f"\n💡 建议: 使用 /yumecard_notify subscribe 订阅通知")
        
        yield event.plain_result("\n".join(status_parts))

    @filter.command("yumecard_manage")
    async def repository_management(self, event: AstrMessageEvent, action: str = "list", owner: str = "", repo: str = "", branch: str = "main"):
        """仓库管理命令"""
        try:
            if action.lower() == "list":
                async for result in self._handle_list_repositories(event):
                    yield result
            elif action.lower() == "add" and owner and repo:
                async for result in self._handle_add_repository(event, owner, repo, branch):
                    yield result
            elif action.lower() == "check" and owner and repo:
                async for result in self._handle_check_repository(event, owner, repo):
                    yield result
            else:
                help_msg = """📚 仓库管理命令

📋 命令格式:
   /yumecard_manage list
   /yumecard_manage add <用户名> <仓库名> [分支名]
   /yumecard_manage check <用户名> <仓库名>

💡 示例:
   /yumecard_manage add octocat Hello-World main
   /yumecard_manage check octocat Hello-World"""
                
                yield event.plain_result(help_msg)
        except Exception as e:
            logger.error(f"仓库管理命令错误: {e}")
            yield event.plain_result(f"❌ 操作失败: {str(e)}")

    async def _handle_list_repositories(self, event: AstrMessageEvent):
        """处理列出仓库"""
        if not self.runNable:
            yield event.plain_result("❌ YumeCard 未准备就绪")
            return
        
        cmd = [self.yume_card_executable, "list"]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, cwd=self.vendor_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            output = stdout.decode('utf-8', errors='ignore')
            yield event.plain_result(f"📋 订阅的仓库:\n{output}")
        else:
            error_output = stderr.decode('utf-8', errors='ignore')
            yield event.plain_result(f"❌ 获取失败: {error_output}")

    async def _handle_add_repository(self, event: AstrMessageEvent, owner: str, repo: str, branch: str):
        """处理添加仓库"""
        if not self.runNable:
            yield event.plain_result("❌ YumeCard 未准备就绪")
            return
        
        cmd = [self.yume_card_executable, "add", owner, repo, branch]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, cwd=self.vendor_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            output = stdout.decode('utf-8', errors='ignore')
            yield event.plain_result(f"✅ 仓库添加成功\n📚 {owner}/{repo} ({branch})\n{output}")
            self._update_yumecard_config_file()
        else:
            error_output = stderr.decode('utf-8', errors='ignore')
            yield event.plain_result(f"❌ 添加失败: {error_output}")

    async def _handle_check_repository(self, event: AstrMessageEvent, owner: str, repo: str):
        """处理检查仓库"""
        if not self.runNable:
            yield event.plain_result("❌ YumeCard 未准备就绪")
            return
        
        yield event.plain_result(f"🔍 正在检查 {owner}/{repo}...")
        
        cmd = [self.yume_card_executable, "check", owner, repo]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, cwd=self.vendor_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            output = stdout.decode('utf-8', errors='ignore')
            yield event.plain_result(f"✅ 检查完成\n📚 {owner}/{repo}\n{output}")
        else:
            error_output = stderr.decode('utf-8', errors='ignore')
            yield event.plain_result(f"❌ 检查失败: {error_output}")

    @filter.command("yumecard_notify")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def notification_management(self, event: AstrMessageEvent, action: str = "list"):
        """通知管理命令（仅管理员）"""
        try:
            if action.lower() == "list":
                async for result in self._handle_list_subscribers(event):
                    yield result
            elif action.lower() == "subscribe":
                async for result in self._handle_subscribe(event):
                    yield result
            elif action.lower() == "unsubscribe":
                async for result in self._handle_unsubscribe(event):
                    yield result
            elif action.lower() == "test":
                async for result in self._handle_test_notification(event):
                    yield result
            else:
                help_msg = """📢 通知管理命令（仅管理员）

📋 命令格式:
   /yumecard_notify list        - 查看订阅列表
   /yumecard_notify subscribe   - 订阅当前对话
   /yumecard_notify unsubscribe - 取消订阅当前对话
   /yumecard_notify test        - 测试通知功能"""
                
                yield event.plain_result(help_msg)
        except Exception as e:
            logger.error(f"通知管理命令错误: {e}")
            yield event.plain_result(f"❌ 操作失败: {str(e)}")

    async def _handle_list_subscribers(self, event: AstrMessageEvent):
        """处理列出订阅者"""
        github_config = self.config.get("GitHub", {})
        targets = github_config.get("notification_targets", [])
        current_target = event.unified_msg_origin
        
        if not targets:
            yield event.plain_result("📭 暂无订阅者")
            return
        
        subscribers_info = []
        subscribers_info.append(f"📋 通知订阅列表 ({len(targets)}个)")
        subscribers_info.append("=" * 20)
        
        for i, target in enumerate(targets, 1):
            target_display = target
            target_type = "私聊"
            
            if "Group" in target:
                target_type = "群组"
                parts = target.split(":")
                if len(parts) >= 3:
                    target_display = f"群组({parts[2]})"
            else:
                parts = target.split(":")
                if len(parts) >= 3:
                    target_display = f"用户({parts[2]})"
            
            if target == current_target:
                subscribers_info.append(f"   {i}. {target_display} 🔸当前")
            else:
                subscribers_info.append(f"   {i}. {target_display}")
        
        yield event.plain_result("\n".join(subscribers_info))

    async def _handle_subscribe(self, event: AstrMessageEvent):
        """处理订阅通知"""
        target = event.unified_msg_origin
        github_config = self.config.get("GitHub", {})
        targets = github_config.get("notification_targets", [])
        
        if target in targets:
            yield event.plain_result("ℹ️ 当前对话已订阅通知")
            return
        
        targets.append(target)
        github_config["notification_targets"] = targets
        self.config.save_config()
        self._update_yumecard_config_file()
        
        target_type = "群组" if "Group" in target else "私聊"
        yield event.plain_result(f"✅ 订阅成功\n📱 类型: {target_type}\n📊 总数: {len(targets)}")

    async def _handle_unsubscribe(self, event: AstrMessageEvent):
        """处理取消订阅"""
        target = event.unified_msg_origin
        github_config = self.config.get("GitHub", {})
        targets = github_config.get("notification_targets", [])
        
        if target not in targets:
            yield event.plain_result("ℹ️ 当前对话未订阅通知")
            return
        
        targets.remove(target)
        github_config["notification_targets"] = targets
        self.config.save_config()
        self._update_yumecard_config_file()
        
        yield event.plain_result(f"✅ 取消订阅成功\n📊 剩余: {len(targets)}个")

    # 移除旧的重复命令方法，保留核心功能
    # 删除以下方法：
    # - get_yumecard_status -> 已整合到 yumecard status
    # - show_yumecard_config -> 已整合到 yumecard config  
    # - show_recent_logs -> 功能简化
    # - restart_monitoring -> 已整合到 yumecard restart
    # - stop_monitoring -> 已整合到 yumecard stop
    # - start_yumecard_monitor -> 已整合到 yumecard start
    # - stop_yumecard_process -> 已整合到 yumecard stop
    # - add_repository -> 已整合到 yumecard_manage add
    # - check_repository -> 已整合到 yumecard_manage check
    # - list_repositories -> 已整合到 yumecard_manage list
    # - subscribe_notification -> 已整合到 yumecard_notify subscribe
    # - unsubscribe_notification -> 已整合到 yumecard_notify unsubscribe
    # - list_subscribers -> 已整合到 yumecard_notify list
    # - manual_notify -> 功能简化
    # - test_yumecard_notification -> 已整合到 yumecard test
    # - start_yumecard_once -> 功能简化
    # - check_local_status -> 已整合到 yumecard check
