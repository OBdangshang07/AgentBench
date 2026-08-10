from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(default="openai-compatible", max_length=60)
    model_name: str = Field(min_length=1, max_length=160)
    base_url: HttpUrl | None = None
    api_style: Literal["openai", "anthropic", "mock"] = "openai"
    api_key: str | None = Field(default=None, repr=False)
    agent_provider: str | None = Field(
        default=None, max_length=100, pattern=r"^[A-Za-z0-9._-]+$"
    )
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=64, le=200000)
    input_price: float = Field(default=0, ge=0)
    output_price: float = Field(default=0, ge=0)


class ModelDiscoveryRequest(BaseModel):
    source: Literal[
        "api",
        "codex-cli",
        "claude-code",
        "opencode-cli",
        "reasonix-cli",
        "gemini-cli",
        "aider-cli",
        "kimi-code",
        "qoder-cli",
    ] = "api"
    provider: str = Field(default="openai-compatible", min_length=1, max_length=100)
    base_url: HttpUrl | None = None
    api_style: Literal["openai", "anthropic"] = "openai"
    api_key: str | None = Field(default=None, repr=False)


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, repr=False)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=64, le=200000)
    input_price: float | None = Field(default=None, ge=0)
    output_price: float | None = Field(default=None, ge=0)
    enabled: bool | None = None


class RunnerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    runner_type: Literal[
        "unified",
        "codex_cli",
        "claude_code_cli",
        "opencode_cli",
        "reasonix_cli",
        "gemini_cli",
        "aider_cli",
        "kimi_code_cli",
        "qoder_cli",
        "command",
    ]
    executable: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    system_prompt: str = ""
    tools: list[str] = Field(default_factory=lambda: ["filesystem", "search"])
    limits: dict[str, Any] = Field(default_factory=dict)
    model_override_supported: bool = True


class Participant(BaseModel):
    model_id: str
    runner_id: str


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=140)
    suite_id: str
    participants: list[Participant] = Field(min_length=1, max_length=20)
    repetitions: int = Field(default=1, ge=1, le=10)
    concurrency: int = Field(default=1, ge=1, le=8)


class TestCaseImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    version: str = Field(min_length=1, max_length=40)
    category: str
    title: str
    instruction: str
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    attempt_policy: dict[str, Any] | None = None
    validators: list[dict[str, Any]]
    rubric: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    # initial_files values are UTF-8 text, except values prefixed with "base64:"
    # which are decoded as raw bytes (used for binary assets like .docx/.xlsx/.pptx).
    initial_files: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MathQuestionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_text: str | None = Field(default=None, max_length=40_000)
    answer: str | None = Field(default=None, max_length=8_000)
    accepted_answers: list[str] | None = Field(default=None, max_length=40)
    variables: list[str] | None = Field(default=None, max_length=20)
    solution_obligations: list[str] | None = Field(default=None, max_length=30)
    review_status: Literal["needs_review", "confirmed"] | None = None


class ManualScoreUpdate(BaseModel):
    score: float = Field(ge=0, le=100)
    reason: str = Field(min_length=3, max_length=1000)


class AppSettingUpdate(BaseModel):
    judge_model_id: str | None = None
    judge_runner_id: str | None = None
    judge_model_id_secondary: str | None = None
    judge_runner_id_secondary: str | None = None
    judge_model_id_tiebreaker: str | None = None
    judge_runner_id_tiebreaker: str | None = None
    judge_disagreement_threshold: float | None = Field(default=None, ge=0, le=100)
    allow_native_cli: bool | None = None
    default_concurrency: int | None = Field(default=None, ge=1, le=8)
    default_max_runtime_seconds: int | None = Field(default=None, ge=0, le=86400)


class ModelEnabledUpdate(BaseModel):
    enabled: bool


