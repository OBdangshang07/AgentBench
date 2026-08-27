from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PrivateValidatorError(RuntimeError):
    """Raised when an external validator bundle is absent or fails integrity checks."""


@dataclass(frozen=True, slots=True)
class ResolvedPrivateValidator:
    command: str
    files: dict[str, str]
    provenance: dict[str, Any]


def _safe_identifier(value: Any, field: str) -> str:
    text = str(value or "")
    if not _IDENTIFIER_RE.fullmatch(text):
        raise PrivateValidatorError(f"invalid {field}")
    return text


def _safe_relative_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise PrivateValidatorError("private validator contains an unsafe file path")
    return path.as_posix()


class PrivateValidatorStore:
    """Resolve signed-by-digest validator references outside public test definitions.

    The manifest digest is pinned in the immutable test definition.  The bundle itself
    lives below the application's user-data directory and is copied into a random
    workspace directory only after the candidate Agent has finished.
    """

    def __init__(self, root: Path | None):
        self.root = root.resolve() if root is not None else None

    def resolve(self, reference: Any) -> ResolvedPrivateValidator:
        if self.root is None:
            raise PrivateValidatorError("private validator store is not configured")
        if not isinstance(reference, dict):
            raise PrivateValidatorError("private_validator_ref must be an object")

        bundle_id = _safe_identifier(reference.get("bundle_id"), "bundle_id")
        version = _safe_identifier(reference.get("version"), "version")
        validator_id = _safe_identifier(reference.get("validator_id"), "validator_id")
        expected_manifest_hash = str(reference.get("manifest_sha256") or "").lower()
        if not _SHA256_RE.fullmatch(expected_manifest_hash):
            raise PrivateValidatorError("invalid manifest_sha256")

        bundle_root = (self.root / bundle_id / version).resolve()
        if not bundle_root.is_relative_to(self.root):
            raise PrivateValidatorError("private validator bundle escapes its store")
        manifest_path = bundle_root / "manifest.json"
        try:
            manifest_bytes = manifest_path.read_bytes()
        except OSError as exc:
            raise PrivateValidatorError(
                f"private validator bundle is unavailable: {bundle_id}@{version}"
            ) from exc
        actual_manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if actual_manifest_hash != expected_manifest_hash:
            raise PrivateValidatorError("private validator manifest integrity check failed")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PrivateValidatorError("private validator manifest is invalid") from exc
        if not isinstance(manifest, dict) or int(manifest.get("schema_version") or 0) != 1:
            raise PrivateValidatorError("unsupported private validator manifest schema")
        if manifest.get("bundle_id") != bundle_id or str(manifest.get("version")) != version:
            raise PrivateValidatorError("private validator reference does not match its manifest")
        validators = manifest.get("validators")
        entry = validators.get(validator_id) if isinstance(validators, dict) else None
        if not isinstance(entry, dict):
            raise PrivateValidatorError("private validator entry is missing")
        command = str(entry.get("command") or "")
        if "{private_root}" not in command:
            raise PrivateValidatorError("private validator command must use {private_root}")
        declared_files = entry.get("files")
        if not isinstance(declared_files, dict) or not declared_files:
            raise PrivateValidatorError("private validator entry contains no files")

        files: dict[str, str] = {}
        file_hashes: dict[str, str] = {}
        for raw_path, raw_digest in declared_files.items():
            relative = _safe_relative_path(raw_path)
            expected_digest = str(raw_digest or "").lower()
            if not _SHA256_RE.fullmatch(expected_digest):
                raise PrivateValidatorError("private validator file digest is invalid")
            source = (bundle_root / Path(relative)).resolve()
            if not source.is_relative_to(bundle_root):
                raise PrivateValidatorError("private validator file escapes its bundle")
            try:
                content_bytes = source.read_bytes()
                content = content_bytes.decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise PrivateValidatorError(
                    f"private validator file is unavailable: {relative}"
                ) from exc
            actual_digest = hashlib.sha256(content_bytes).hexdigest()
            if actual_digest != expected_digest:
                raise PrivateValidatorError(
                    f"private validator file integrity check failed: {relative}"
                )
            files[relative] = content
            file_hashes[relative] = actual_digest

        return ResolvedPrivateValidator(
            command=command,
            files=files,
            provenance={
                "bundle_id": bundle_id,
                "version": version,
                "validator_id": validator_id,
                "manifest_sha256": actual_manifest_hash,
                "file_sha256": file_hashes,
            },
        )


def install_private_validator_bundle(archive: Path, store_root: Path) -> dict[str, str]:
    """Validate and atomically install one local ``.abpv`` bundle into user data."""

    archive = archive.resolve()
    store_root = store_root.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = {item.filename.replace("\\", "/"): item for item in bundle.infolist()}
            manifest_info = infos.get("manifest.json")
            if manifest_info is None or manifest_info.file_size > 1_000_000:
                raise PrivateValidatorError("private validator archive has no valid manifest")
            manifest_bytes = bundle.read(manifest_info)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, dict) or int(manifest.get("schema_version") or 0) != 1:
                raise PrivateValidatorError("unsupported private validator manifest schema")
            bundle_id = _safe_identifier(manifest.get("bundle_id"), "bundle_id")
            version = _safe_identifier(manifest.get("version"), "version")
            validators = manifest.get("validators")
            if not isinstance(validators, dict) or not validators:
                raise PrivateValidatorError("private validator bundle contains no validators")
            expected_files: dict[str, str] = {}
            for raw_entry in validators.values():
                if not isinstance(raw_entry, dict) or not isinstance(raw_entry.get("files"), dict):
                    raise PrivateValidatorError("private validator manifest entry is invalid")
                for raw_path, raw_digest in raw_entry["files"].items():
                    relative = _safe_relative_path(raw_path)
                    digest = str(raw_digest or "").lower()
                    if not _SHA256_RE.fullmatch(digest):
                        raise PrivateValidatorError("private validator file digest is invalid")
                    if relative in expected_files and expected_files[relative] != digest:
                        raise PrivateValidatorError("private validator file has conflicting digests")
                    expected_files[relative] = digest
            total_size = 0
            contents: dict[str, bytes] = {}
            for relative, digest in expected_files.items():
                info = infos.get(relative)
                if info is None or info.is_dir():
                    raise PrivateValidatorError(f"private validator archive misses {relative}")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise PrivateValidatorError("private validator archive cannot contain symlinks")
                total_size += info.file_size
                if total_size > 32 * 1024 * 1024:
                    raise PrivateValidatorError("private validator archive is too large")
                content = bundle.read(info)
                if hashlib.sha256(content).hexdigest() != digest:
                    raise PrivateValidatorError(
                        f"private validator archive integrity check failed: {relative}"
                    )
                content.decode("utf-8")
                contents[relative] = content
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise PrivateValidatorError("private validator archive is invalid") from exc

    target_root = (store_root / bundle_id / version).resolve()
    if not target_root.is_relative_to(store_root):
        raise PrivateValidatorError("private validator install target escapes its store")
    target_root.mkdir(parents=True, exist_ok=True)
    for relative, content in contents.items():
        destination = (target_root / Path(relative)).resolve()
        if not destination.is_relative_to(target_root):
            raise PrivateValidatorError("private validator install path escapes its bundle")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
    manifest_path = target_root / "manifest.json"
    temporary_manifest = manifest_path.with_name(f".manifest.{uuid.uuid4().hex}.tmp")
    temporary_manifest.write_bytes(manifest_bytes)
    temporary_manifest.replace(manifest_path)
    return {
        "bundle_id": bundle_id,
        "version": version,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
