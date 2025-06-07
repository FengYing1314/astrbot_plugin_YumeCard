# YumeCard AstrBot 插件

这是一个为 [YumeCard](https://github.com/YumeYuka/YumeCard) 项目开发的 AstrBot 插件，提供自动化的依赖管理和配置功能。

## 📋 功能特性

- **自动依赖下载**: 根据运行环境（Windows/Linux）自动下载对应的 YumeCard 核心文件
- **智能配置管理**: 将 AstrBot 的配置自动转换为 YumeCard 所需的 config.json 格式
- **GitHub 集成**: 支持配置 GitHub 用户名、Token 和仓库跟踪
- **实时监控**: 后台自动监控 GitHub 仓库更新并生成提交卡片
- **文件系统监听**: 使用 watchdog 监听图片生成，确保及时推送
- **状态检查**: 提供完整的命令集来检查和管理插件运行状态
- **跨平台支持**: 支持 Windows 和 Linux 系统
- **易于安装**: 只需将插件放入 AstrBot 的插件目录即可使用
- **sha256校验**: 确保下载的核心文件完整性

## 🚀 安装和使用

### 前置要求

1. 已安装 [AstrBot](https://github.com/AstrBotDevs/AstrBot)
2. Python 3.8+ 环境
3. 网络连接（用于下载 YumeCard 核心文件）

### 安装插件

1. 将插件文件夹放置在 AstrBot 的插件目录中
2. 重启 AstrBot 或通过插件管理界面加载插件

### 配置说明

插件会在 AstrBot 配置界面中添加 "GitHub" 配置块，包含以下选项：

#### 必填配置

- **username**: GitHub 用户名（YumeCard 功能围绕此用户展开）
- **token**: GitHub 个人访问令牌（PAT），需要具有仓库读取权限
- **repository**: 要跟踪的仓库列表，至少需要配置一个仓库的 `repo` 字段

#### 可选配置

- **refresh_interval_seconds**: 数据刷新间隔（秒），默认 3600（1小时）
- **backgrounds**: 是否启用 GitHub 背景图功能，默认 true
- **notification_targets**: 通知推送目标列表，配置接收图片通知的群组或私聊

#### 仓库配置示例

repository 字段是一个列表，每个元素都是一个仓库配置对象。基本格式如下：

```json
{
  "owner": "YumeYuka",
  "repo": "YumeCard", 
  "branch": "main",
  "lastsha": ""
}
```

## 🔧 使用命令

### 基础状态命令

#### 检查本地状态
```
/check_yumecard_local
```

显示：
- YumeCard 主程序状态和路径
- 配置文件状态和基本信息
- 核心文件目录状态
- Style 目录状态和文件统计
- 文件权限状态（Linux）
- 运行准备状态
- 通知配置信息

#### 启动 YumeCard 主程序
```
/start_yumecard
```

功能：
- 检查 YumeCard 是否已准备就绪
- 在正确的工作目录中启动 YumeCard 主程序
- 自动设置文件权限（Linux）
- 返回启动状态和相关路径信息

#### 启动 YumeCard 监听模式
```
/yumecard_run
```

功能：
- 启动 YumeCard 的持续监听模式
- 自动检查仓库更新并生成卡片
- 使用配置的检查间隔
- 后台持续运行

#### 停止 YumeCard 进程
```
/yumecard_kill
```

功能：
- 停止正在运行的 YumeCard 进程
- 优雅终止或强制杀死进程
- 清理进程状态

#### 测试通知功能
```
/yumecard_test
```

功能：
- 测试通知发送功能
- 如果存在测试图片则发送测试图片
- 否则发送测试文本消息
- 显示发送结果统计

### 通知订阅管理命令（管理员专用）

#### 订阅通知
```
/yumecard_subscribe
```

功能：
- **仅管理员可用** - 将当前对话（群组或私聊）添加到 YumeCard 通知列表
- 自动获取当前对话的标识符
- 检查是否已经订阅，避免重复添加
- 立即保存配置更改

#### 取消订阅
```
/yumecard_unsubscribe
```

功能：
- **仅管理员可用** - 将当前对话从 YumeCard 通知列表中移除
- 检查订阅状态，提供友好提示
- 立即保存配置更改

#### 查看订阅列表
```
/yumecard_subscribers
```

功能：
- **仅管理员可用** - 显示所有已订阅 YumeCard 通知的对话
- 区分群组和私聊类型
- 高亮显示当前对话
- 显示订阅者总数

#### 手动发送通知
```
/yumecard_notify [message]
```

功能：
- **仅管理员可用** - 手动向所有订阅者发送测试通知
- 可自定义通知消息内容
- 显示发送成功和失败的统计
- 用于测试通知功能是否正常

## 🔧 使用命令

### 基础管理命令

| 命令 | 功能 | 说明 |
|------|------|------|
| `/check_yumecard_local` | 检查本地状态 | 显示完整的本地状态信息 |
| `/start_yumecard` | 启动主程序 | 一次性启动 YumeCard |
| `/yumecard_run` | 启动监听模式 | 持续运行和监控 |
| `/yumecard_kill` | 停止进程 | 停止 YumeCard 进程 |
| `/yumecard_test` | 测试通知 | 测试通知发送功能 |

### 状态查询命令

| 命令 | 功能 | 说明 |
|------|------|------|
| `/yumecard_status` | 运行状态 | 显示插件运行状态 |
| `/yumecard_config` | 配置详情 | 显示详细配置信息 |
| `/yumecard_logs` | 运行日志 | 显示日志摘要 |

### 通知订阅命令（管理员专用）

| 命令 | 功能 | 权限要求 | 说明 |
|------|------|----------|------|
| `/yumecard_subscribe` | 订阅通知 | **管理员** | 将当前对话加入通知列表 |
| `/yumecard_unsubscribe` | 取消订阅 | **管理员** | 将当前对话移出通知列表 |
| `/yumecard_subscribers` | 订阅列表 | **管理员** | 显示所有通知订阅者 |
| `/yumecard_notify [message]` | 手动通知 | **管理员** | 发送测试通知到所有订阅者 |

### 监控管理命令

| 命令 | 功能 | 说明 |
|------|------|------|
| `/yumecard_restart` | 重启监控 | 重启后台监控任务 |
| `/yumecard_stop` | 停止监控 | 停止后台监控任务 |

## 📁 文件结构

```
astrbot_plugin_YumeCard/
├── main.py                    # 插件主文件
├── metadata.yaml             # 插件元数据
├── _conf_schema.json         # 配置文件模式
├── requirements.txt          # Python 依赖
├── README.md                 # 说明文档
├── README_YumeCard.md        # YumeCard 原项目文档
├── LICENSE                   # 许可证文件
└── YumeCard_core/           # YumeCard 核心文件（自动创建）
    ├── YumeCard.exe         # Windows 可执行文件
    ├── YumeCard             # Linux 可执行文件
    ├── Style/               # 样式和输出目录
    └── config/              # YumeCard 配置目录
        └── config.json      # YumeCard 配置文件（自动生成）
```

## ⚙️ 工作原理

1. **初始化阶段**: 插件启动时会检测操作系统，下载对应的 YumeCard 核心文件
2. **配置转换**: 将 AstrBot 的用户配置转换为 YumeCard 期望的 config.json 格式
3. **文件监听**: 启动 watchdog 监听器，监控 Style 目录中的新图片文件
4. **后台监控**: 定期检查配置的 GitHub 仓库更新，触发 YumeCard 生成图片
5. **自动推送**: 检测到新图片后，自动推送到配置的通知目标

## 🐛 故障排除

### 常见问题

1. **下载失败**: 检查网络连接和防火墙设置
2. **配置错误**: 确保 GitHub Token 具有正确的权限
3. **路径问题**: 检查插件目录的读写权限
4. **监控未启动**: 使用 `/yumecard_status` 检查状态，使用 `/yumecard_restart` 重启

### 状态诊断

使用 `/yumecard_status` 命令可以快速诊断插件状态：
- 如果显示 ❌，说明对应功能未正常运行
- 检查错误次数和成功率，判断是否有网络或配置问题
- 查看最后检查时间，确认监控是否正常工作

### 日志查看

- 使用 `/yumecard_logs` 查看插件运行摘要
- 查看 AstrBot 主日志获取详细错误信息
- 使用 `/yumecard_restart` 重置错误计数器

## 📄 许可证

本项目采用 GNU Affero General Public License v3.0 许可证。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request 来改进这个插件。

## ⚠️ 免责声明

本插件仅供学习和研究使用。使用过程中产生的任何问题，作者不承担责任。请确保遵守相关法律法规和服务条款。

---

**相关链接:**
- [YumeCard 项目](https://github.com/YumeYuka/YumeCard)
- [AstrBot 项目](https://github.com/AstrBotDevs/AstrBot)

### 使用建议

1. **初始化检查**: 插件安装后，先使用 `/check_yumecard_local` 检查状态
2. **配置通知**: **管理员**在需要接收通知的群组或私聊中使用 `/yumecard_subscribe` 订阅通知
3. **启动监听**: 使用 `/yumecard_run` 启动持续监听模式
4. **状态监控**: 定期使用 `/yumecard_status` 检查运行状态
5. **测试功能**: **管理员**使用 `/yumecard_test` 或 `/yumecard_notify` 测试通知发送是否正常
6. **管理订阅**: **管理员**使用 `/yumecard_subscribers` 查看订阅列表，使用 `/yumecard_unsubscribe` 取消不需要的订阅
7. **故障排除**: 使用各种状态查询命令诊断问题

### 通知订阅管理（管理员功能）

#### 权限说明

通知订阅管理功能仅限管理员使用，这是为了：
- **安全控制**: 防止普通用户随意修改通知配置
- **权限管理**: 确保只有管理员能够决定哪些对话接收通知
- **配置保护**: 避免意外的配置更改影响系统稳定性

#### 快速订阅流程（管理员操作）

1. **在目标群组或私聊中发送**（需要管理员权限）:
   ```
   /yumecard_subscribe
   ```

2. **确认订阅成功**:
   插件会显示订阅成功信息，包含对话类型和ID

3. **查看所有订阅**（需要管理员权限）:
   ```
   /yumecard_subscribers
   ```

4. **测试通知**（需要管理员权限）:
   ```
   /yumecard_notify 测试消息
   ```

#### 订阅管理最佳实践

- **群组订阅**: 适合团队协作，所有成员都能看到提交通知，但只有管理员能修改订阅设置
- **私聊订阅**: 适合个人使用，避免打扰他人，管理员可以为特定用户设置私聊通知
- **定期检查**: 管理员使用 `/yumecard_subscribers` 定期检查订阅列表
- **测试通知**: 订阅后管理员建议使用 `/yumecard_notify` 测试功能是否正常
- **权限分离**: 普通用户可以接收通知，但无法修改通知设置，确保系统安全

#### 非管理员用户说明

如果您不是管理员但需要：
- **接收通知**: 请联系管理员在相应对话中执行订阅操作
- **停止通知**: 请联系管理员取消对应对话的订阅
- **查看状态**: 可以使用 `/yumecard_status` 查看插件运行状态（无需管理员权限）
