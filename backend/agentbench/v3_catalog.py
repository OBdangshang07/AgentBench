from __future__ import annotations

import hashlib
import json
import textwrap
from typing import Any


def _validator(kind: str, weight: float, **config: Any) -> dict[str, Any]:
    return {"type": kind, "weight": weight, "config": config}


def _cross_document_case(index: int) -> dict[str, Any]:
    entity_id = f"ACCT-{index:02d}-{70 + index:03d}"
    cutoff = f"2025-{6 + (index % 4):02d}-20T23:59:59Z"
    base_revision = f"MASTER-{index:02d}-R1"
    ops_revision = f"OPS-{index:02d}-R2"
    partner_revision = f"PARTNER-{index:02d}-R3"
    compliance_revision = f"COMPLIANCE-{index:02d}-R4"
    bad_revision = f"UNTRUSTED-{index:02d}-R5"
    future_revision = f"COMPLIANCE-{index:02d}-R6"
    risk_team = f"risk-team-{(index % 5) + 1}"
    exposure = 850_000 + index * 7_500

    entities = ["entity_id,status,owner,exposure,updated_at,revision,source"]
    for item in range(1, 161):
        current_id = entity_id if item == 70 + index else f"ACCT-{index:02d}-{item:03d}"
        if current_id == entity_id:
            entities.append(
                f"{current_id},pending,team-{index % 7 + 1},{exposure - 50000},"
                f"2025-05-01T08:00:00Z,{base_revision},master"
            )
        else:
            entities.append(
                f"{current_id},{['active','pending','closed'][item % 3]},team-{item % 9 + 1},"
                f"{120000 + item * 2300},2025-04-{item % 27 + 1:02d}T08:00:00Z,"
                f"MASTER-{index:02d}-{item:03d},master"
            )

    changes: list[dict[str, Any]] = []
    for item in range(1, 91):
        changes.append(
            {
                "revision": f"NOISE-{index:02d}-{item:03d}",
                "entity_id": f"ACCT-{index:02d}-{(item * 7) % 160 + 1:03d}",
                "source": ["ops", "partner", "compliance"][item % 3],
                "effective_at": f"2025-05-{item % 27 + 1:02d}T12:00:00Z",
                "patch": {"status": ["active", "pending", "closed"][item % 3]},
            }
        )
    target_changes = [
        {
            "revision": ops_revision,
            "entity_id": entity_id,
            "source": "ops",
            "effective_at": "2025-06-12T10:00:00Z",
            "patch": {"status": "active", "owner": f"ops-team-{index % 4 + 1}"},
        },
        {
            "revision": partner_revision,
            "entity_id": entity_id,
            "source": "partner",
            "effective_at": "2025-06-18T18:00:00Z",
            "patch": {"status": "approved", "exposure": exposure - 25_000},
        },
        {
            "revision": compliance_revision,
            "entity_id": entity_id,
            "source": "compliance",
            "effective_at": "2025-06-19T09:30:00Z",
            "patch": {"status": "suspended", "owner": risk_team, "exposure": exposure},
        },
        {
            "revision": bad_revision,
            "entity_id": entity_id,
            "source": "emergency",
            "effective_at": "2025-06-19T20:00:00Z",
            "patch": {"status": "active", "owner": "unknown"},
        },
        {
            "revision": future_revision,
            "entity_id": entity_id,
            "source": "compliance",
            "effective_at": "2026-01-01T00:00:00Z",
            "patch": {"status": "closed"},
        },
    ]
    changes.extend(target_changes)
    signatures = {
        item["revision"]: hashlib.sha256(
            f"agentbench-v3|{item['source']}|{item['revision']}|{item['entity_id']}".encode()
        ).hexdigest()
        for item in changes
        if item["revision"] != bad_revision
    }
    signatures[bad_revision] = "0" * 64
    policy = {
        "as_of": cutoff,
        "source_priority": {
            "master": 10,
            "partner": 30,
            "ops": 50,
            "compliance": 90,
            "emergency": 100,
        },
        "signature_template": "sha256('agentbench-v3|{source}|{revision}|{entity_id}')",
        "tie_break": ["source_priority_desc", "effective_at_desc", "revision_asc"],
        "field_merge": "select one accepted revision; do not merge fields across revisions",
    }
    expected = {
        "case_id": f"AUDIT-{index:02d}",
        "entity_id": entity_id,
        "as_of": cutoff,
        "decision": {
            "status": "suspended",
            "owner": risk_team,
            "exposure": exposure,
            "accepted_revision": compliance_revision,
        },
        "rejected_revisions": [
            {"revision": future_revision, "reason": "after-cutoff"},
            {"revision": bad_revision, "reason": "invalid-signature"},
        ],
        "superseded_revisions": [base_revision, ops_revision, partner_revision],
        "evidence": [
            f"entities.csv#{entity_id}",
            f"changes.jsonl#{compliance_revision}",
            f"signatures.json#{compliance_revision}",
            "source-policy.json#source_priority.compliance",
        ],
    }
    target = "deliverables/audit.json"
    rules = (
        "# Reconciliation rules\n\n"
        "1. Work as of `source-policy.json.as_of`; later revisions are rejected.\n"
        "2. Recompute every signature using `signature_template`; mismatches are rejected.\n"
        "3. Choose one whole revision by priority, effective time, then revision ID. Never merge fields.\n"
        "4. The master row participates as the lowest-priority signed baseline.\n"
        "5. Sort rejected revisions by reason then revision; sort superseded revisions lexicographically.\n"
        "6. Evidence must use the exact file anchors shown in the output contract.\n"
    )
    return {
        "slug": f"knowledge.cross-document-{index:03d}",
        "version": "3.0.0",
        "category": "knowledge-work",
        "title": f"冲突证据链审计 {index:02d}",
        "description": "跨文件验证签名、时序、来源优先级与不可合并修订，生成可追溯审计结论。",
        "instruction": (
            f"按照 `RULES.md`，审计实体 `{entity_id}`，截止时间以策略文件为准。联合读取"
            " `entities.csv`、`changes.jsonl`、`signatures.json` 与 `source-policy.json`，"
            f"把最终审计对象写入 `{target}`。输出字段必须为 case_id、entity_id、as_of、"
            "decision、rejected_revisions、superseded_revisions、evidence；case_id 为 "
            f"`AUDIT-{index:02d}`。必须验证签名和时间，禁止把不同修订的字段拼接成一个结果。"
        ),
        "tools": ["filesystem", "search"],
        "limits": {
            "max_steps": 30,
            "time_target_seconds": 900 if index <= 7 else 1200,
            "token_budget": 26000 + index * 600,
        },
        "validators": [
            _validator("file_exists", 5, path=target),
            _validator("json_file", 90, path=target, expected=expected, critical=True, critical_min_score=75),
            _validator("forbidden_paths", 5, paths=[".git", "*.bak", "source-*.*.modified"]),
        ],
        "tags": ["long-context", "evidence-chain", "temporal", "audit", "v3"],
        "initial_files": {
            "entities.csv": "\n".join(entities) + "\n",
            "changes.jsonl": "\n".join(json.dumps(item, ensure_ascii=False) for item in changes)
            + "\n",
            "signatures.json": json.dumps(signatures, ensure_ascii=False, indent=2),
            "source-policy.json": json.dumps(policy, ensure_ascii=False, indent=2),
            "RULES.md": rules,
        },
        "metadata": {
            "demo_actions": [
                {
                    "tool": "write_file",
                    "arguments": {
                        "path": target,
                        "content": json.dumps(expected, ensure_ascii=False, indent=2) + "\n",
                    },
                }
            ],
            "demo_response": "审计证据链已生成并完成自检。",
            "difficulty": 4 if index <= 7 else 5,
            "estimated_minutes": 18 if index <= 7 else 25,
            "capability": "cross-document-evidence-reconciliation",
            "quality_revision": "v3-p0",
        },
    }


