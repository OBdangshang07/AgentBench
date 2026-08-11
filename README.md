# AgentBench Desktop

AgentBench Desktop 是一个 Windows 优先、本地运行的全 Agent 可视化工作台，同时保留完整的 AI 模型能力评测系统。它既能在图形界面中管理项目、长期会话、任务、Flow、MCP、终端与浏览器，也能将不同模型放入统一 Agent Harness，通过确定性验证器、匿名 AI 裁判和成本指标生成可追溯评分。

## V5.0.0：从“能用”到“好用”

- 新增首次使用向导、真实全局搜索、全局审批入口，以及包含运行环境健康和最近失败的控制中心。
- Agent Studio 支持服务端长会话分页、原生文件拖放、停止自动滚动、流式公开进度、折叠工具调用、附件、权限/思考强度切换、Token/费用、Diff、ConPTY 终端和可接管浏览器。
- Agent Flow 新增自动保存、Undo/Redo、缩放/平移/小地图、静态验证、无副作用 Dry Run、自动版本快照、运行历史、版本恢复和失败节点局部重试。
- 项目与任务中心补齐项目健康检查、详情页、前置依赖阻塞、依赖环防护、审批状态同步和明确的下一步操作。
- MCP 工具页提供常用模板、标准 JSON 导入、结构化密钥编辑、离线诊断和真实工具调用测试台。
- 模型与 Agent 配置明确区分模型身份和运行时，并在 Studio、Flow 与测评之间复用；设置页支持无密钥、无提示词的一键诊断报告。
- 路由按需拆包，核心前端包从约 739 KB 降至约 248 KB；高频轮询不再反复传输完整长会话。
- SQLite Schema v10 保留旧项目、会话和全部测评历史，迁移前自动备份，并补充重启恢复、路径越界、符号链接和附件边界回归。
- 测评区及 NCRE Office 题库和评分逻辑保持不变；录屏界面仍只展示公开进度和可验证操作，不展示模型私有思维链。

完整变更见 [`docs/releases/V5.0.0.md`](docs/releases/V5.0.0.md)，基础使用方法见 [`docs/V4-GUIDE.md`](docs/V4-GUIDE.md)。

### 评测能力

- 延续 V3.1.1 的结构级本地评测工作站 UI、套件优先测试库、Viewer-safe 实验/任务直播页、考研数学完整导入与发布工作流
- Tauri 2 + React 桌面界面，FastAPI 本地 Sidecar
- SQLite 本地数据，不需要服务器、Redis 或云存储
- OpenAI-compatible 模型适配器和可离线演示的 Mock 模型
- 统一 Agent 循环、文件工具、受限 Shell/Docker 工具
- 版本化测试 DSL、难度 4/5 复合题与私有验证升级，以及 2 个难度 6 Ultra 三轮挑战
- Ultra 工程题使用任务结束后临时注入的私有故障验证器，按迁移与模式、规范 JSON、多进程、强杀原子性、完整性/快照和文件完整性六项连续评分
- Ultra 调度题要求提交通用 `solver.py`，评分时现场注入未公开的小/中/大型实例，覆盖时间间隔、机器日历、序列切换、替代机器、共享资源、非可再生预算和多目标优化
- 私有验证器启动或注入故障归为平台错误且不消耗 Ultra 轮次；退役题目不进入新排行榜
- Ultra 失败后按固定阶梯给出两次提示，轮次系数为 1.00 / 0.85 / 0.70，并保留工作区继续修复
- 长上下文检索、数据分析、多文件工作流、项目编码、安全修复与规划决策任务
- 推理计算含 20 道高难数学题，覆盖定积分、高阶导数、微分方程、无穷级数和线性代数
- 创建评测时提供推理计算、规划决策、编码工程三个适量的单项能力测试入口
- Codex、Claude Code、OpenCode、Reasonix、Gemini CLI、Aider、Kimi Code、Qoder CLI 和自定义命令 Runner
- Agent 页面为 Codex、Claude Code、OpenCode、Reasonix、Gemini CLI、Aider 和 Kimi Code 提供白名单快捷安装/升级，显示来源、完整命令、实时输出与退出码；Qoder 和自定义 Runner 保持手动配置
- 自动读取 Codex/Claude Code/OpenCode 本机模型目录，并可通过 OpenAI/Anthropic 兼容 API 识别模型；下拉选择保留 Agent Provider 路由，未列出模型仍可手动输入
- 三步实验向导、环境就绪检查、能力地图、参测者对比和能力域可视化
- 客观验证、AI Rubric 裁判、重复运行统计
- 完成时间采用软目标并只占 3%；超时继续执行，独立安全看门狗仅用于终止永久卡死进程
- Token 与费用来源可追溯；支持 CLI 实际费用、模型单价估算和修改单价后回算历史记录
- 原生 CLI 逐行实时事件、5 秒心跳、文件变化、断流补拉、录屏安全过滤和观众模式
- 2025 考研数学（一）支持“本地 PDF 导入 → 22 题逐题校对 → 答案/等价答案/解答题得分点确认 → 闭卷推理与工具增强双套件发布”；真题内容必须人工校对后发布
- 实时运行事件、轨迹回放、文件产物、V2/V3 分代排行榜和报告导出
- Windows Credential Manager 优先的密钥存储
- Docker 检测、默认断网和资源限制；无 Docker 时自动进入受限模式
- Sidecar 使用版本化文件名；客户端启动时核对前后端版本，并只在确认旧进程身份后清理占用端口的旧 AgentBench Sidecar

## 开发启动

```powershell
./scripts/bootstrap.ps1
./scripts/dev.ps1
```

也可以分别启动：

```powershell
./.venv/Scripts/python.exe -m agentbench
pnpm dev
```

前端默认访问 `http://localhost:1420`，本地 API 默认监听 `http://127.0.0.1:43765`。

## 测试与构建

```powershell
./scripts/test.ps1
./scripts/build.ps1
```

正式代码执行任务要求 Docker Desktop。没有 Docker 时，文本推理、结构化输出和受限文件任务仍可运行；Shell 验证会明确标记为环境不可用，绝不会静默回退到宿主机执行。

详细设计见 [`docs/PRODUCT.md`](docs/PRODUCT.md)、[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)、[`docs/SECURITY.md`](docs/SECURITY.md) 和 [`docs/V4-GUIDE.md`](docs/V4-GUIDE.md)。

## 分发给其他人

Windows 安装包可以直接分享，对方不需要修改源码、数据库或 Runner 参数。首次启动会自动创建本地数据，并检查每个执行环境：

- 内置统一 Agent Harness 和离线演示模型可直接使用。
- API 模型需要使用者填写自己的 Base URL 与 API Key；备份和安装包不会携带你的密钥。
- Codex、Claude Code、OpenCode、Reasonix、Gemini CLI、Aider、Kimi Code、Qoder CLI 需要在对方电脑上分别安装 CLI 并完成自己的登录或 Provider 配置。
- OpenCode 桌面版本身不等于 `opencode` CLI；环境页会识别这种情况并显示安装命令。
- Reasonix 若只存在于一次性 `npx` 缓存会显示“需优化”，正式评测前应全局安装。
- Qoder 桌面 IDE 不等于可无头返回结果的 `qodercli`；只安装桌面版时会明确显示“缺 CLI”，不会误启动 GUI。
- 包含代码命令验证的测试需要 Docker Desktop；纯文本和无需命令验证的测试不需要 Docker。

客户端不会分发账号令牌，也不会连接 AgentBench 服务器。换电脑后只需按“本地设置 → 运行环境”的提示补齐个人依赖即可。
