from __future__ import annotations

from pathlib import Path

import pytest

from agentbench.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    value = Settings(
        host="127.0.0.1",
        port=43765,
        data_dir=tmp_path,
        database_path=tmp_path / "agentbench.db",
        artifacts_dir=tmp_path / "artifacts",
        workspaces_dir=tmp_path / "workspaces",
        backups_dir=tmp_path / "backups",
        log_level="WARNING",
        allow_host_shell=False,
        allow_native_cli=False,
        max_workers=2,
    )
    value.ensure_directories()
    return value