def _security_hardening_case(index: int) -> dict[str, Any]:
    namespace = f"tenant-{index:02d}"
    allowed_suffix = [".json", ".txt", ".bin"][(index - 1) % 3]
    max_bytes = 4096 + index * 257
    secret_hex = hashlib.sha256(f"agentbench-security-v3-{index}".encode()).hexdigest()
    solution = textwrap.dedent(
        r'''
        from __future__ import annotations

        import copy
        import hashlib
        import hmac
        import os
        import re
        import secrets
        import threading
        import urllib.parse
        from pathlib import Path, PurePosixPath


        class SecurityError(ValueError):
            pass


        class SignatureError(SecurityError):
            pass


        class ReplayConflict(SecurityError):
            pass


        class TargetConflict(SecurityError):
            pass


        _REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")
        _SENSITIVE = {
            "authorization", "xapikey", "cookie", "setcookie", "token",
            "accesstoken", "refreshtoken", "secret", "password", "signature",
        }


        def _sensitive(name):
            return re.sub(r"[-_]", "", str(name).casefold()) in _SENSITIVE


        def _redact_url(value):
            try:
                parsed = urllib.parse.urlsplit(value)
            except ValueError:
                return value
            if not parsed.scheme or not parsed.netloc or not parsed.query:
                return value
            query = [
                (key, "***" if _sensitive(key) else item)
                for key, item in urllib.parse.parse_qsl(
                    parsed.query, keep_blank_values=True, strict_parsing=False
                )
            ]
            return urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
            )


        def redact_event(event):
            def visit(value, key=None):
                if key is not None and _sensitive(key):
                    return "***"
                if isinstance(value, dict):
                    return {item_key: visit(item, item_key) for item_key, item in value.items()}
                if isinstance(value, list):
                    return [visit(item) for item in value]
                if isinstance(value, tuple):
                    return tuple(visit(item) for item in value)
                if isinstance(value, str) and str(key).casefold() in {"url", "uri"}:
                    return _redact_url(value)
                return copy.deepcopy(value)

            return visit(event)


        class SecureArtifactStore:
            def __init__(self, root, secret, namespace, max_bytes, allowed_suffix):
                if type(secret) is not bytes or not secret:
                    raise TypeError("secret must be non-empty bytes")
                if type(namespace) is not str or not re.fullmatch(r"[a-z0-9-]{3,40}", namespace):
                    raise TypeError("invalid namespace")
                if type(max_bytes) is not int or max_bytes <= 0:
                    raise TypeError("max_bytes must be a positive integer")
                if type(allowed_suffix) is not str or not re.fullmatch(r"\.[a-z0-9]{1,8}", allowed_suffix):
                    raise TypeError("invalid allowed suffix")
                self.root = Path(root)
                if not self.root.is_dir() or self.root.is_symlink():
                    raise SecurityError("root must be a real directory")
                self.secret = secret
                self.namespace = namespace
                self.max_bytes = max_bytes
                self.allowed_suffix = allowed_suffix
                self._lock = threading.RLock()
                self._requests = {}

            @staticmethod
            def _payload(request_id, encoded_path, body):
                return request_id.encode("ascii") + b"\n" + encoded_path.encode("ascii") + b"\n" + body

            def _verify(self, request_id, encoded_path, body, signature):
                if type(signature) is not str or not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
                    raise SignatureError("signature must be canonical sha256 hex")
                expected = hmac.new(
                    self.secret, self._payload(request_id, encoded_path, body), hashlib.sha256
                ).hexdigest()
                if not hmac.compare_digest(expected.encode("ascii"), signature[7:].encode("ascii")):
                    raise SignatureError("signature mismatch")

            def _decode(self, encoded_path):
                if type(encoded_path) is not str or not encoded_path or len(encoded_path) > 240:
                    raise SecurityError("invalid encoded path")
                try:
                    encoded_path.encode("ascii")
                    decoded = urllib.parse.unquote_to_bytes(encoded_path).decode("utf-8", "strict")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    raise SecurityError("path must use canonical ASCII percent encoding") from None
                if "%" in decoded or "\\" in decoded or "\x00" in decoded:
                    raise SecurityError("ambiguous path encoding")
                if urllib.parse.quote(decoded, safe="/-._~") != encoded_path:
                    raise SecurityError("non-canonical path encoding")
                path = PurePosixPath(decoded)
                parts = path.parts
                if (
                    path.is_absolute()
                    or len(parts) < 3
                    or parts[0] != self.namespace
                    or parts[1] != "inbox"
                    or any(part in {"", ".", ".."} for part in parts)
                    or any(not re.fullmatch(r"[A-Za-z0-9._~ -]+", part) for part in parts)
                    or not parts[-1].endswith(self.allowed_suffix)
                ):
                    raise SecurityError("path violates namespace policy")
                return parts

            @staticmethod
            def _write_all(file_descriptor, body):
                view = memoryview(body)
                while view:
                    written = os.write(file_descriptor, view)
                    if written <= 0:
                        raise OSError("short write")
                    view = view[written:]

            def _secure_write_posix(self, parts, body, request_id):
                nofollow = getattr(os, "O_NOFOLLOW", 0)
                directory = getattr(os, "O_DIRECTORY", 0)
                root_fd = os.open(self.root, os.O_RDONLY | directory | nofollow)
                current_fd = root_fd
                temp_name = None
                try:
                    for part in parts[:-1]:
                        next_fd = os.open(
                            part, os.O_RDONLY | directory | nofollow, dir_fd=current_fd
                        )
                        if current_fd != root_fd:
                            os.close(current_fd)
                        current_fd = next_fd
                    temp_name = f".agentbench-{request_id}-{secrets.token_hex(8)}.tmp"
                    temp_fd = os.open(
                        temp_name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                        0o600,
                        dir_fd=current_fd,
                    )
                    try:
                        self._write_all(temp_fd, body)
                        os.fsync(temp_fd)
                    finally:
                        os.close(temp_fd)
                    try:
                        os.link(
                            temp_name,
                            parts[-1],
                            src_dir_fd=current_fd,
                            dst_dir_fd=current_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        raise TargetConflict("target already exists") from None
                    finally:
                        try:
                            os.unlink(temp_name, dir_fd=current_fd)
                        except FileNotFoundError:
                            pass
                        temp_name = None
                except (NotADirectoryError, FileNotFoundError, OSError) as exc:
                    if isinstance(exc, TargetConflict):
                        raise
                    raise SecurityError("unsafe or unavailable path") from exc
                finally:
                    if temp_name is not None:
                        try:
                            os.unlink(temp_name, dir_fd=current_fd)
                        except OSError:
                            pass
                    if current_fd != root_fd:
                        os.close(current_fd)
                    os.close(root_fd)

            def _secure_write_portable(self, parts, body, request_id):
                root = self.root.resolve(strict=True)
                parent = root
                for part in parts[:-1]:
                    candidate = parent / part
                    if candidate.is_symlink():
                        raise SecurityError("symbolic-link parent rejected")
                    parent = candidate.resolve(strict=True)
                    if not parent.is_relative_to(root):
                        raise SecurityError("path escaped root")
                target = parent / parts[-1]
                if target.exists() or target.is_symlink():
                    raise TargetConflict("target already exists")
                temporary = parent / f".agentbench-{request_id}-{secrets.token_hex(8)}.tmp"
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    self._write_all(descriptor, body)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    raise TargetConflict("target already exists") from None
                finally:
                    temporary.unlink(missing_ok=True)

            def put(self, encoded_path, body, signature, request_id):
                if type(body) is not bytes:
                    raise TypeError("body must be bytes")
                if not body or len(body) > self.max_bytes:
                    raise SecurityError("body size rejected")
                if type(request_id) is not str or not _REQUEST_ID.fullmatch(request_id):
                    raise SecurityError("invalid request id")
                parts = self._decode(encoded_path)
                self._verify(request_id, encoded_path, body, signature)
                fingerprint = hashlib.sha256(
                    encoded_path.encode("ascii") + b"\x00" + body
                ).hexdigest()
                with self._lock:
                    previous = self._requests.get(request_id)
                    if previous is not None:
                        if previous["fingerprint"] != fingerprint:
                            raise ReplayConflict("request id reused with different content")
                        return copy.deepcopy(previous["result"])
                    if os.open in os.supports_dir_fd and os.link in os.supports_dir_fd:
                        self._secure_write_posix(parts, body, request_id)
                    else:
                        self._secure_write_portable(parts, body, request_id)
                    result = {
                        "path": "/".join(parts),
                        "size": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                    }
                    self._requests[request_id] = {
                        "fingerprint": fingerprint,
                        "result": copy.deepcopy(result),
                    }
                    return copy.deepcopy(result)
        '''
    ).strip() + "\n"
    initial = textwrap.dedent(
        '''
        from __future__ import annotations


        class SecurityError(ValueError):
            pass


        class SignatureError(SecurityError):
            pass


        class ReplayConflict(SecurityError):
            pass


        class TargetConflict(SecurityError):
            pass


        def redact_event(event):
            raise NotImplementedError


        class SecureArtifactStore:
            def __init__(self, root, secret, namespace, max_bytes, allowed_suffix):
                raise NotImplementedError

            def put(self, encoded_path, body, signature, request_id):
                raise NotImplementedError
        '''
    ).strip() + "\n"
    public_smoke = textwrap.dedent(
        f'''
        import hashlib
        import hmac
        import tempfile
        from pathlib import Path

        from secure_gateway import SecureArtifactStore, redact_event

        root = Path(tempfile.mkdtemp())
        (root / "{namespace}" / "inbox").mkdir(parents=True)
        secret = b"public-smoke-key"
        path = "{namespace}/inbox/public{allowed_suffix}"
        body = b"public-smoke"
        request_id = "public-0001"
        payload = request_id.encode() + b"\\n" + path.encode() + b"\\n" + body
        signature = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
        store = SecureArtifactStore(root, secret, "{namespace}", {max_bytes}, "{allowed_suffix}")
        result = store.put(path, body, signature, request_id)
        assert result["size"] == len(body)
        assert redact_event({{"Authorization": "Bearer demo"}})["Authorization"] == "***"
        print("PUBLIC_SECURITY_SMOKE_OK")
        '''
    ).strip() + "\n"
    private_validator = textwrap.dedent(
        r'''
        import concurrent.futures
        import copy
        import hashlib
        import hmac
        import json
        import os
        import pathlib
        import tempfile
        import sys
        import urllib.parse

        workspace = pathlib.Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(workspace))

        metrics = {
            "valid_store": 0,
            "canonicalization": 0,
            "authentication": 0,
            "symlink_containment": 0,
            "atomic_replay": 0,
            "redaction": 0,
        }
        evidence = {}
        try:
            from secure_gateway import (
                ReplayConflict,
                SecureArtifactStore,
                SecurityError,
                SignatureError,
                TargetConflict,
                redact_event,
            )
        except Exception as exc:
            evidence["import"] = repr(exc)
        else:
            namespace = "__NAMESPACE__"
            suffix = "__SUFFIX__"
            maximum = __MAX_BYTES__
            secret = bytes.fromhex("__SECRET_HEX__")

            def fresh(label):
                root = pathlib.Path(tempfile.mkdtemp(prefix=label + "-", dir=workspace))
                (root / namespace / "inbox").mkdir(parents=True)
                return root, SecureArtifactStore(root, secret, namespace, maximum, suffix)

            def sign(request_id, path, body, key=secret):
                payload = request_id.encode("ascii") + b"\n" + path.encode("ascii") + b"\n" + body
                return "sha256=" + hmac.new(key, payload, hashlib.sha256).hexdigest()

            try:
                root, store = fresh("valid")
                path = namespace + "/inbox/report%20__INDEX__" + suffix
                body = b"verified-payload-__INDEX__"
                request_id = "valid-__INDEX__-0001"
                result = store.put(path, body, sign(request_id, path, body), request_id)
                decoded = urllib.parse.unquote(path)
                assert (root / decoded).read_bytes() == body
                assert result == {
                    "path": decoded,
                    "size": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
                metrics["valid_store"] = 100
            except Exception as exc:
                evidence["valid_store"] = repr(exc)

            try:
                root, store = fresh("paths")
                attacks = [
                    "../escape" + suffix,
                    namespace + "/inbox/%2e%2e/escape" + suffix,
                    namespace + "/inbox/%252e%252e/escape" + suffix,
                    namespace + "\\inbox\\escape" + suffix,
                    "/" + namespace + "/inbox/escape" + suffix,
                    "other/inbox/escape" + suffix,
                    namespace + "%2finbox%2fescape" + suffix,
                    namespace + "/inbox/bad%00name" + suffix,
                    namespace + "/inbox/wrong.exe",
                ]
                for number, path in enumerate(attacks):
                    body = b"attack"
                    request_id = f"attack-{number:02d}-0001"
                    try:
                        store.put(path, body, sign(request_id, path, body), request_id)
                    except (SecurityError, TypeError):
                        pass
                    else:
                        raise AssertionError("ambiguous path accepted: " + path)
                assert not (workspace / ("escape" + suffix)).exists()
                metrics["canonicalization"] = 100
            except Exception as exc:
                evidence["canonicalization"] = repr(exc)

            try:
                root, store = fresh("auth")
                path = namespace + "/inbox/auth" + suffix
                body = b"authenticated"
                rejected = [
                    "sha256=" + "0" * 64,
                    "SHA256=" + "0" * 64,
                    "0" * 64,
                    "sha256=" + "A" * 64,
                ]
                for number, supplied in enumerate(rejected):
                    try:
                        store.put(path, body, supplied, f"auth-{number:02d}-0001")
                    except SignatureError:
                        pass
                    else:
                        raise AssertionError("invalid signature accepted")
                try:
                    SecureArtifactStore(root, bytearray(secret), namespace, maximum, suffix)
                except TypeError:
                    pass
                else:
                    raise AssertionError("mutable key type accepted")
                try:
                    store.put(path, "not-bytes", sign("auth-body-01", path, body), "auth-body-01")
                except TypeError:
                    pass
                else:
                    raise AssertionError("text body accepted")
                assert not (root / namespace / "inbox" / ("auth" + suffix)).exists()
                metrics["authentication"] = 100
            except Exception as exc:
                evidence["authentication"] = repr(exc)

            try:
                root, store = fresh("links")
                outside = pathlib.Path(tempfile.mkdtemp(prefix="outside-", dir=workspace))
                link = root / namespace / "inbox" / "linked"
                symlink_supported = True
                try:
                    os.symlink(outside, link, target_is_directory=True)
                except (OSError, NotImplementedError):
                    symlink_supported = False
                if symlink_supported:
                    path = namespace + "/inbox/linked/pwn" + suffix
                    body = b"outside-write"
                    request_id = "symlink-0001"
                    try:
                        store.put(path, body, sign(request_id, path, body), request_id)
                    except SecurityError:
                        pass
                    else:
                        raise AssertionError("symlink parent accepted")
                    assert not (outside / ("pwn" + suffix)).exists()
                target = root / namespace / "inbox" / ("existing" + suffix)
                target.write_bytes(b"original")
                path = namespace + "/inbox/existing" + suffix
                body = b"replacement"
                request_id = "existing-0001"
                try:
                    store.put(path, body, sign(request_id, path, body), request_id)
                except TargetConflict:
                    pass
                else:
                    raise AssertionError("existing target overwritten")
                assert target.read_bytes() == b"original"
                metrics["symlink_containment"] = 100
            except Exception as exc:
                evidence["symlink_containment"] = repr(exc)

            try:
                root, store = fresh("race")
                path = namespace + "/inbox/race" + suffix
                body = b"single-winner"
                shared_id = "replay-0001"
                shared_signature = sign(shared_id, path, body)
                with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                    replays = list(
                        pool.map(lambda _: store.put(path, body, shared_signature, shared_id), range(32))
                    )
                assert all(item == replays[0] for item in replays)
                altered = b"changed"
                try:
                    store.put(path, altered, sign(shared_id, path, altered), shared_id)
                except ReplayConflict:
                    pass
                else:
                    raise AssertionError("replay payload conflict accepted")
                race_path = namespace + "/inbox/winner" + suffix

                def contender(number):
                    request_id = f"winner-{number:02d}-0001"
                    try:
                        return store.put(race_path, body, sign(request_id, race_path, body), request_id)
                    except TargetConflict:
                        return None

                with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                    winners = list(pool.map(contender, range(24)))
                assert sum(item is not None for item in winners) == 1
                assert not list((root / namespace / "inbox").glob(".agentbench-*.tmp"))
                metrics["atomic_replay"] = 100
            except Exception as exc:
                evidence["atomic_replay"] = repr(exc)

            try:
                source = {
                    "Authorization": "Bearer private",
                    "nested": [
                        {"X_API_KEY": "api-secret", "keep": "visible"},
                        {"url": "https://example.test/cb?token=abc&keep=1#done"},
                    ],
                    "Cookie": {"session": "secret"},
                }
                before = copy.deepcopy(source)
                redacted = redact_event(source)
                assert source == before and redacted is not source
                assert redacted["Authorization"] == "***"
                assert redacted["nested"][0] == {"X_API_KEY": "***", "keep": "visible"}
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(redacted["nested"][1]["url"]).query)
                assert query == {"token": ["***"], "keep": ["1"]}
                assert redacted["Cookie"] == "***"
                metrics["redaction"] = 100
            except Exception as exc:
                evidence["redaction"] = repr(exc)

        print("AGENTBENCH_METRICS=" + json.dumps({"metrics": metrics, "evidence": evidence}, sort_keys=True))
        '''
    ).strip()
    replacements = {
        "__NAMESPACE__": namespace,
        "__SUFFIX__": allowed_suffix,
        "__MAX_BYTES__": str(max_bytes),
        "__SECRET_HEX__": secret_hex,
        "__INDEX__": f"{index:02d}",
    }
    for marker, value in replacements.items():
        private_validator = private_validator.replace(marker, value)
    metrics = [
        {"key": "valid_store", "name": "合法写入与完整性", "weight": 15},
        {"key": "canonicalization", "name": "编码规范化与路径策略", "weight": 20},
        {"key": "authentication", "name": "签名与密钥类型", "weight": 15},
        {"key": "symlink_containment", "name": "符号链接与覆盖防护", "weight": 20},
        {"key": "atomic_replay", "name": "并发原子性与重放冲突", "weight": 20},
        {"key": "redaction", "name": "递归日志脱敏", "weight": 10},
    ]
    contract = (
        "# SecureArtifactStore contract\n\n"
        f"Implement `secure_gateway.py` for namespace `{namespace}`, maximum body size "
        f"{max_bytes} bytes and allowed suffix `{allowed_suffix}`. `put(encoded_path, body, "
        "signature, request_id)` accepts bytes only and writes below `<namespace>/inbox/`; "
        "parent directories already exist. Paths use strict UTF-8 percent decoding exactly once "
        "and must be canonically re-encoded with safe characters `/-._~`; reject absolute paths, "
        "backslashes, dot segments, decoded percent signs, NULs, wrong namespaces and suffixes. "
        "The signature is lowercase `sha256=<hex>` HMAC over "
        "`request_id + LF + encoded_path + LF + body`; the secret must be immutable bytes and "
        "comparison must be constant-time. Writes must not follow symlink parents, overwrite an "
        "existing target or expose partial files. Identical request replays return the original "
        "result; changed payloads raise ReplayConflict; concurrent target races have one winner. "
        "Return path, size and sha256. `redact_event` recursively copies dictionaries/lists/tuples "
        "and redacts authorization, API keys, cookies, tokens, secrets, passwords, signatures and "
        "sensitive URL query values without mutating the input.\n"
    )
    return {
        "slug": f"security.hardening-{index:03d}",
        "version": "3.0.0",
        "category": "security",
        "title": f"签名制品入口组合加固 {index:02d}",
        "description": "修复编码、签名、路径、符号链接、并发重放和日志泄密组成的攻击链。",
        "instruction": (
            "按照 `SECURITY_CONTRACT.md` 完成 `secure_gateway.py`，并运行 "
            "`python public_smoke.py`。不得修改公开冒烟脚本、创建 tests/ 或绕过文件系统约束。"
        ),
        "tools": ["filesystem", "search", "shell"],
        "limits": {
            "max_steps": 85,
            "time_target_seconds": 1800 if index <= 7 else 2400,
            "token_budget": 52000,
            "network": "disabled",
            "docker_image": "python:3.12-alpine",
            "validator_timeout_seconds": 240,
        },
        "validators": [
            _validator("file_exists", 3, path="secure_gateway.py"),
            _validator(
                "command_metrics",
                94,
                command="python {private_root}/validate_secure_gateway.py",
                private_files={"validate_secure_gateway.py": private_validator},
                metrics=metrics,
                critical=True,
                critical_min_score=70,
            ),
            _validator(
                "forbidden_paths",
                3,
                paths=["tests", ".git", ".agentbench-private-*", "public_smoke.py.modified"],
            ),
        ],
        "tags": [
            "security",
            "hmac",
            "canonicalization",
            "symlink",
            "race-condition",
            "redaction",
            "v3",
        ],
        "initial_files": {
            "secure_gateway.py": initial,
            "public_smoke.py": public_smoke,
            "SECURITY_CONTRACT.md": contract,
        },
        "metadata": {
            "demo_actions": [
                {"tool": "write_file", "arguments": {"path": "secure_gateway.py", "content": solution}}
            ],
            "demo_response": "安全制品入口已完成组合加固并通过公开验证。",
            "difficulty": 4 if index <= 7 else 5,
            "estimated_minutes": 40 if index <= 7 else 55,
            "capability": "adversarial-security-engineering",
            "quality_revision": "v3-p0",
        },
    }


