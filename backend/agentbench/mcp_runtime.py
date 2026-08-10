from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from contextlib import suppress
from typing import Any

import httpx


class McpRuntimeError(RuntimeError):
    pass


def _event_data(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                with suppress(json.JSONDecodeError):
                    value = json.loads(line[5:].strip())
                    if isinstance(value, dict):
                        return value
        raise McpRuntimeError("MCP Server 返回了无有效 data 事件的 SSE 响应")
    try:
        value = response.json()
    except json.JSONDecodeError as exc:
        raise McpRuntimeError("MCP Server 返回了非 JSON 响应") from exc
    if not isinstance(value, dict):
        raise McpRuntimeError("MCP Server 返回格式无效")
    return value


class _StdioMcp:
    def __init__(self, command: str, args: list[str], env: dict[str, str]):
        resolved = shutil.which(command) or command
        environment = os.environ.copy()
        environment.update(env)
        self.process = subprocess.Popen(
            [resolved, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            creationflags=(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
            ),
            start_new_session=os.name != "nt",
        )
        self.lines: queue.Queue[str] = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.next_id = 1

    def _read_stdout(self) -> None:
        if self.process.stdout is None:
            return
        for line in iter(self.process.stdout.readline, ""):
            self.lines.put(line)

    def _read_stderr(self) -> None:
        if self.process.stderr is None:
            return
        for line in iter(self.process.stderr.readline, ""):
            self.stderr.append(line)
            if len(self.stderr) > 200:
                self.stderr.pop(0)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 10
    ) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None and self.lines.empty():
                detail = "".join(self.stderr)[-2000:].strip()
                raise McpRuntimeError(
                    f"MCP stdio 进程已退出（{self.process.returncode}）"
                    + (f"：{detail}" if detail else "")
                )
            try:
                line = self.lines.get(timeout=min(0.2, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            with suppress(json.JSONDecodeError):
                value = json.loads(line)
                if isinstance(value, dict) and value.get("id") == request_id:
                    if value.get("error"):
                        raise McpRuntimeError(str(value["error"]))
                    result = value.get("result")
                    return result if isinstance(result, dict) else {"value": result}
        raise McpRuntimeError(f"MCP 请求 {method} 超时")

    def _write(self, value: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise McpRuntimeError("MCP stdio 标准输入不可用")
        try:
            self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpRuntimeError("无法向 MCP stdio 进程发送请求") from exc

    def initialize(self, timeout: float = 10) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "AgentBench Desktop", "version": "4.0"},
            },
            timeout,
        )
        self.notify("notifications/initialized")
        return result

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            with suppress(subprocess.TimeoutExpired):
                self.process.wait(timeout=2)
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()


def _http_rpc(
    url: str,
    method: str,
    params: dict[str, Any],
    *,
    request_id: int,
    timeout: float,
    session_id: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    response = httpx.post(
        url,
        headers=headers,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        timeout=timeout,
    )
    response.raise_for_status()
    value = _event_data(response)
    if value.get("error"):
        raise McpRuntimeError(str(value["error"]))
    result = value.get("result")
    return (
        result if isinstance(result, dict) else {"value": result},
        response.headers.get("mcp-session-id") or session_id,
    )


def probe_mcp(config: dict[str, Any], env: dict[str, str], timeout: float = 8) -> dict[str, Any]:
    transport = str(config["transport"])
    if transport == "stdio":
        client = _StdioMcp(str(config["command"]), list(config.get("args") or []), env)
        try:
            initialized = client.initialize(timeout)
            tools = client.request("tools/list", {}, timeout).get("tools") or []
        finally:
            client.close()
        return {"status": "online", "server": initialized.get("serverInfo") or {}, "tools": tools}
    url = str(config.get("url") or "")
    if transport == "sse":
        response = httpx.get(url, headers={"Accept": "text/event-stream"}, timeout=timeout)
        response.raise_for_status()
        return {"status": "online", "server": {}, "tools": [], "transport_note": "SSE endpoint reachable"}
    initialized, session_id = _http_rpc(
        url,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "AgentBench Desktop", "version": "4.0"},
        },
        request_id=1,
        timeout=timeout,
    )
    listed, _ = _http_rpc(
        url, "tools/list", {}, request_id=2, timeout=timeout, session_id=session_id
    )
    return {
        "status": "online",
        "server": initialized.get("serverInfo") or {},
        "tools": listed.get("tools") or [],
    }


def call_mcp_tool(
    config: dict[str, Any],
    env: dict[str, str],
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float = 60,
) -> dict[str, Any]:
    if config["transport"] == "stdio":
        client = _StdioMcp(str(config["command"]), list(config.get("args") or []), env)
        try:
            client.initialize(min(timeout, 10))
            return client.request(
                "tools/call", {"name": tool_name, "arguments": arguments}, timeout
            )
        finally:
            client.close()
    if config["transport"] == "sse":
        raise McpRuntimeError("旧式 SSE Server 暂不支持直接工具调用，请改用 Streamable HTTP")
    initialized, session_id = _http_rpc(
        str(config["url"]),
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "AgentBench Desktop", "version": "4.0"},
        },
        request_id=1,
        timeout=min(timeout, 10),
    )
    del initialized
    result, _ = _http_rpc(
        str(config["url"]),
        "tools/call",
        {"name": tool_name, "arguments": arguments},
        request_id=2,
        timeout=timeout,
        session_id=session_id,
    )
    return result
