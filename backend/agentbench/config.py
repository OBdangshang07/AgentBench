from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    database_path: Path
    artifacts_dir: Path
    workspaces_dir: Path
    backups_dir: Path
    log_level: str
    allow_host_shell: bool
    allow_native_cli: bool
    max_workers: int

    @classmethod
    def from_env(cls) -> Settings:
        raw_dir = os.getenv("AGENTBENCH_DATA_DIR")
        data_dir = (
            Path(raw_dir).expanduser().resolve()
            if raw_dir
            else Path(user_data_path("AgentBench", "AgentBench")).resolve()
        )
        settings = cls(
            host=os.getenv("AGENTBENCH_HOST", "127.0.0.1"),
            port=int(os.getenv("AGENTBENCH_PORT", "43765")),
            data_dir=data_dir,
            database_path=data_dir / "agentbench.db",
            artifacts_dir=data_dir / "artifacts",
            workspaces_dir=data_dir / "workspaces",
            backups_dir=data_dir / "backups",
            log_level=os.getenv("AGENTBENCH_LOG_LEVEL", "INFO").upper(),
            allow_host_shell=_as_bool(os.getenv("AGENTBENCH_ALLOW_HOST_SHELL")),
            allow_native_cli=_as_bool(os.getenv("AGENTBENCH_ALLOW_NATIVE_CLI")),
            max_workers=max(1, min(int(os.getenv("AGENTBENCH_MAX_WORKERS", "2")), 8)),
        )
        settings.ensure_directories()
        return settings

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.artifacts_dir,
            self.workspaces_dir,
            self.backups_dir,
            self.data_dir / "frontend-portfolios",
            self.data_dir / "review-evidence",
        ):
            path.mkdir(parents=True, exist_ok=True)
