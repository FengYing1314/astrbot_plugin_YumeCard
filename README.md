# YumeCard AstrBot 插件

这是一个为 [YumeCard](https://github.com/YumeYuka/YumeCard) 项目开发的 AstrBot 插件，提供自动化的依赖管理和配置功能。

## 📋 功能特性

- **自动依赖下载**: 根据运行环境（Windows/Linux）自动下载对应的 YumeCard 核心文件
- **智能配置管理**: 将 AstrBot 的配置自动转换为 YumeCard 所需的 config.json 格式
- **GitHub 集成**: 支持配置 GitHub 用户名、Token 和仓库跟踪
- **状态检查**: 提供命令来检查 YumeCard 依赖和配置状态
- **跨平台支持**: 支持 Windows 和 Linux 系统

> **⚠️ 功能限制**: 当前版本仅提供依赖下载和配置管理功能，**暂不支持一键运行 YumeCard**。需要手动启动 YumeCard 程序。未来版本将考虑添加一键启动功能。

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

**完整的 repository 配置示例:**

```json
[
  {
    "owner": "YumeYuka",
    "repo": "YumeCard",
    "branch": "main",
    "lastsha": ""
  },
  {
    "owner": "FengYing1314",
    "repo": "astrbot_plugin_YumeCard",
    "branch": "main",
    "lastsha": ""
  }
]
```

**字段说明:**
- `owner`: 仓库所有者/组织名（可选，默认为空）
- `repo`: 仓库名称（**必填**）
- `branch`: 要跟踪的分支名（可选，默认为 "main"）
- `lastsha`: 最后同步的 SHA-1 值（由插件自动管理，无需手动配置）

注意：`lastsha` 字段由插件自动管理，无需手动配置。

## 🔧 使用命令

### 检查状态命令

```
/check_yumecard_local
```

此命令会显示：
- YumeCard 主程序状态和路径
- 配置文件状态和基本信息
- 核心文件目录状态

### 手动启动 YumeCard

插件完成初始化后，可以通过以下方式手动启动 YumeCard：

**Windows:**
```bash
cd d:\program\AstrBot\data\plugins\astrbot_plugin_YumeCard\YumeCard_core
.\YumeCard.exe
```

**Linux:**
```bash
cd /path/to/AstrBot/data/plugins/astrbot_plugin_YumeCard/YumeCard_core
./YumeCard
```

## 📁 文件结构

```
astrbot_plugin_YumeCard/
├── main.py                    # 插件主文件
├── metadata.yaml             # 插件元数据
├── _conf_schema.json         # 配置文件模式
├── README.md                 # 说明文档
├── LICENSE                   # 许可证文件
└── YumeCard_core/           # YumeCard 核心文件（自动创建）
    ├── YumeCard.exe         # Windows 可执行文件
    ├── YumeCard             # Linux 可执行文件
    └── config/              # YumeCard 配置目录
        └── config.json      # YumeCard 配置文件（自动生成）
```

## ⚙️ 工作原理

1. **初始化阶段**: 插件启动时会检测操作系统，下载对应的 YumeCard 核心文件
2. **配置转换**: 将 AstrBot 的用户配置转换为 YumeCard 期望的 config.json 格式
3. **自动管理**: 插件会自动创建必要的目录结构，确保 YumeCard 能正常运行

## 🐛 故障排除

### 常见问题

1. **下载失败**: 检查网络连接和防火墙设置
2. **配置错误**: 确保 GitHub Token 具有正确的权限
3. **路径问题**: 检查插件目录的读写权限

### 日志查看

插件会在 AstrBot 日志中记录详细的运行信息，可以通过查看日志来诊断问题。

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
