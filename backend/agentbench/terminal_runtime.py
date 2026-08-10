from __future__ import annotations

import os
import shutil
import threading
from collections import deque
from pathlib import Path
from typing import Any

from .db import utc_now


class InteractiveTerminal:
    """A Windows ConPTY-backed terminal with cursor-based, recording-safe output reads."""

    def __init__(
        self,
        terminal_id: str,
        workspace: Path,
        shell: str = "powershell.exe",
        columns: int = 120,
        rows: int = 30,
    ):
        try:
            from winpty import PtyProcess
        except ImportError as exc:  # pragma: no cover - non-Windows packaging fallback
            raise RuntimeError("ConPTY runtime is unavailable; reinstall AgentBench Desktop") from exc
        executable = shutil.which(shell)
        if not executable:
            raise ValueError("terminal_shell_not_found")
        if Path(executable).name.lower() not in {"powershell.exe", "pwsh.exe", "cmd.exe"}:
            raise ValueError("terminal_shell_not_allowed")
        argv = [executable]
        if Path(executable).name.lower() in {"powershell.exe", "pwsh.exe"}:
            argv.extend(["-NoLogo", "-NoProfile"])
        environment = os.environ.copy()
        environment["AGENTBENCH_TERMINAL"] = "1"
        self.id = terminal_id
        self.workspace = workspace.resolve()
        self.shell = Path(executable).name
        self.created_at = utc_now()
        self.process = PtyProcess.spawn(
            argv,
            cwd=str(self.workspace),
            env=environment,
            dimensions=(max(10, rows), max(40, columns)),
        )
        self._chunks: deque[dict[str, Any]] = deque(maxlen=2000)
        self._sequence = 0
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._reader = threading.Thread(
            target=self._read_loop,
            name=f"agentbench-terminal-{terminal_id[:8]}",
            daemon=True,
        )
        self._reader.start()

    def _read_loop(self) -> None:
        try:
            while not self._closed.is_set() and self.process.isalive():
                try:
                    value = self.process.read(4096)
                except (EOFError, OSError):
                    break
                if not value:
                    continue
                with self._lock:
                    self._sequence += 1
                    self._chunks.append(
                        {"seq": self._sequence, "data": value, "created_at": utc_now()}
                    )
        finally:
            self._closed.set()

    def write(self, value: str) -> None:
        if self._closed.is_set() or not self.process.isalive():
            raise ValueError("terminal_not_running")
        self.process.write(value)

    def resize(self, columns: int, rows: int) -> None:
        self.process.setwinsize(max(10, rows), max(40, columns))

    def read(self, after: int = 0) -> dict[str, Any]:
        with self._lock:
            chunks = [dict(item) for item in self._chunks if int(item["seq"]) > after]
            cursor = self._sequence
        return {
            "id": self.id,
            "shell": self.shell,
            "workspace": str(self.workspace),
            "running": not self._closed.is_set() and self.process.isalive(),
            "exit_code": None if self.process.isalive() else self.process.exitstatus,
            "cursor": cursor,
            "chunks": chunks,
            "created_at": self.created_at,
        }

    def close(self) -> None:
        self._closed.set()
        if self.process.isalive():
            self.process.close(force=True)
        self._reader.join(timeout=2)
