from __future__ import annotations

from agentbench.config import Settings


def test_v530_defaults_to_four_global_workers_for_dual_model_dual_concurrency(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("AGENTBENCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("AGENTBENCH_MAX_WORKERS", raising=False)

    settings = Settings.from_env()

    assert settings.max_workers == 4


def test_global_worker_override_remains_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTBENCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AGENTBENCH_MAX_WORKERS", "99")

    settings = Settings.from_env()

    assert settings.max_workers == 8