def _ode_bvp_case() -> dict[str, Any]:
    answer = {
        "transformation": "y=exp(x)*u",
        "reduced_equation": "u''+lambda*u=1",
        "lambda_4": {
            "classification": "infinitely-many",
            "family": "exp(x)*(1-cos(2*x))/4+C*exp(x)*sin(2*x)",
        },
        "lambda_1": {
            "classification": "no-solution",
            "compatibility": "violated",
        },
        "lambda_2": {
            "classification": "unique",
            "solution": "exp(x)*(1/2-cos(sqrt(2)*x)/2+(cos(sqrt(2)*pi)-1)*sin(sqrt(2)*x)/(2*sin(sqrt(2)*pi)))",
        },
    }
    return _ode_bvp_definition(answer)


def _business_rules_case(index: int) -> dict[str, Any]:
    scale = 2 + (index % 2)
    solution = '''from __future__ import annotations

import copy
import hashlib
import json
import threading
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class EventConflict(ValueError):
    pass


class InvalidTransition(ValueError):
    pass


class SequenceError(ValueError):
    pass


class OrderEngine:
    def __init__(self, currency_scale=2):
        self.currency_scale = int(currency_scale)
        self._orders = {}
        self._processed = {}
        self._lock = threading.RLock()

    def _money(self, value):
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise InvalidTransition("invalid amount") from exc
        if not amount.is_finite() or amount <= 0:
            raise InvalidTransition("amount must be positive")
        quantum = Decimal(1).scaleb(-self.currency_scale)
        return amount.quantize(quantum, rounding=ROUND_HALF_UP)

    @staticmethod
    def _fingerprint(event):
        return hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _public(order):
        return {
            "order_id": order["order_id"],
            "seq": order["seq"],
            "status": order["status"],
            "authorized": order["authorized"],
            "captured": order["captured"],
            "refunded": order["refunded"],
        }

    def apply(self, event):
        if not isinstance(event, dict):
            raise InvalidTransition("event must be an object")
        required = {"event_id", "order_id", "seq", "type"}
        if not required <= set(event):
            raise InvalidTransition("missing event field")
        event = copy.deepcopy(event)
        event_id = str(event["event_id"])
        order_id = str(event["order_id"])
        fingerprint = self._fingerprint(event)
        with self._lock:
            previous = self._processed.get(event_id)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise EventConflict("event id reused with a different payload")
                return copy.deepcopy(previous["result"])
            current = copy.deepcopy(self._orders.get(order_id))
            expected_seq = 1 if current is None else current["seq"] + 1
            if not isinstance(event["seq"], int) or event["seq"] != expected_seq:
                raise SequenceError(f"expected sequence {expected_seq}")
            kind = str(event["type"])
            if current is None:
                if kind != "authorize":
                    raise InvalidTransition("first event must authorize")
                amount = self._money(event.get("amount"))
                current = {
                    "order_id": order_id,
                    "seq": event["seq"],
                    "status": "authorized",
                    "authorized": format(amount, "f"),
                    "captured": format(Decimal(0).quantize(amount), "f"),
                    "refunded": format(Decimal(0).quantize(amount), "f"),
                }
            else:
                authorized = Decimal(current["authorized"])
                captured = Decimal(current["captured"])
                refunded = Decimal(current["refunded"])
                if kind == "capture":
                    if current["status"] not in {"authorized", "partially-captured"}:
                        raise InvalidTransition("capture is not allowed")
                    amount = self._money(event.get("amount"))
                    if captured + amount > authorized:
                        raise InvalidTransition("capture exceeds authorization")
                    captured += amount
                    current["captured"] = format(captured, "f")
                    current["status"] = "captured" if captured == authorized else "partially-captured"
                elif kind == "refund":
                    if current["status"] not in {"captured", "partially-refunded"}:
                        raise InvalidTransition("refund is not allowed")
                    amount = self._money(event.get("amount"))
                    if refunded + amount > captured:
                        raise InvalidTransition("refund exceeds capture")
                    refunded += amount
                    current["refunded"] = format(refunded, "f")
                    current["status"] = "refunded" if refunded == captured else "partially-refunded"
                elif kind == "void":
                    if current["status"] != "authorized" or captured != 0:
                        raise InvalidTransition("void is not allowed")
                    current["status"] = "voided"
                else:
                    raise InvalidTransition("unknown event type")
                current["seq"] = event["seq"]
            result = self._public(current)
            self._orders[order_id] = current
            self._processed[event_id] = {"fingerprint": fingerprint, "result": copy.deepcopy(result)}
            return copy.deepcopy(result)

    def snapshot(self):
        with self._lock:
            return {
                "currency_scale": self.currency_scale,
                "orders": [copy.deepcopy(self._orders[key]) for key in sorted(self._orders)],
                "processed": copy.deepcopy(dict(sorted(self._processed.items()))),
            }

    @classmethod
    def from_snapshot(cls, snapshot):
        engine = cls(snapshot["currency_scale"])
        engine._orders = {item["order_id"]: copy.deepcopy(item) for item in snapshot["orders"]}
        engine._processed = copy.deepcopy(snapshot["processed"])
        return engine
'''
    initial = '''from __future__ import annotations


class EventConflict(ValueError):
    pass


class InvalidTransition(ValueError):
    pass


class SequenceError(ValueError):
    pass


class OrderEngine:
    def __init__(self, currency_scale=2):
        raise NotImplementedError

    def apply(self, event):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError

    @classmethod
    def from_snapshot(cls, snapshot):
        raise NotImplementedError
'''
    public_smoke = f'''from src.order_engine import OrderEngine

engine = OrderEngine(currency_scale={scale})
assert engine.apply({{"event_id":"e1","order_id":"o1","seq":1,"type":"authorize","amount":"10"}})["status"] == "authorized"
assert engine.apply({{"event_id":"e2","order_id":"o1","seq":2,"type":"capture","amount":"4"}})["status"] == "partially-captured"
assert engine.apply({{"event_id":"e3","order_id":"o1","seq":3,"type":"capture","amount":"6"}})["status"] == "captured"
print("public smoke passed")
'''
    private_validator = f'''import concurrent.futures
import copy
import json
import pathlib
import sys

workspace = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(workspace))

metrics = {{"state_machine":0,"idempotency":0,"atomic_sequence":0,"money":0,"concurrency":0,"snapshot_restore":0}}
evidence = {{}}
try:
    from src.order_engine import OrderEngine, EventConflict, InvalidTransition, SequenceError
except Exception as exc:
    evidence["import"] = repr(exc)
else:
    def event(eid, oid, seq, kind, amount=None):
        value = {{"event_id":eid,"order_id":oid,"seq":seq,"type":kind}}
        if amount is not None: value["amount"] = amount
        return value
    try:
        e=OrderEngine({scale}); e.apply(event("a","o",1,"authorize","12.3456")); e.apply(event("c1","o",2,"capture","5")); r=e.apply(event("c2","o",3,"capture","7.346")); assert r["status"]=="captured"; e.apply(event("r1","o",4,"refund","2")); r=e.apply(event("r2","o",5,"refund","10.346")); assert r["status"]=="refunded"; metrics["state_machine"]=100
    except Exception as exc: evidence["state_machine"]=repr(exc)
    try:
        e=OrderEngine({scale}); first=event("same","x",1,"authorize","9"); r1=e.apply(first); r2=e.apply(copy.deepcopy(first)); assert r1==r2; conflict=copy.deepcopy(first); conflict["amount"]="10"; ok=False
        try: e.apply(conflict)
        except EventConflict: ok=True
        assert ok and e.snapshot()["orders"][0]["authorized"]==r1["authorized"]; metrics["idempotency"]=100
    except Exception as exc: evidence["idempotency"]=repr(exc)
    try:
        e=OrderEngine({scale}); e.apply(event("a","q",1,"authorize","10")); before=copy.deepcopy(e.snapshot())
        for bad in [event("gap","q",3,"capture","1"),event("over","q",2,"capture","11"),event("bad","q",2,"refund","1")]:
            try: e.apply(bad)
            except (SequenceError,InvalidTransition): pass
            else: raise AssertionError("invalid event accepted")
            assert e.snapshot()==before
        metrics["atomic_sequence"]=100
    except Exception as exc: evidence["atomic_sequence"]=repr(exc)
    try:
        e=OrderEngine({scale}); r=e.apply(event("a","m",1,"authorize","1.005")); assert r["authorized"]=={('"1.005"' if scale == 3 else '"1.01"')};
        for value in ["NaN","Infinity","0","-1"]:
            try: OrderEngine({scale}).apply(event("x"+value,"z",1,"authorize",value))
            except InvalidTransition: pass
            else: raise AssertionError("invalid money accepted")
        metrics["money"]=100
    except Exception as exc: evidence["money"]=repr(exc)
    try:
        e=OrderEngine({scale}); base=event("once","thread",1,"authorize","20")
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool: results=list(pool.map(lambda _: e.apply(copy.deepcopy(base)),range(40)))
        assert all(item==results[0] for item in results) and len(e.snapshot()["processed"])==1; metrics["concurrency"]=100
    except Exception as exc: evidence["concurrency"]=repr(exc)
    try:
        e=OrderEngine({scale}); a=event("a","s",1,"authorize","10"); e.apply(a); e.apply(event("c","s",2,"capture","10")); snap=e.snapshot(); restored=OrderEngine.from_snapshot(copy.deepcopy(snap)); assert restored.snapshot()==snap and restored.apply(copy.deepcopy(a))["status"]=="authorized"; metrics["snapshot_restore"]=100
    except Exception as exc: evidence["snapshot_restore"]=repr(exc)
print("AGENTBENCH_METRICS="+json.dumps({{"metrics":metrics,"evidence":evidence}},sort_keys=True))
'''
    metric_specs = [
        {"key": "state_machine", "name": "状态机与业务不变量", "weight": 25},
        {"key": "idempotency", "name": "全局幂等与冲突检测", "weight": 20},
        {"key": "atomic_sequence", "name": "顺序与失败原子性", "weight": 15},
        {"key": "money", "name": "金额精度与非法值", "weight": 15},
        {"key": "concurrency", "name": "并发重复事件", "weight": 15},
        {"key": "snapshot_restore", "name": "快照恢复兼容", "weight": 10},
    ]
    return {
        "slug": f"coding.business-rules-{index:03d}",
        "version": "3.0.0",
        "category": "software-engineering",
        "title": f"并发订单事件状态机 {index:02d}",
        "description": "实现多阶段资金状态机、全局幂等、失败原子性、并发安全与快照恢复。",
        "instruction": (
            f"按照 `SPEC.md` 完成 `src/order_engine.py` 的 OrderEngine，币种精度为 {scale} 位。"
            "必须实现 authorize/capture/refund/void 状态机、严格单调序号、event_id 全局幂等、"
            "同 ID 异载荷冲突、Decimal 金额规则、并发安全和可恢复快照。运行 "
            "`python public_smoke.py` 自检。禁止修改 public_smoke.py 或创建 tests/。"
        ),
        "tools": ["filesystem", "search", "shell"],
        "limits": {
            "max_steps": 80,
            "time_target_seconds": 1800,
            "token_budget": 50000,
            "network": "disabled",
            "docker_image": "python:3.12-alpine",
            "validator_timeout_seconds": 240,
        },
        "validators": [
            _validator("file_exists", 3, path="src/order_engine.py"),
            _validator(
                "command_metrics",
                92,
                command="python {private_root}/validate_order_engine.py",
                private_files={"validate_order_engine.py": private_validator},
                metrics=metric_specs,
                critical=True,
                critical_min_score=60,
            ),
            _validator("file_content", 2, path="public_smoke.py", expected=public_smoke),
            _validator("forbidden_paths", 3, paths=["tests", ".git", ".agentbench-private-*"]),
        ],
        "tags": ["python", "state-machine", "idempotency", "concurrency", "property-tests", "v3"],
        "initial_files": {
            "src/__init__.py": "",
            "src/order_engine.py": initial,
            "public_smoke.py": public_smoke,
            "SPEC.md": (
                "# OrderEngine contract\n\n"
                "`apply(event)` accepts event_id, order_id, integer seq, type and optional amount. "
                "The first seq is 1 and every accepted event increments it by exactly one. "
                "authorize creates an order; captures may be partial but cannot exceed authorization; "
                "refunds require a fully captured order and cannot exceed captured funds; void is only "
                "allowed before capture. Invalid events must leave all state unchanged. Money is finite, "
                f"positive Decimal rounded HALF_UP to {scale} places. Duplicate identical event IDs return "
                "the original result; a changed payload raises EventConflict. apply is thread-safe. "
                "snapshot returns JSON-serializable canonical state including idempotency records; "
                "from_snapshot restores it without changing duplicate-event behavior.\n"
            ),
        },
        "metadata": {
            "demo_actions": [
                {"tool": "write_file", "arguments": {"path": "src/order_engine.py", "content": solution}}
            ],
            "demo_response": "订单事件状态机已实现并通过公开验证。",
            "difficulty": 4 if index <= 10 else 5,
            "estimated_minutes": 35,
            "capability": "stateful-software-engineering",
            "quality_revision": "v3-p0",
        },
    }
