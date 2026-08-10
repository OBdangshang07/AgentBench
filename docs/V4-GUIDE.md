# AgentBench Desktop 4.0 使用指南

AgentBench Desktop 4.0 是完全在 Windows 本机运行的 Agent 可视化操作平台与 AI 能力评测工作站。客户端、API、SQLite、会话文件和产物均保存在本机，不需要部署 AgentBench 服务器。

## 首次使用

1. 在“模型与 Agent”检查需要使用的 CLI，并按页面提示完成安装、登录或 Provider 配置。
2. 从 Agent 来源读取模型目录；例如 Reasonix 会读取 `reasonix doctor --json` 中已配置且具备密钥的 Provider。
3. 在“项目中心”选择一个本地目录，设置默认 Agent、模型和权限档位。
4. 进入 Agent Studio 发起会话，或在任务中心、Agent Flow 中启动自动化任务。

API Key 只保存在当前用户的系统凭据库。项目、安装包、数据库备份和导出报告不会携带登录状态或 API Key。

## Agent Studio

Studio 是单个 Agent 的主要操作界面：

- 中央活动流实时展示公开的命令、工具、文件变化、测试和阶段结果。
- 左侧显示项目文件树与最近会话，右侧显示 Agent、审批、Token、费用和用时。
- “文件预览”用于查看项目文件；“变更”用于审核 Diff，可以接受、拒绝并安全还原，或编辑后部分应用。
- `standard` 和 `full` 权限可启动 ConPTY 交互终端；`readonly` 与 `workspace` 不允许启动终端。
- 原生 CLI Agent 第一次操作项目前会挂起并请求审批。批准后原 Turn 自动恢复，无需重新发送消息。

平台不读取、展示或持久化私有思维链。录屏中可见的是公开活动、工具结果、文件变化和简短进度。

## 权限档位

| 档位 | 文件读取 | 文件写入 | Agent 命令 | 交互终端 |
| --- | --- | --- | --- | --- |
| `readonly` | 是 | 否 | 否 | 否 |
| `workspace` | 是 | 是 | 否 | 否 |
| `standard` | 是 | 是 | 审批后 | 是 |
| `full` | 是 | 是 | 审批后 | 是 |

审批可选择“允许一次”“本会话允许”“项目级允许”或“拒绝”。项目级规则只匹配同一项目、同一 Agent 和同一请求类型。

## 任务中心

点击任务“开始”会创建真实 Agent Session、执行任务并同步完成或失败状态。运行中的任务可以跳转 Studio 查看公开过程，也可以停止；停止会终止对应 Agent 的完整子进程树。

## Agent Flow

Flow 用有向无环图组织 Agent、人工审批、条件和 MCP 工具节点：

- 没有依赖关系的同层 Agent 可并行执行。
- Git 项目中的并行 Agent 使用独立 worktree，合并前检查主工作区是否出现冲突。
- Flow 可设置失败重试、并发数、最大用时、Token 和费用预算。
- 人工审批节点会真实暂停 DAG；取消 Flow 会取消活动 Session 并停止子进程树。
- 每个 Agent 节点都能跳转到对应 Studio Session 查看活动和文件变化。

并行任务建议使用干净的 Git 项目。若 Agent 修改了同一文件且主工作区也出现不同内容，安全合并会失败并保留现场供人工处理。

## 工具与 MCP

MCP 页面支持：

- stdio Server：填写可执行文件、参数和环境变量引用。
- Streamable HTTP：填写 MCP HTTP 地址。
- SSE：进行可达性和连接状态检查。

健康检查会完成 MCP 初始化并读取 `tools/list`。工具可在页面直接调用，也可配置为 Flow 工具节点。环境变量密钥存放在系统凭据库，SQLite 只保存引用。

## Benchmarks

Benchmarks Hub 保留原有能力评测：难度 1–5、Ultra 三轮任务、2025 考研数学（一）、排行榜、匿名多裁判、时间和 Token/费用轻权重评分，以及 NCRE Office。NCRE Office 的题目、素材和验证器在 4.0 中保持冻结。

## 数据升级与分发

- 3.x 数据库首次由 4.0 打开时会自动升级到 Schema v6，并先写入 `migration-backups/`。
- 安装包可以直接分享。其他用户不需要修改源码，但必须在自己的电脑安装并登录所需 Agent CLI。
- 卸载客户端不会自动删除用户数据；备份、恢复和数据目录位置可在“本地设置”查看。
