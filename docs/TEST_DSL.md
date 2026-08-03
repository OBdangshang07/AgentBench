# 测试 DSL

测试定义采用 JSON/YAML，导入时按 `schemas/test-case.schema.json` 验证并保存不可变版本。

关键字段：

- `slug`、`version`、`category`、`title`
- `instruction`：提供给 Agent 的任务
- `workspace`：可选的初始项目包
- `tools`：允许的工具
- `limits`：步数、软时间目标、安全看门狗、Token、费用和网络策略
- `attempt_policy`：可选的 1–3 轮提示阶梯、通过线与轮次折扣
- `validators`：验证器列表和权重
- `rubric`：可选匿名 AI 裁判量表
- `tags`：检索和分组标签

验证器支持：`exact_match`、`contains`、`regex`、`json_schema`、`json_file`、`file_exists`、`file_content`、`file_contains`、`forbidden_paths`、`command` 和 `ai_rubric`。

## V2 平衡评分

- 正确性、产物和 AI Rubric 等质量验证器按相对权重归一到总分的 94%。
- 完成时间占 3%。`time_target_seconds` 是软目标，超过后仍继续运行，并按对数曲线轻微扣分。
- `max_runtime_seconds` 仅是防止进程永久卡死的安全看门狗；设为 0 表示不限制，触发后不作为模型能力零分。
- Agent 步数占 2%，按 `max_steps` 归一化。
- Token 效率占 1%，按 `token_budget` 归一化；未可靠上报时使用中性分，避免把缺失统计误判成零消耗。
- `exact_match`、`contains`、`file_content`、`json_schema` 和 `json_file` 支持可解释的部分分。
- `json_file` 的 `config` 需要 `path` 与 `expected`，对象按字段评分并兼容 UTF-8 BOM。
- `forbidden_paths` 等安全约束仍为硬门槛，不因相似度获得部分分。

## Ultra 三轮挑战

- 第一轮、第二轮、第三轮默认分数系数分别为 1.00、0.85、0.70。
- 第二、三轮使用题目中预先版本化的标准提示，并保留上一轮工作区。
- 只有客观质量达到 `pass_threshold` 且所有 `critical` 验证器通过，才算完成该轮。
- CLI 缺失、Provider 错误或安全看门狗终止属于环境失败，不消耗 Ultra 能力机会。
