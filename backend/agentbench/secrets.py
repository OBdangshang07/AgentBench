from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import Path

import keyring
from keyring.errors import KeyringError

logger = logging.getLogger(__name__)


class SecretStore:
    """Store provider secrets in the operating-system credential vault only."""

    service_name = "AgentBench Desktop"

    def __init__(self, fallback_dir: Path):
        # Keep this argument for a stable constructor; secrets are never written there.
        self.data_dir = fallback_dir

    def set(self, reference: str, secret: str) -> None:
        try:
            keyring.set_password(self.service_name, reference, secret)
            return
        except KeyringError as exc:
            logger.error("Credential Manager rejected a secret: %s", exc)
            raise RuntimeError(
                "Windows Credential Manager is unavailable; the API key was not saved"
            ) from exc

    def get(self, reference: str | None) -> str | None:
        if not reference:
            return None
        try:
            value = keyring.get_password(self.service_name, reference)
            if value:
                return value
        except KeyringError:
            return None
        return None

    def delete(self, reference: str | None) -> None:
        if not reference:
            return
        with suppress(KeyringError):
            keyring.delete_password(self.service_name, reference)