PermissionProfile = Literal["readonly", "workspace", "standard", "full"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    root_path: str = Field(min_length=1, max_length=2048)
    description: str = Field(default="", max_length=2000)
    default_runner_id: str | None = None
    default_model_id: str | None = None
    permission_profile: PermissionProfile = "workspace"
    pinned: bool = False


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    default_runner_id: str | None = None
    default_model_id: str | None = None
    permission_profile: PermissionProfile | None = None
    pinned: bool | None = None
    archived: bool | None = None


class ProjectRootCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_path: str = Field(min_length=1, max_length=2048)
    label: str = Field(default="", max_length=120)
    access_mode: PermissionProfile = "workspace"


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    runner_id: str | None = None
    model_id: str | None = None
    title: str = Field(default="新 Agent 会话", min_length=1, max_length=180)
    permission_profile: PermissionProfile | None = None
    reasoning_effort: ReasoningEffort = "medium"
    skill_pack_id: str | None = None


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=180)
    runner_id: str | None = None
    model_id: str | None = None
    permission_profile: PermissionProfile | None = None
    reasoning_effort: ReasoningEffort | None = None
    skill_pack_id: str | None = None
    archived: bool | None = None


class SessionTurnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=200_000)
    context: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class SessionAttachmentImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[str] = Field(min_length=1, max_length=10)


class TerminalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shell: Literal["powershell.exe", "pwsh.exe", "cmd.exe"] = "powershell.exe"
    columns: int = Field(default=120, ge=40, le=300)
    rows: int = Field(default=30, ge=10, le=100)


class TerminalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: str = Field(max_length=20_000)


class TerminalResize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: int = Field(ge=40, le=300)
    rows: int = Field(ge=10, le=100)


class BrowserLaunch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(default="about:blank", min_length=1, max_length=4096)


class BrowserNavigate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=4096)
    page_id: str | None = Field(default=None, max_length=240)


class BrowserAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["click", "fill", "submit"]
    selector: str = Field(min_length=1, max_length=2000)
    value: str | None = Field(default=None, max_length=100_000)
    page_id: str | None = Field(default=None, max_length=240)


class BrowserToolCall(BaseModel):
    """One capability-scoped call from the ephemeral native-Agent MCP bridge."""

    model_config = ConfigDict(extra="forbid")

    tool_name: Literal[
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_fill",
        "browser_screenshot",
    ]
    arguments: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["allow_once", "allow_session", "allow_project", "deny"]
    reason: str = Field(default="", max_length=1000)


class FileChangeReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "reject", "apply_content"]
    content: str | None = Field(default=None, max_length=2_000_000)


class TaskItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str | None = None
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    runner_id: str | None = None
    model_id: str | None = None


class TaskItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["backlog", "queued", "running", "approval", "completed", "failed"] | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    runner_id: str | None = None
    model_id: str | None = None


class McpServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    transport: Literal["stdio", "sse", "streamable_http"] = "stdio"
    command: str | None = Field(default=None, max_length=2048)
    args: list[str] = Field(default_factory=list, max_length=100)
    url: HttpUrl | None = None
    env: dict[str, str] = Field(default_factory=dict)


class McpServerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    transport: Literal["stdio", "sse", "streamable_http"] | None = None
    command: str | None = Field(default=None, max_length=2048)
    args: list[str] | None = Field(default=None, max_length=100)
    url: HttpUrl | None = None
    env: dict[str, str] | None = None
    remove_env_keys: list[str] = Field(default_factory=list, max_length=100)
    enabled: bool | None = None


class McpToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=240)
    arguments: dict[str, Any] = Field(default_factory=dict)


class SkillPackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    content: str = Field(min_length=1, max_length=20_000)
    tools: list[str] = Field(default_factory=list, max_length=50)
    permission_profile: PermissionProfile | None = None


class SkillPackUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    content: str | None = Field(default=None, min_length=1, max_length=20_000)
    tools: list[str] | None = Field(default=None, max_length=50)
    permission_profile: PermissionProfile | None = None


class TaskGraphCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str | None = None
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4000)
    settings: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    edges: list[dict[str, Any]] = Field(default_factory=list, max_length=300)


class TaskGraphUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    settings: dict[str, Any] | None = None
    nodes: list[dict[str, Any]] | None = Field(default=None, min_length=1, max_length=100)
    edges: list[dict[str, Any]] | None = Field(default=None, max_length=300)