def _ode_bvp_definition(answer: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "transformation": {
            "expected": "y=exp(x)*u",
            "accepted": ["y=e^x*u", "y=u*exp(x)"],
            "weight": 1,
        },
        "reduced_equation": {
            "expected": "u''+lambda*u=1",
            "accepted": ["u''+λu=1", "u''+lambda u=1"],
            "weight": 1,
        },
        "lambda_4.classification": {"expected": "infinitely-many", "weight": 1},
        "lambda_4.family": {
            "kind": "expression",
            "expected": answer["lambda_4"]["family"],
            "variables": ["x", "C"],
            "weight": 3,
        },
        "lambda_1.classification": {"expected": "no-solution", "weight": 1},
        "lambda_1.compatibility": {"expected": "violated", "weight": 1},
        "lambda_2.classification": {"expected": "unique", "weight": 1},
        "lambda_2.solution": {
            "kind": "expression",
            "expected": answer["lambda_2"]["solution"],
            "variables": ["x"],
            "weight": 3,
        },
    }
    return {
        "slug": "math.ode-second-order-ivp",
        "version": "3.0.0",
        "category": "reasoning",
        "title": "含参数二阶边值问题与 Fredholm 相容性",
        "description": "同时判断无解、唯一解和无穷多解，并给出等价符号表达式。",
        "instruction": (
            "考虑边值问题 y''-2y'+(1+lambda)y=e^x，0<=x<=pi，y(0)=y(pi)=0。"
            "先作代换 y=e^x*u。分别分析 lambda=4、lambda=1、lambda=2：判断解的"
            "存在性/唯一性；lambda=4 给出含任意常数 C 的通解族，lambda=1 指出相容性"
            "是否满足，lambda=2 给出唯一解。只输出一个 JSON 对象，字段严格为 "
            "transformation、reduced_equation、lambda_4、lambda_1、lambda_2。表达式使用 "
            "exp、sin、cos、sqrt、pi 和 `*`，不要使用小数近似。"
        ),
        "tools": [],
        "limits": {
            "max_steps": 18,
            "time_target_seconds": 1500,
            "token_budget": 30000,
        },
        "validators": [_validator("symbolic_json", 100, fields=fields)],
        "tags": ["math", "ode", "boundary-value", "fredholm", "symbolic-equivalence", "v3"],
        "initial_files": {},
        "metadata": {
            "demo_response": json.dumps(answer, ensure_ascii=False),
            "difficulty": 5,
            "estimated_minutes": 25,
            "capability": "differential-equation",
            "quality_revision": "v3-p0",
        },
    }


def upgrade_v3_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace low-discrimination V2 definitions while preserving catalog order."""
    replacements = {
        **{
            f"knowledge.cross-document-{index:03d}": _cross_document_case(index)
            for index in range(1, 16)
        },
        **{
            f"coding.business-rules-{index:03d}": _business_rules_case(index)
            for index in range(1, 21)
        },
        **{
            f"security.hardening-{index:03d}": _security_hardening_case(index)
            for index in range(1, 16)
        },
        "math.ode-second-order-ivp": _ode_bvp_case(),
    }
    upgraded = [replacements.get(str(case.get("slug")), case) for case in cases]
    from .v3_p1_catalog import upgrade_v3_p1_cases

    return upgrade_v3_p1_cases(upgraded)
