# 原生 Agent Runner

## 配置分层

AgentBench 将参测者表示为 `Agent Runner + 模型配置`。Runner 负责循环、工具和工作区操作，模型配置负责底层模型身份、API 端点和计价。统一 Agent 赛道只替换模型；原生赛道将整个组合作为被测系统。

## Codex CLI

内置 Runner 使用非交互 `codex exec`、JSON 事件输出、临时会话和 `workspace-write` 沙箱。实验选择的模型名会替换 `{model_name}`。因此可以用 Codex 测试 Codex 本身允许选择的 GPT 模型，或 Codex 配置中已经接入的兼容端点。

平台不会绕过 Codex 的模型兼容性。如果模型无法被 Codex CLI 选择，该运行会明确失败并保存 CLI 证据。

## Claude Code CLI

内置 Runner 使用 `claude --print --verbose --output-format stream-json`，模型名通过 `--model` 传入。要用 Claude Code 测试 Fable5，Fable5 必须满足以下之一：

- Claude Code 已原生支持该模型；
- Fable5 提供 Claude Code 接受的 Anthropic-compatible 接口；
- 本机 Claude Code 已配置能够完成模型映射的网关。

AgentBench 负责组合与记录，但不会伪造 Claude Code 不支持的协议。

## OpenCode CLI

内置 Runner 使用 `opencode run --format json --model {model_name}`。AgentBench 逐行解析 JSON 事件，同时保留完整 stdout、stderr 和工作区文件。模型名必须是本机 OpenCode Provider 配置能够识别的标识。

## Reasonix CLI

内置 Runner 使用非交互 `reasonix run --output-format json` 模板。不同 Reasonix 发行版的参数若有差异，可以复制为自定义 Runner 并在界面中调整参数数组；工作区、模型名和匿名任务仍通过标准占位符注入。

## Gemini CLI 与 Aider

- Gemini CLI 使用 `stream-json` 输出，适合长上下文和项目型任务；
- Aider 使用无确认、无自动提交的消息模式，适合代码库编辑与隐藏测试。

所有原生 Runner 都在独立赛道计分。平台会实际执行 `--version`，路径存在但无法启动时不会显示为“可用”。

## 自定义命令 Runner

可配置任意本地可执行文件与参数数组，支持：

- `{prompt}`：匿名化后的完整任务或裁判提示；
- `{model_name}`：实验选择的模型标识；
- `{workspace}`：本次运行工作区绝对路径。

命令不经过 Shell 字符串拼接。Sidecar 只继承运行所需的系统环境变量，并以工作区作为当前目录。

## 原生裁判 Agent

本地设置中可以将任一可用原生 Runner 或统一 Agent 设为裁判 Agent。裁判在工作区只读副本上运行，得到任务、Rubric、最终回答和文件样本，但得不到参测模型名称。裁判必须返回包含 `score` 与证据的 JSON；失败或格式不合法会进入人工复核，不会被伪装成零分。

## 安全提示

原生 CLI 使用自身权限系统，不等同于 Docker 容器。首次启用必须在本地设置中显式确认。模型 API 密钥不会从 AgentBench 模型配置注入 CLI 子进程；原生 CLI 使用它自己的登录或安全凭据配置。
