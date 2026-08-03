# 安全模型

## 信任边界

模型响应和测试项目均视为不可信输入。文件工具只能访问为本次运行创建的工作区；路径必须在规范化后仍位于工作区根目录。

## Shell 策略

- 默认禁止宿主机 Shell。
- 代码执行仅通过 Docker 容器。
- Docker 不挂载用户目录和凭据目录。
- 容器默认 `--network none`、`--read-only`、`--cap-drop ALL`、`--security-opt no-new-privileges`。
- 设置 CPU、内存、PID、临时空间和时间限制。
- 仅工作区挂载为可写。
- Docker 不可用时返回结构化 `sandbox_unavailable`，不回退宿主机执行。

开发者可以通过显式环境变量开启宿主机执行，但 UI 必须持续显示高风险状态，且该配置不用于发布构建。

## 密钥

- 优先存入 Windows Credential Manager。
- SQLite 只保存 credential reference。
- API 请求在 Sidecar 内构造。
- 日志过滤 Authorization、API key 和常见 Token 格式。
- API 密钥不注入 Agent 工作区或 Docker 容器。

## AI 裁判

- 裁判输入删除参测模型名称。
- 默认禁止参测模型为自己的运行评分。
- 裁判输出必须满足 JSON Schema，并给出证据。
- 裁判错误不会被伪装成零分；运行进入 `needs_review`。
