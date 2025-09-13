# 🌟 GitHub Star Manager - AstrBot插件

> 一个智能的GitHub插件Star管理器，帮助你点赞优质的AstrBot插件

[![GitHub](https://img.shields.io/badge/GitHub-shannai37-blue?logo=github)](https://github.com/shannai37)
[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-green)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.8+-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## ✨ 功能特性

### 🔍 智能插件发现
- 🎯 **精准搜索**：基于 [AstrBot_Plugins_Collection](https://github.com/AstrBotDevs/AstrBot_Plugins_Collection) 的官方插件数据库
- 🔤 **多种标识符**：支持插件ID、短名称、完整名称搜索
- 📄 **分页浏览**：每页显示8个插件，支持翻页浏览
- ⭐ **实时star数**：显示最新的GitHub star数量
- 🏷️ **智能排序**：按star数量和相关性排序

### 🌟 一键点Star
- 🎯 **多种方式**：支持数字ID、短名称、完整名称点star
- 🛡️ **防重复检查**：自动检测是否已点star
- 📊 **实时反馈**：显示当前star数量和操作结果
- ⚡ **快速操作**：优化的API调用，响应迅速

## 📥 安装流程

### 1. 获取GitHub Personal Access Token

1. 访问 [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. 点击 "Generate new token (classic)"
3. 选择以下权限：
   - ✅ `public_repo` - 访问公开仓库
   - ✅ `user` - 读取用户信息
4. 复制生成的token（形如：`ghp_xxxxxxxxxxxx`）

### 2. 安装插件

1. 将 `github_star_plugin` 文件夹复制到AstrBot的插件目录
2. 重启AstrBot或重新加载插件
3. 在插件列表中启用 "GitHub Star Manager"

### 3. 配置插件

在AstrBot的插件配置页面中设置：

```json
{
  "github_token": "你的GitHub Personal Access Token",
  "github_username": "你的GitHub用户名",
  "allowed_users": "{\"用户QQ号1\": true, \"用户QQ号2\": true}",
  "api_settings": {
    "request_timeout": 15,
    "max_retries": 3,
    "enable_fallback": true
  }
}
```

> **💡 提示**：如果 `allowed_users` 为空或 `{}`，则允许所有用户使用插件

## 📋 使用指南

### 🔍 搜索命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/find_plugins [关键词] [页码]` | 搜索AstrBot插件（支持分页） | `/find_plugins 天气 2` |
| `/find_by_author <作者>` | 按作者搜索插件 | `/find_by_author 木有知` |

### ⭐ 点Star命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/star_plugin <ID或名称>` | 给插件点star | `/star_plugin 1` |
| `/check_star <ID或名称>` | 检查插件star状态 | `/check_star weather_api` |

### 🛠️ 管理命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/my_github` | 查看GitHub账号信息 | `/my_github` |
| `/test_network` | 测试GitHub API连通性 | `/test_network` |
| `/update_plugins` | 手动更新插件数据库 | `/update_plugins` |
| `/debug_config` | 调试配置信息 | `/debug_config` |
| `/github_help` | 显示帮助信息 | `/github_help` |

## 🎯 使用示例

### 搜索插件
```
用户: /find_plugins 天气

机器人: 🔍 关键词: 天气 - 找到 5 个插件 (第1/1页):

[1] 📦 weather_api
    👤 dev*** | ⭐ 245
    📝 实时天气查询插件，支持多城市天气预报功能，提供详细的气象信息...
    🔗 https://github.com/***/***/...

[15] 📦 weather_forecast
    👤 dev*** | ⭐ 123
    📝 天气预报插件，提供未来7天天气预测，支持降雨概率和温度趋势...
    🔗 https://github.com/***/***/...

💡 使用 /star_plugin <ID或名称> 来给插件点star
💡 示例: /star_plugin 1 或 /star_plugin weather_api
```

### 给插件点Star
```
用户: /star_plugin 1

机器人: ⭐ 正在给 [1] weather_api 点star...
       🌟 成功给 weather_api 点star！
       当前⭐数量: 246
```

### 按作者搜索
```
用户: /find_by_author 木有知

机器人: 🔍 作者 '木有知' 的插件 - 找到 2 个插件 (第1/1页):

[8] 📦 example_plugin
    👤 木有知 | ⭐ 156
    📝 一个示例插件，展示基本的AstrBot插件开发模式...
    🔗 https://github.com/***/***/...
```

### 网络测试
```
用户: /test_network

机器人: 🔍 测试GitHub API连通性...
       🔧 未配置代理，使用直连

       📊 网络连通性测试结果:

       ✅ api.github.com (245ms)

       🚀 推荐使用: api.github.com (245ms)
```

## 🎨 插件标识符说明

| 类型 | 格式 | 示例 | 说明 |
|------|------|------|------|
| 数字ID | `[数字]` | `[1] [2] [3]` | 显示在搜索结果中的编号 |
| 短名称 | `简化名称` | `weather_api` | 自动生成的简短名称 |
| 完整名称 | `完整插件名` | `astrbot_plugin_weather_api` | GitHub仓库的完整名称 |

### 使用方式
- `/star_plugin 1` - 使用数字ID
- `/star_plugin weather_api` - 使用短名称  
- `/star_plugin astrbot_plugin_weather_api` - 使用完整名称

## ⚙️ 高级配置

### API设置优化

```json
{
  "api_settings": {
    "request_timeout": 15,     // 请求超时时间（秒）
    "max_retries": 3,          // 最大重试次数
    "enable_fallback": true    // 启用API端点故障转移
  }
}
```

## 🔧 故障排除

### 常见问题

#### 1. "GitHub token无效或已过期"
- ✅ 检查token是否正确复制（不要包含空格）
- ✅ 确认token具有 `public_repo` 权限
- ✅ 检查token是否已过期
- ✅ 使用 `/debug_config` 检查配置状态

#### 2. "插件未正确初始化"
- ✅ 检查GitHub token配置
- ✅ 使用 `/test_network` 测试网络连接
- ✅ 使用 `/update_plugins` 手动更新插件数据

#### 3. "未找到插件"
- ✅ 使用 `/find_plugins` 浏览所有可用插件
- ✅ 尝试使用插件的短名称或完整名称
- ✅ 检查插件是否在 [AstrBot插件集合](https://github.com/AstrBotDevs/AstrBot_Plugins_Collection) 中

#### 4. "权限不足"
- ✅ 检查 `allowed_users` 配置格式
- ✅ 确认用户QQ号在白名单中
- ✅ 使用 `/debug_config` 查看权限状态

### 调试工具

```bash
# 查看配置状态
/debug_config

# 测试网络连通性
/test_network
```

## 📊 性能特性

- ⚡ **高性能搜索**：基于内存的快速模糊匹配
- 🔄 **智能缓存**：插件数据库1小时自动缓存
- 📡 **实时更新**：搜索时自动更新前10个插件的star数
- 🌐 **网络优化**：多端点故障转移和重试机制
- 📈 **可扩展性**：支持大量插件数据的高效处理

## 🏗️ 技术架构

- **数据源**：[AstrBot_Plugins_Collection](https://github.com/AstrBotDevs/AstrBot_Plugins_Collection) 官方插件数据库
- **API**：GitHub REST API v3
- **缓存**：内存缓存 + TTL机制
- **搜索**：加权模糊匹配算法
- **网络**：aiohttp异步HTTP客户端

## 👨‍💻 作者信息

**作者**: 山萘 (shannai37)  
**GitHub**: [https://github.com/shannai37](https://github.com/shannai37)  
**主要项目**: [🌟一个德州扑克小游戏插件](https://github.com/shannai37/astrbot_plugin_poker_game)

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

## 📄 更新日志

### v1.0.0 (最新)
- ✨ 新增插件ID系统，支持数字ID快速操作
- ✨ 新增分页浏览功能，优化大量插件展示
- ✨ 新增实时star数更新，显示最新数据
- ✨ 新增按作者搜索功能
- 🔧 优化代码结构，统一显示格式
- 🐛 修复点star状态码判断问题
- 🐛 修复作者搜索ID同步问题
- ⚡ 性能优化，提升搜索和显示速度

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🔗 相关链接

- 🤖 [AstrBot官方仓库](https://github.com/Soulter/AstrBot)
- 📦 [AstrBot插件集合](https://github.com/AstrBotDevs/AstrBot_Plugins_Collection)
- 📚 [GitHub API文档](https://docs.github.com/en/rest)

---

**💖 如果这个插件对你有帮助，请给个Star支持一下！**

**🐛 如有问题，请访问 [Issues](https://github.com/shannai37/astrbot_plugin_poker_game/issues) 页面报告**