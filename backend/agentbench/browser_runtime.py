from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from websockets.sync.client import connect


class BrowserRuntimeError(ValueError):
    pass


def _browser_executable() -> Path | None:
    candidates = [
        shutil.which("msedge"),
        shutil.which("chrome"),
        str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe"),
        str(Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe"),
        str(Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe"),
    ]
    for raw in candidates:
        if raw and Path(raw).is_file():
            return Path(raw).resolve()
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class BrowserRuntime:
    """Visible, isolated Edge/Chrome runtime controlled through the local CDP endpoint."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.profile_dir = (data_dir / "browser-profile").resolve()
        self.artifact_dir = (data_dir / "browser-artifacts").resolve()
        self._process: subprocess.Popen[bytes] | None = None
        self._port: int | None = None
        self._artifacts: dict[str, Path] = {}
        self._lock = threading.RLock()

    @property
    def executable(self) -> Path | None:
        return _browser_executable()

    def _base_url(self) -> str:
        if self._port is None:
            raise BrowserRuntimeError("browser_not_running")
        return f"http://127.0.0.1:{self._port}"

    def _version(self) -> dict[str, Any]:
        try:
            response = httpx.get(f"{self._base_url()}/json/version", timeout=2)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BrowserRuntimeError("browser_cdp_unavailable") from exc

    def is_running(self) -> bool:
        with self._lock:
            if self._process is None or self._process.poll() is not None or self._port is None:
                return False
            try:
                self._version()
                return True
            except BrowserRuntimeError:
                return False

    def status(self) -> dict[str, Any]:
        executable = self.executable
        running = self.is_running()
        pages = self.pages() if running else []
        return {
            "installed": executable is not None,
            "running": running,
            "executable": str(executable) if executable else None,
            "engine": "Microsoft Edge / Chromium CDP" if executable else None,
            "profile_path": str(self.profile_dir),
            "page_count": len(pages),
            "pages": pages,
            "manual_takeover": running,
        }

    def launch(self, url: str = "about:blank") -> dict[str, Any]:
        self._validate_url(url)
        with self._lock:
            if self.is_running():
                if url != "about:blank":
                    self.new_page(url)
                return self.status()
            executable = self.executable
            if executable is None:
                raise BrowserRuntimeError("supported_browser_not_installed")
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            port = _free_port()
            args = [
                str(executable),
                f"--remote-debugging-port={port}",
                "--remote-debugging-address=127.0.0.1",
                "--remote-allow-origins=*",
                f"--user-data-dir={self.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--disable-features=msEdgeSidebarV2",
                "--window-size=1440,900",
                url,
            ]
            self._process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._port = port
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self._process and self._process.poll() is not None:
                break
            try:
                self._version()
                return self.status()
            except BrowserRuntimeError:
                time.sleep(0.2)
        self.close()
        raise BrowserRuntimeError("browser_startup_failed")

    @staticmethod
    def _validate_url(url: str) -> None:
        if url == "about:blank":
            return
        if not url.lower().startswith(("http://", "https://")):
            raise BrowserRuntimeError("browser_url_scheme_not_allowed")

    def pages(self) -> list[dict[str, Any]]:
        try:
            response = httpx.get(f"{self._base_url()}/json/list", timeout=3)
            response.raise_for_status()
            values = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BrowserRuntimeError("browser_pages_unavailable") from exc
        return [
            {
                "id": str(item.get("id")),
                "title": str(item.get("title") or "Untitled"),
                "url": str(item.get("url") or "about:blank"),
                "type": str(item.get("type") or "page"),
            }
            for item in values
            if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
        ]

    def new_page(self, url: str) -> dict[str, Any]:
        self._validate_url(url)
        try:
            response = httpx.put(f"{self._base_url()}/json/new?{quote(url, safe=':/?&=#%')}", timeout=5)
            response.raise_for_status()
            page = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BrowserRuntimeError("browser_page_create_failed") from exc
        return {"id": str(page["id"]), "title": str(page.get("title") or "Untitled"), "url": str(page.get("url") or url)}

    def _page_target(self, page_id: str | None = None) -> dict[str, Any]:
        try:
            response = httpx.get(f"{self._base_url()}/json/list", timeout=3)
            response.raise_for_status()
            values = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BrowserRuntimeError("browser_pages_unavailable") from exc
        pages = [item for item in values if item.get("type") == "page" and item.get("webSocketDebuggerUrl")]
        target = next((item for item in pages if str(item.get("id")) == page_id), None) if page_id else (pages[0] if pages else None)
        if not target:
            raise BrowserRuntimeError("browser_page_not_found")
        return target

    def _command(self, method: str, params: dict[str, Any] | None = None, page_id: str | None = None, timeout: float = 8) -> dict[str, Any]:
        target = self._page_target(page_id)
        message_id = int(time.time_ns() % 2_000_000_000)
        try:
            with connect(str(target["webSocketDebuggerUrl"]), open_timeout=3, close_timeout=1, max_size=24 * 1024 * 1024) as websocket:
                websocket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    message = json.loads(websocket.recv(timeout=max(0.1, deadline - time.monotonic())))
                    if message.get("id") != message_id:
                        continue
                    if message.get("error"):
                        raise BrowserRuntimeError(str(message["error"].get("message") or "browser_cdp_error"))
                    return message.get("result") or {}
        except BrowserRuntimeError:
            raise
        except Exception as exc:
            raise BrowserRuntimeError(f"browser_command_failed:{method}") from exc
        raise BrowserRuntimeError(f"browser_command_timeout:{method}")

    def evaluate(self, expression: str, page_id: str | None = None) -> Any:
        result = self._command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True, "userGesture": True},
            page_id,
        )
        remote = result.get("result") or {}
        if remote.get("subtype") == "error":
            raise BrowserRuntimeError(str(remote.get("description") or "browser_script_failed"))
        return remote.get("value")

    def navigate(self, url: str, page_id: str | None = None) -> dict[str, Any]:
        self._validate_url(url)
        self._command("Page.navigate", {"url": url}, page_id)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if self.evaluate("document.readyState", page_id) in {"interactive", "complete"}:
                    break
            except BrowserRuntimeError:
                pass
            time.sleep(0.2)
        return self.snapshot(page_id)

    def snapshot(self, page_id: str | None = None) -> dict[str, Any]:
        value = self.evaluate(
            """(() => {
              const selectorFor = (element) => {
                if (element.id) return `#${CSS.escape(element.id)}`;
                const parts = [];
                let current = element;
                while (current && current.nodeType === 1 && current !== document.documentElement) {
                  const tag = current.tagName.toLowerCase();
                  const siblings = current.parentElement ? Array.from(current.parentElement.children).filter((item) => item.tagName === current.tagName) : [];
                  const suffix = siblings.length > 1 ? `:nth-of-type(${siblings.indexOf(current) + 1})` : '';
                  parts.unshift(`${tag}${suffix}`);
                  current = current.parentElement;
                }
                return parts.join(' > ');
              };
              return {
                title: document.title,
                url: location.href,
                text: (document.body?.innerText || '').slice(0, 60000),
                links: Array.from(document.querySelectorAll('a[href]')).slice(0, 200).map((a, index) => ({index, text: (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 300), href: a.href, selector: selectorFor(a)})),
                controls: Array.from(document.querySelectorAll('button,input,textarea,select,[role=button]')).slice(0, 300).map((el, index) => ({index, tag: el.tagName.toLowerCase(), type: el.getAttribute('type'), text: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('name') || el.tagName).trim().slice(0, 300), id: el.id || null, name: el.getAttribute('name'), value: 'value' in el ? String(el.value).slice(0, 1000) : null, disabled: Boolean(el.disabled), selector: selectorFor(el)}))
              };
            })()""",
            page_id,
        )
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _selector_script(selector: str) -> str:
        return json.dumps(selector)

    def interact(self, action: str, selector: str, value: str | None = None, page_id: str | None = None) -> dict[str, Any]:
        encoded = self._selector_script(selector)
        if action == "click":
            script = f"""(() => {{ const el=document.querySelector({encoded}); if(!el) throw new Error('selector_not_found'); el.scrollIntoView({{block:'center'}}); el.click(); return true; }})()"""
        elif action == "fill":
            encoded_value = json.dumps(value or "")
            script = f"""(() => {{ const el=document.querySelector({encoded}); if(!el) throw new Error('selector_not_found'); el.focus(); el.value={encoded_value}; el.dispatchEvent(new Event('input',{{bubbles:true}})); el.dispatchEvent(new Event('change',{{bubbles:true}})); return true; }})()"""
        elif action == "submit":
            script = f"""(() => {{ const el=document.querySelector({encoded}); if(!el) throw new Error('selector_not_found'); (el.form || el).requestSubmit?.(); return true; }})()"""
        else:
            raise BrowserRuntimeError("browser_action_not_supported")
        self.evaluate(script, page_id)
        time.sleep(0.25)
        return self.snapshot(page_id)

    def screenshot(self, page_id: str | None = None) -> dict[str, Any]:
        result = self._command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, page_id, timeout=15)
        data = base64.b64decode(str(result.get("data") or ""), validate=True)
        if not data:
            raise BrowserRuntimeError("browser_screenshot_empty")
        artifact_id = uuid.uuid4().hex
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        target = (self.artifact_dir / f"{artifact_id}.png").resolve()
        if not target.is_relative_to(self.artifact_dir):
            raise BrowserRuntimeError("browser_artifact_path_invalid")
        target.write_bytes(data)
        self._artifacts[artifact_id] = target
        return {"id": artifact_id, "size": len(data), "media_type": "image/png"}

    def artifact(self, artifact_id: str) -> Path:
        target = self._artifacts.get(artifact_id)
        if not target or not target.is_file():
            candidate = (self.artifact_dir / f"{artifact_id}.png").resolve()
            if not candidate.is_relative_to(self.artifact_dir) or not candidate.is_file():
                raise BrowserRuntimeError("browser_artifact_not_found")
            target = candidate
        return target

    def close(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            self._process = None
            self._port = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        return self.status()
