from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .execution import DockerExecutor, Workspace, WorkspaceViolation
from .model_clients import ModelClient, ModelClientError, ModelUsage

EventSink = Callable[[str, dict[str, Any]], None]
ToolAuthorizer = Callable[[str, dict[str, Any]], dict[str, Any] | None]
ToolExecutor = Callable[[str, dict[str, Any]], dict[str, Any] | None]


TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "read_file": {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the task workspace.",
        "parameters": {
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "list_files": {
        "name": "list_files",
        "description": "List files inside the task workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
            "additionalProperties": False,
        },
    },
    "search_text": {
        "name": "search_text",
        "description": "Search text inside workspace files.",
        "parameters": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string", "default": "."},
            },
            "additionalProperties": False,
        },
    },
    "write_file": {
        "name": "write_file",
        "description": "Create or replace a UTF-8 text file inside the task workspace.",
        "parameters": {
            "type": "object",
            "required": ["path", "content"],
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "run_command": {
        "name": "run_command",
        "description": "Run a shell command in the configured Docker sandbox.",
        "parameters": {
            "type": "object",
            "required": ["command"],
            "properties": {"command": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "browser_navigate": {
        "name": "browser_navigate",
        "description": "Open or navigate the visible AgentBench browser to an HTTP(S) URL.",
        "parameters": {
            "type": "object",
            "required": ["url"],
            "properties": {"url": {"type": "string"}, "page_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "browser_snapshot": {
        "name": "browser_snapshot",
        "description": "Read the current page text, links and interactive controls.",
        "parameters": {
            "type": "object",
            "properties": {"page_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "browser_click": {
        "name": "browser_click",
        "description": "Click an element in the visible browser using a CSS selector.",
        "parameters": {
            "type": "object",
            "required": ["selector"],
            "properties": {"selector": {"type": "string"}, "page_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "browser_fill": {
        "name": "browser_fill",
        "description": "Fill an input in the visible browser using a CSS selector.",
        "parameters": {
            "type": "object",
            "required": ["selector", "value"],
            "properties": {
                "selector": {"type": "string"},
                "value": {"type": "string"},
                "page_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "browser_screenshot": {
        "name": "browser_screenshot",
        "description": "Capture the visible browser viewport as a PNG artifact.",
        "parameters": {
            "type": "object",
            "properties": {"page_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
}


@dataclass(slots=True)
class AgentResult:
    ok: bool
    final_answer: str
    steps: int
    usage: ModelUsage
    duration_ms: int
    error_code: str | None = None
    error_message: str | None = None
    native_session_id: str | None = None


class AgentHarness:
    def __init__(
        self,
        *,
        client: ModelClient,
        workspace: Workspace,
        docker: DockerExecutor,
        allowed_capabilities: list[str],
        limits: dict[str, Any],
        system_prompt: str,
        event_sink: EventSink,
        cancellation_check: Callable[[], bool] | None = None,
        tool_authorizer: ToolAuthorizer | None = None,
        tool_executor: ToolExecutor | None = None,
    ):
        self.client = client
        self.workspace = workspace
        self.docker = docker
        self.allowed_capabilities = set(allowed_capabilities)
        self.limits = limits
        self.system_prompt = system_prompt
        self.event_sink = event_sink
        self.cancellation_check = cancellation_check or (lambda: False)
        self.tool_authorizer = tool_authorizer
        self.tool_executor = tool_executor

    def _tools(self) -> list[dict[str, Any]]:
        names: list[str] = []
        if {
            "filesystem",
            "filesystem_read",
        } & self.allowed_capabilities:
            names.extend(["read_file", "list_files"])
        if {"filesystem", "filesystem_write"} & self.allowed_capabilities:
            names.append("write_file")
        if "search" in self.allowed_capabilities:
            names.append("search_text")
        if "shell" in self.allowed_capabilities:
            names.append("run_command")
        if "browser" in self.allowed_capabilities:
            names.extend(
                [
                    "browser_navigate",
                    "browser_snapshot",
                    "browser_click",
                    "browser_fill",
                    "browser_screenshot",
                ]
            )
        return [TOOL_DEFINITIONS[name] for name in dict.fromkeys(names)]

    def run(self, instruction: str) -> AgentResult:
        started = time.perf_counter()
        max_steps = int(self.limits.get("max_steps", 40))
        token_budget = int(self.limits.get("token_budget", 100_000))
        max_runtime_seconds = int(self.limits.get("max_runtime_seconds", 7200))
        token_budget_notified = False
        history: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    self.system_prompt
                    + "\nNever expose private chain-of-thought. Use tools when needed and provide only "
                    "the final result or a concise task summary. All file paths are workspace-relative."
                ).strip(),
            },
            {"role": "user", "content": instruction},
        ]
        usage = ModelUsage()
        tools = self._tools()
        for step in range(1, max_steps + 1):
            if self.cancellation_check():
                return AgentResult(
                    False,
                    "",
                    step - 1,
                    usage,
                    int((time.perf_counter() - started) * 1000),
                    "user_cancelled",
                    "The user cancelled this Agent turn",
                )
            if max_runtime_seconds > 0 and time.perf_counter() - started > max_runtime_seconds:
                return AgentResult(
                    False,
                    "",
                    step - 1,
                    usage,
                    int((time.perf_counter() - started) * 1000),
                    "runtime_safety_limit",
                    "Agent reached the runtime safety watchdog; this is an infrastructure stop, not a scored failure",
                )
            self.event_sink("model.requested", {"step": step})
            try:
                decision = self.client.complete(history, tools)
            except ModelClientError as exc:
                return AgentResult(
                    False,
                    "",
                    step - 1,
                    usage,
                    int((time.perf_counter() - started) * 1000),
                    "model_error",
                    str(exc),
                )
            usage.add(decision.usage)
            if self.cancellation_check():
                return AgentResult(
                    False,
                    "",
                    step,
                    usage,
                    int((time.perf_counter() - started) * 1000),
                    "user_cancelled",
                    "The user cancelled this Agent turn",
                )
            self.event_sink(
                "model.responded",
                {
                    "step": step,
                    "kind": decision.kind,
                    "content": decision.content[:20_000],
                    "usage": {
                        "input_tokens": decision.usage.input_tokens,
                        "output_tokens": decision.usage.output_tokens,
                    },
                },
            )
            if (
                token_budget > 0
                and not token_budget_notified
                and usage.input_tokens + usage.output_tokens > token_budget
            ):
                token_budget_notified = True
                self.event_sink(
                    "agent.soft_budget_exceeded",
                    {
                        "budget": "tokens",
                        "target": token_budget,
                        "actual": usage.input_tokens + usage.output_tokens,
                    },
                )
            if decision.kind == "final":
                return AgentResult(
                    True,
                    decision.content,
                    step,
                    usage,
                    int((time.perf_counter() - started) * 1000),
                )
            if decision.kind != "tool" or not decision.tool_name:
                return AgentResult(
                    False,
                    "",
                    step,
                    usage,
                    int((time.perf_counter() - started) * 1000),
                    "invalid_model_decision",
                    "Model returned neither a final answer nor a tool request",
                )
            call_id = decision.tool_call_id or f"call-{step}"
            call = {
                "id": call_id,
                "name": decision.tool_name,
                "arguments": decision.tool_arguments,
            }
            history.append({"role": "assistant", "content": decision.content, "tool_call": call})
            self.event_sink("tool.requested", {"step": step, **call})
            result = self._execute_tool(decision.tool_name, decision.tool_arguments)
            self.event_sink(
                "tool.completed", {"step": step, "name": decision.tool_name, "result": result}
            )
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": decision.tool_name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        return AgentResult(
            False,
            "",
            max_steps,
            usage,
            int((time.perf_counter() - started) * 1000),
            "max_steps_exceeded",
            "Agent reached the maximum number of steps",
        )

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if self.tool_authorizer is not None:
                denied = self.tool_authorizer(name, arguments)
                if denied is not None:
                    return denied
            if self.tool_executor is not None:
                executed = self.tool_executor(name, arguments)
                if executed is not None:
                    return executed
            if name == "read_file" and {
                "filesystem",
                "filesystem_read",
            } & self.allowed_capabilities:
                return {"ok": True, "content": self.workspace.read_file(str(arguments["path"]))}
            if name == "list_files" and {
                "filesystem",
                "filesystem_read",
            } & self.allowed_capabilities:
                return {
                    "ok": True,
                    "files": self.workspace.list_files(str(arguments.get("path", "."))),
                }
            if name == "search_text" and "search" in self.allowed_capabilities:
                return {
                    "ok": True,
                    "matches": self.workspace.search_text(
                        str(arguments["query"]), str(arguments.get("path", "."))
                    ),
                }
            if name == "write_file" and {
                "filesystem",
                "filesystem_write",
            } & self.allowed_capabilities:
                return {
                    "ok": True,
                    **self.workspace.write_file(str(arguments["path"]), str(arguments["content"])),
                }
            if name == "run_command" and "shell" in self.allowed_capabilities:
                result = self.docker.run(
                    self.workspace,
                    str(arguments["command"]),
                    str(self.limits.get("docker_image", "python:3.12-alpine")),
                    timeout=min(int(self.limits.get("command_timeout_seconds", 120)), 600),
                    network=str(self.limits.get("network", "disabled")),
                )
                return result.as_dict()
            return {"ok": False, "error_code": "tool_not_allowed", "message": name}
        except (KeyError, OSError, WorkspaceViolation, ValueError) as exc:
            return {"ok": False, "error_code": "tool_error", "message": str(exc)}
