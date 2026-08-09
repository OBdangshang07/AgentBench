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
