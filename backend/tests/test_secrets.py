from __future__ import annotations

import pytest
from keyring.errors import KeyringError

from agentbench.secrets import SecretStore


def test_secret_store_fails_closed_without_plaintext_fallback(tmp_path, monkeypatch):
    def reject(*_args, **_kwargs):
        raise KeyringError("vault unavailable")

    monkeypatch.setattr("agentbench.secrets.keyring.set_password", reject)
    store = SecretStore(tmp_path)
    with pytest.raises(RuntimeError, match="was not saved"):
        store.set("model-test", "top-secret")
    assert list(tmp_path.rglob("*secret*")) == []
