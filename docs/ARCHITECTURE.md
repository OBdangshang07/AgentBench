# 架构

## 进程边界

```text
Tauri 主进程
  ├─ React WebView：本地 UI
  └─ Python Sidecar：FastAPI + 调度器
       ├─ SQLite（WAL）
       ├─ 本地 Artifact Store
       ├─ Model Gateway
       ├─ Agent Runner Gateway
       │    ├─ Unified Agent Harness
       │    ├─ Codex CLI Runner
       │    ├─ Claude Code CLI Runner
       │    └─ Custom Command Runner
       ├─ Docker Executor
       └─ Scoring Pipeline
```

UI 只访问 `127.0.0.1`。Sidecar 默认生成本次安装的本地访问令牌，并拒绝非允许 Origin。模型密钥不进入前端状态或运行日志。

## Agent 协议

运行输入：

- 任务 ID 与不可变版本
- 指令和初始工作区快照
- Agent Profile（提示词、工具、步数）
- Model Profile（端点、模型名、采样参数）
- 运行限制（时间、Token、费用、网络、资源）

事件类型：

- `run.started`
- `model.requested`
- `model.responded`
- `tool.requested`
- `tool.completed`
- `artifact.created`
- `validator.completed`
- `judge.completed`
- `run.completed`
- `run.failed`

运行输出：公开模型消息、最终答案、工具记录、工作区产物、验证结果、评分分量和使用量。系统不要求或存储隐藏思维链。

## 调度状态机

```text
queued -> preparing -> running -> validating -> judging -> completed
   |          |           |           |            |
   +----------+-----------+-----------+------------+-> failed/cancelled/timed_out
```

调度器使用 SQLite 原子状态迁移和进程内线程池。V1 是单机单 Sidecar，因此不引入 Redis。意外退出后，启动恢复流程会将遗留的运行标记为 `interrupted`，用户可重试。

## 数据与文件

- SQLite：配置、测试、实验、运行、事件、评分元数据
- `artifacts/<run-id>/`：工作区快照、标准输出、报告和导出文件
- Windows Credential Manager：API 密钥
- `backups/`：带清单和校验值的备份 ZIP

## 公平性

模型配置与 Agent Runner 是两个独立实体。统一赛道固定 Runner、工具、环境镜像、上下文材料和限制，只替换模型配置；原生赛道比较 `Runner + 模型` 完整组合。若某个 CLI 不支持模型覆盖，该组合被标记为不可拆分系统，不会被解释成基础模型能力。两个赛道使用独立排行榜，并按测试集版本分区。

Codex 和 Claude Code 的兼容性由能力探测决定。只有 CLI 自身支持目标模型或兼容 API 网关时，才允许组成相应参与者。裁判同样可以是直接 API 模型或能够检查工作区的裁判 Agent。
