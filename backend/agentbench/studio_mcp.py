from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class StudioMcpBridge:
    """Ephemeral MCP facade for the tools authorized by one Studio turn."""

    def __init__(self, api_base: str, bridge_token: str):
        self.api_base = api_base.rstrip("/")
        self.bridge_token = bridge_token

    def _request(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        binary: bool = False,
    ) -> Any:
        url = urllib.parse.urljoin(f"{self.api_base}/", path.lstrip("/"))
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=7200) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"AgentBench Studio tool request failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"AgentBench Studio tool bridge is unavailable: {exc.reason}") from exc
        if binary:
            return raw
        return json.loads(raw.decode("utf-8"))

    def tools(self) -> list[dict[str, Any]]:
        result = self._request(f"/api/v1/studio/bridge/{self.bridge_token}/tools")
        return [item for item in result.get("tools", []) if isinstance(item, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._request(
            f"/api/v1/studio/bridge/{self.bridge_token}",
            payload={"tool_name": name, "arguments": arguments},
        )
        is_error = not bool(result.get("ok", True))
        public_result = {key: value for key, value in result.items() if key != "path"}
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(public_result, ensure_ascii=False, indent=2),
            }
        ]
        artifact_url = result.get("url")
        if name == "browser_screenshot" and isinstance(artifact_url, str):
            png = self._request(artifact_url, binary=True)
            content.insert(
                0,
                {
                    "type": "image",
                    "data": base64.b64encode(png).decode("ascii"),
                    "mimeType": "image/png",
                },
            )
        return {"content": content, "isError": is_error}

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = str(request.get("method") or "")
        if method.startswith("notifications/"):
            return None
        if method == "initialize":
            requested = str((request.get("params") or {}).get("protocolVersion") or "")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": requested or "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "agentbench-studio-tools", "version": "1.0.0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.tools()}}
        if method == "tools/call":
            params = request.get("params") or {}
            name = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            try:
                result = self.call_tool(name, arguments)
                return {"jsonrpc": "2.0", "id": request_id, "result": result}
            except Exception as exc:  # MCP transports report tool failures as results.
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    },
                }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def run_studio_mcp(api_base: str, bridge_token: str) -> None:
    bridge = StudioMcpBridge(api_base, bridge_token)
    for raw_line in sys.stdin:
        if not raw_line.strip():
            continue
        try:
            request = json.loads(raw_line)
            if not isinstance(request, dict):
                raise ValueError("JSON-RPC request must be an object")
            response = bridge.handle(request)
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": str(exc)},
            }
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()


def parse_studio_mcp_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--bridge-token", required=True)
    return parser.parse_args(argv)
