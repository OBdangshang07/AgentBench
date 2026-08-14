from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(slots=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reported_cost_usd: float | None = None

    def add(self, other: ModelUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        if other.reported_cost_usd is not None:
            self.reported_cost_usd = (self.reported_cost_usd or 0.0) + other.reported_cost_usd


@dataclass(slots=True)
class ModelDecision:
    kind: str
    content: str = ""
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    tool_call_id: str | None = None
    usage: ModelUsage = field(default_factory=ModelUsage)
    raw: dict[str, Any] = field(default_factory=dict)


class ModelClient(Protocol):
    def complete(
        self,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelDecision: ...


class ModelClientError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_name: str,
        temperature: float,
        max_tokens: int,
        reasoning_effort: str | None = None,
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.reasoning_status = "requested" if reasoning_effort else "not_requested"
        self.timeout = timeout

    def complete(self, history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelDecision:
        messages: list[dict[str, Any]] = []
        for item in history:
            role = item["role"]
            if role == "assistant" and item.get("tool_call"):
                call = item["tool_call"]
                messages.append(
                    {
                        "role": "assistant",
                        "content": item.get("content") or None,
                        "tool_calls": [
                            {
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                                },
                            }
                        ],
                    }
                )
            elif role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item["tool_call_id"],
                        "content": item.get("content", ""),
                    }
                )
            else:
                messages.append({"role": role, "content": item.get("content", "")})
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
            payload["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            if response.status_code == 400 and "reasoning_effort" in payload:
                self.reasoning_status = "rejected_fallback"
                fallback_payload = {key: value for key, value in payload.items() if key != "reasoning_effort"}
                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=fallback_payload,
                    timeout=self.timeout,
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelClientError(f"OpenAI-compatible request failed: {exc}") from exc
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelClientError("Model response did not contain choices[0].message") from exc
        usage_data = data.get("usage") or {}
        usage = ModelUsage(
            input_tokens=int(usage_data.get("prompt_tokens", 0)),
            output_tokens=int(usage_data.get("completion_tokens", 0)),
        )
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            call = tool_calls[0]
            try:
                arguments = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError as exc:
                raise ModelClientError("Model returned invalid JSON tool arguments") from exc
            return ModelDecision(
                kind="tool",
                content=message.get("content") or "",
                tool_name=call["function"]["name"],
                tool_arguments=arguments,
                tool_call_id=call.get("id") or "tool-call",
                usage=usage,
                raw=data,
            )
        return ModelDecision(
            kind="final",
            content=message.get("content") or "",
            usage=usage,
            raw=data,
        )


class AnthropicClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_name: str,
        max_tokens: int,
        reasoning_effort: str | None = None,
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.reasoning_status = "requested" if reasoning_effort else "not_requested"
        self.timeout = timeout

    def complete(self, history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelDecision:
        system_parts = [item.get("content", "") for item in history if item["role"] == "system"]
        messages: list[dict[str, Any]] = []
        for item in history:
            role = item["role"]
            if role == "system":
                continue
            if role == "assistant" and item.get("tool_call"):
                call = item["tool_call"]
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": call["id"],
                                "name": call["name"],
                                "input": call["arguments"],
                            }
                        ],
                    }
                )
            elif role == "tool":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": item["tool_call_id"],
                                "content": item.get("content", ""),
                            }
                        ],
                    }
                )
            else:
                messages.append({"role": role, "content": item.get("content", "")})
        payload: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "system": "\n".join(system_parts),
            "messages": messages,
        }
        if self.reasoning_effort:
            payload["output_config"] = {"effort": self.reasoning_effort}
        if tools:
            payload["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool["parameters"],
                }
                for tool in tools
            ]
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            response = httpx.post(
                f"{self.base_url}/v1/messages", headers=headers, json=payload, timeout=self.timeout
            )
            if response.status_code == 400 and "output_config" in payload:
                self.reasoning_status = "rejected_fallback"
                fallback_payload = {key: value for key, value in payload.items() if key != "output_config"}
                response = httpx.post(
                    f"{self.base_url}/v1/messages",
                    headers=headers,
                    json=fallback_payload,
                    timeout=self.timeout,
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelClientError(f"Anthropic request failed: {exc}") from exc
        usage_data = data.get("usage") or {}
        usage = ModelUsage(
            input_tokens=int(usage_data.get("input_tokens", 0)),
            output_tokens=int(usage_data.get("output_tokens", 0)),
        )
        content = data.get("content") or []
        tool_block = next((block for block in content if block.get("type") == "tool_use"), None)
        if tool_block:
            return ModelDecision(
                kind="tool",
                tool_name=tool_block["name"],
                tool_arguments=tool_block.get("input") or {},
                tool_call_id=tool_block["id"],
                usage=usage,
                raw=data,
            )
        text = "\n".join(block.get("text", "") for block in content if block.get("type") == "text")
        return ModelDecision(kind="final", content=text, usage=usage, raw=data)


class MockModelClient:
    def __init__(self, metadata: dict[str, Any]):
        self.actions = list(metadata.get("demo_actions") or [])
        self.final_response = str(metadata.get("demo_response") or "任务已完成。")
        self.reasoning_status = (
            "requested" if metadata.get("reasoning_effort") else "not_requested"
        )
        self.index = 0

    def complete(self, history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelDecision:
        del history, tools
        if self.index < len(self.actions):
            action = self.actions[self.index]
            self.index += 1
            return ModelDecision(
                kind="tool",
                tool_name=action["tool"],
                tool_arguments=action.get("arguments") or {},
                tool_call_id=f"mock-tool-{self.index}",
                usage=ModelUsage(input_tokens=80, output_tokens=25),
                raw={"mock": True},
            )
        return ModelDecision(
            kind="final",
            content=self.final_response,
            usage=ModelUsage(input_tokens=60, output_tokens=12),
            raw={"mock": True},
        )
