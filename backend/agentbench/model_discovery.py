from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import tomllib
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .execution import native_cli_status

SOURCE_META: dict[str, tuple[str, str | None]] = {
    "api": ("API 接口", None),
    "codex-cli": ("Codex CLI", "codex"),
    "claude-code": ("Claude Code", "claude"),
    "opencode-cli": ("OpenCode", "opencode"),
    "reasonix-cli": ("Reasonix", "reasonix"),
    "gemini-cli": ("Gemini CLI", "gemini"),
    "aider-cli": ("Aider", "aider"),
    "kimi-code": ("Kimi Code", "kimi"),
    "qoder-cli": ("Qoder", "qoderclicn"),
    "cursor-cli": ("Cursor Agent", "agent"),
}

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_MODEL_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]*(?:/[A-Za-z0-9][A-Za-z0-9._:/+-]*)+$")
_MAX_CONFIG_BYTES = 5_000_000


def _read_json(path: Path) -> Any:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_CONFIG_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_CONFIG_BYTES:
            return {}
        value = tomllib.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return {}


def _model_option(
    model_id: str,
    *,
    label: str | None,
    provider_id: str,
    provider_label: str,
    source: str,
    configured: bool = False,
    is_default: bool = False,
) -> dict[str, Any]:
    return {
        "id": model_id,
        "label": label or model_id,
        "provider_id": provider_id,
        "provider_label": provider_label,
        "source": source,
        "configured": configured,
        "is_default": is_default,
    }


def _deduplicate_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in models:
        model_id = str(item.get("id") or "").strip()
        provider_id = str(item.get("provider_id") or "default").strip()
        if not model_id:
            continue
        key = (provider_id, model_id)
        current = merged.get(key)
        if current is None:
            merged[key] = {**item, "id": model_id, "provider_id": provider_id}
            continue
        current["configured"] = bool(current.get("configured") or item.get("configured"))
        current["is_default"] = bool(current.get("is_default") or item.get("is_default"))
        if current.get("label") == current["id"] and item.get("label"):
            current["label"] = item["label"]
        if item.get("source") and item["source"] not in str(current.get("source") or ""):
            current["source"] = f"{current.get('source')} + {item['source']}"
    return sorted(
        merged.values(),
        key=lambda item: (
            not bool(item.get("is_default")),
            not bool(item.get("configured")),
            str(item.get("provider_label") or "").lower(),
            str(item.get("label") or item["id"]).lower(),
        ),
    )


def _providers_for_models(
    providers: list[dict[str, Any]], models: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in models:
        provider_id = str(item.get("provider_id") or "default")
        counts[provider_id] = counts.get(provider_id, 0) + 1
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for provider in providers:
        provider_id = str(provider.get("id") or "default")
        if provider_id in seen:
            continue
        seen.add(provider_id)
        output.append({**provider, "model_count": counts.get(provider_id, 0)})
    for item in models:
        provider_id = str(item.get("provider_id") or "default")
        if provider_id in seen:
            continue
        seen.add(provider_id)
        output.append(
            {
                "id": provider_id,
                "label": item.get("provider_label") or provider_id,
                "is_default": bool(item.get("is_default")),
                "model_count": counts.get(provider_id, 0),
            }
        )
    return sorted(
        output,
        key=lambda item: (not bool(item.get("is_default")), str(item.get("label") or "")),
    )


def _validate_catalog_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("模型目录仅支持 HTTP 或 HTTPS 地址")
    if parsed.username or parsed.password:
        raise ValueError("模型目录地址不能包含用户名或密码")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"metadata.google.internal", "instance-data"}:
        raise ValueError("不允许访问云主机元数据地址")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        raise ValueError("不允许访问链路本地、组播或保留地址")


def _catalog_url(base_url: str | None, api_style: str) -> str:
    base = (base_url or "").rstrip("/")
    if not base:
        base = "https://api.anthropic.com" if api_style == "anthropic" else "https://api.openai.com/v1"
    if base.lower().endswith("/models"):
        return base
    if api_style == "anthropic" and not base.lower().endswith("/v1"):
        return f"{base}/v1/models"
    return f"{base}/models"


def _parse_catalog_models(payload: Any) -> list[tuple[str, str]]:
    items: Any = payload
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or payload.get("items") or []
    if not isinstance(items, list):
        return []
    output: list[tuple[str, str]] = []
    for item in items[:1000]:
        if isinstance(item, str):
            model_id, label = item.strip(), item.strip()
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or item.get("slug") or "").strip()
            label = str(
                item.get("display_name") or item.get("displayName") or item.get("name") or model_id
            ).strip()
        else:
            continue
        if model_id and len(model_id) <= 240:
            output.append((model_id, label or model_id))
    return output


def _request_api_catalog(
    *,
    base_url: str | None,
    api_style: str,
    api_key: str | None,
    provider_id: str,
    provider_label: str,
    source: str,
    timeout: float = 8.0,
) -> tuple[list[dict[str, Any]], str | None, str]:
    endpoint = _catalog_url(base_url, api_style)
    try:
        _validate_catalog_url(endpoint)
    except ValueError as exc:
        return [], str(exc), endpoint
    headers = {"Accept": "application/json"}
    if api_style == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        if api_key:
            headers["x-api-key"] = api_key
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = httpx.get(
            endpoint,
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 4.0)),
            follow_redirects=False,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            return [], "模型目录返回了重定向，出于安全原因未继续访问", endpoint
        if response.status_code in {401, 403}:
            return [], "模型目录认证失败，请检查 API Key 或 Agent Provider 配置", endpoint
        response.raise_for_status()
        pairs = _parse_catalog_models(response.json())
    except httpx.TimeoutException:
        return [], "模型目录连接超时", endpoint
    except (httpx.HTTPError, ValueError):
        return [], "模型目录不可用或返回格式无法识别", endpoint
    if not pairs:
        return [], "接口连接成功，但未返回可识别的模型", endpoint
    return (
        [
            _model_option(
                model_id,
                label=label,
                provider_id=provider_id,
                provider_label=provider_label,
                source=source,
            )
            for model_id, label in pairs
        ],
        None,
        endpoint,
    )


def _codex_home() -> Path:
    configured = os.getenv("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _discover_codex() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    root = _codex_home()
    config = _read_toml(root / "config.toml")
    cache = _read_json(root / "models_cache.json")
    provider_configs = config.get("model_providers") or {}
    if not isinstance(provider_configs, dict):
        provider_configs = {}
    default_provider = str(config.get("model_provider") or "").strip()
    configured_model = str(config.get("model") or "").strip()
    if not default_provider and len(provider_configs) == 1:
        default_provider = str(next(iter(provider_configs)))

    providers: list[dict[str, Any]] = []
    provider_labels: dict[str, str] = {}
    for provider_id, raw in provider_configs.items():
        details = raw if isinstance(raw, dict) else {}
        label = str(details.get("name") or provider_id)
        provider_labels[str(provider_id)] = label
        providers.append(
            {
                "id": str(provider_id),
                "label": label,
                "base_url": details.get("base_url"),
                "is_default": str(provider_id) == default_provider,
            }
        )
    if default_provider and default_provider not in provider_labels:
        provider_labels[default_provider] = default_provider
        providers.append(
            {"id": default_provider, "label": default_provider, "is_default": True}
        )

    auth_providers = [
        str(provider_id)
        for provider_id, raw in provider_configs.items()
        if isinstance(raw, dict) and raw.get("requires_openai_auth") is True
    ]
    cache_provider = auth_providers[0] if auth_providers else default_provider or "codex"
    cache_label = provider_labels.get(cache_provider, "Codex 登录")
    models: list[dict[str, Any]] = []
    cached_items = cache.get("models") if isinstance(cache, dict) else cache
    if isinstance(cached_items, list):
        for item in cached_items:
            if not isinstance(item, dict) or item.get("visibility") == "hide":
                continue
            model_id = str(item.get("slug") or item.get("id") or item.get("model") or "").strip()
            if not model_id:
                continue
            item_provider = str(
                item.get("model_provider") or item.get("provider") or cache_provider
            ).strip()
            models.append(
                _model_option(
                    model_id,
                    label=str(item.get("display_name") or item.get("name") or model_id),
                    provider_id=item_provider,
                    provider_label=provider_labels.get(item_provider, cache_label),
                    source="Codex 本机缓存",
                    configured=model_id == configured_model,
                    is_default=item_provider == default_provider,
                )
            )

    configured_pairs: list[tuple[str, str]] = []
    if configured_model:
        configured_pairs.append((default_provider or cache_provider, configured_model))
    profiles = config.get("profiles") or {}
    if isinstance(profiles, dict):
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            model_id = str(profile.get("model") or "").strip()
            if model_id:
                configured_pairs.append(
                    (str(profile.get("model_provider") or default_provider or cache_provider), model_id)
                )
    for provider_id, model_id in configured_pairs:
        models.append(
            _model_option(
                model_id,
                label=model_id,
                provider_id=provider_id,
                provider_label=provider_labels.get(provider_id, provider_id),
                source="Codex 配置",
                configured=True,
                is_default=provider_id == default_provider,
            )
        )

    warnings: list[str] = []
    for provider_id, raw in list(provider_configs.items())[:8]:
        details = raw if isinstance(raw, dict) else {}
        base_url = details.get("base_url")
        if not isinstance(base_url, str) or details.get("requires_openai_auth") is True:
            continue
        env_key_name = details.get("env_key")
        api_key = os.getenv(env_key_name) if isinstance(env_key_name, str) else None
        hostname = urlparse(base_url).hostname or ""
        is_local = hostname.lower() == "localhost"
        with suppress(ValueError):
            is_local = is_local or ipaddress.ip_address(hostname).is_private
        if not api_key and not is_local:
            warnings.append(f"{provider_labels.get(str(provider_id), provider_id)} 未暴露可用凭据，已识别配置中的模型但未请求远程目录")
            continue
        discovered, warning, _ = _request_api_catalog(
            base_url=base_url,
            api_style="openai",
            api_key=api_key,
            provider_id=str(provider_id),
            provider_label=provider_labels.get(str(provider_id), str(provider_id)),
            source="Codex Provider API",
            timeout=5.0,
        )
        for item in discovered:
            item["is_default"] = str(provider_id) == default_provider
        models.extend(discovered)
        if warning:
            warnings.append(f"{provider_labels.get(str(provider_id), provider_id)}：{warning}")

    if not models:
        warnings.append("未找到 Codex 模型缓存；可刷新 Codex 登录状态或改用手动输入")
    return models, providers, warnings


def _discover_claude() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    configured_root = os.getenv("CLAUDE_CONFIG_DIR")
    root = Path(configured_root).expanduser() if configured_root else Path.home() / ".claude"
    settings = _read_json(root / "settings.json")
    models: list[dict[str, Any]] = []
    provider_id = "claude-code"
    provider_label = "Claude Code 配置"
    configured_models: set[str] = set()
    if isinstance(settings, dict):
        direct_model = settings.get("model")
        if isinstance(direct_model, str) and direct_model.strip():
            configured_models.add(direct_model.strip())
        environment = settings.get("env") or {}
        if isinstance(environment, dict):
            for key, value in environment.items():
                key_upper = str(key).upper()
                if (
                    isinstance(value, str)
                    and value.strip()
                    and "ANTHROPIC" in key_upper
                    and key_upper.endswith("MODEL")
                ):
                    configured_models.add(value.strip())
    for model_id in sorted(configured_models):
        models.append(
            _model_option(
                model_id,
                label=model_id,
                provider_id=provider_id,
                provider_label=provider_label,
                source="Claude Code 配置",
                configured=True,
                is_default=True,
            )
        )
    aliases = (
        ("fable", "Fable（Claude Code 最新别名）"),
        ("sonnet", "Sonnet（Claude Code 别名）"),
        ("opus", "Opus（Claude Code 别名）"),
        ("haiku", "Haiku（Claude Code 别名）"),
    )
    for alias, label in aliases:
        models.append(
            _model_option(
                alias,
                label=label,
                provider_id=provider_id,
                provider_label=provider_label,
                source="Claude Code 内置别名",
                configured=alias == "fable",
                is_default=True,
            )
        )
    warnings = [] if configured_models else ["未发现自定义 Claude Code 模型映射，已提供内置模型别名"]
    return models, [{"id": provider_id, "label": provider_label, "is_default": True}], warnings


def _discover_opencode(executable: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    if not executable:
        return [], ["OpenCode 未安装，暂时只能手动输入模型 ID"]
    try:
        result = subprocess.run(
            [executable, "models"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], ["OpenCode 模型目录读取失败，仍可手动输入模型 ID"]
    configured_providers: set[str] | None = None
    try:
        auth_result = subprocess.run(
            [executable, "auth", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
        if auth_result.returncode == 0:
            configured_providers = set()
            for raw_line in (auth_result.stdout or "").splitlines():
                line = _ANSI_ESCAPE.sub("", raw_line).strip(" T|•—-\t")
                if not line.lower().endswith(" api"):
                    continue
                label = line[:-4].strip()
                normalized = re.sub(r"[^a-z0-9]", "", label.lower())
                if normalized:
                    configured_providers.add(normalized)
    except (OSError, subprocess.TimeoutExpired):
        pass
    models: list[dict[str, Any]] = []
    for raw_line in (result.stdout or "").splitlines():
        line = _ANSI_ESCAPE.sub("", raw_line).strip()
        if not _MODEL_LINE.fullmatch(line):
            continue
        provider_id = line.split("/", 1)[0]
        provider_key = re.sub(r"[^a-z0-9]", "", provider_id.lower())
        configured = configured_providers is not None and any(
            provider_key in item or item in provider_key for item in configured_providers
        )
        models.append(
            _model_option(
                line,
                label=line,
                provider_id=provider_id,
                provider_label=provider_id,
                source="OpenCode 模型目录",
                configured=configured,
                is_default=True,
            )
        )
    if not models:
        return [], ["OpenCode 未返回可识别的模型目录，仍可手动输入模型 ID"]
    warnings = []
    if configured_providers is not None and not any(item["configured"] for item in models):
        warnings.append("OpenCode 返回了模型目录，但未检测到与目录匹配的已认证 Provider")
    return models, warnings


def _discover_reasonix(
    executable: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not executable:
        return [], [], ["Reasonix CLI 未安装，无法读取 Provider 配置"]
    try:
        result = subprocess.run(
            [executable, "doctor", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], [], ["Reasonix doctor 读取失败，仍可手动输入 Provider 名称"]
    output = (result.stdout or "").strip()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        start, end = output.find("{"), output.rfind("}")
        if start < 0 or end <= start:
            return [], [], ["Reasonix doctor 未返回可识别的 JSON"]
        try:
            payload = json.loads(output[start : end + 1])
        except json.JSONDecodeError:
            return [], [], ["Reasonix doctor 未返回可识别的 JSON"]
    raw_providers = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(raw_providers, list):
        return [], [], ["Reasonix 配置中没有可识别的 Provider"]
    models: list[dict[str, Any]] = []
    providers: list[dict[str, Any]] = []
    for raw in raw_providers[:100]:
        if not isinstance(raw, dict):
            continue
        provider_name = str(raw.get("name") or "").strip()
        if not provider_name:
            continue
        raw_models = raw.get("models") or []
        model_names = (
            [str(item).strip() for item in raw_models if str(item).strip()]
            if isinstance(raw_models, list)
            else []
        )
        configured_model = str(raw.get("model") or "").strip()
        if configured_model and configured_model not in model_names:
            model_names.insert(0, configured_model)
        model_label = ", ".join(model_names[:3]) or configured_model or provider_name
        is_default = bool(raw.get("is_default"))
        configured = bool(raw.get("key_present"))
        models.append(
            _model_option(
                provider_name,
                label=f"{model_label}（{provider_name}）",
                provider_id=provider_name,
                provider_label=provider_name,
                source="Reasonix doctor Provider 配置",
                configured=configured,
                is_default=is_default,
            )
        )
        providers.append(
            {
                "id": provider_name,
                "label": provider_name,
                "is_default": is_default,
            }
        )
    warnings = [] if models else ["Reasonix 配置中没有可识别的 Provider"]
    return models, providers, warnings


def _discover_headless_agent(
    executable: str | None, *, label: str, source: str
) -> tuple[list[dict[str, Any]], list[str]]:
    models: list[dict[str, Any]] = []
    if executable:
        for suffix in (
            ("models", "--json"),
            ("models", "list", "--json"),
            ("models",),
            ("--list-models",),
        ):
            try:
                result = subprocess.run(
                    [executable, *suffix],
                    capture_output=True,
                    text=True,
                    timeout=12,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode != 0:
                continue
            text = _ANSI_ESCAPE.sub("", result.stdout or "").strip()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            items = (
                payload.get("models") or payload.get("data") or []
                if isinstance(payload, dict)
                else payload
                if isinstance(payload, list)
                else []
            )
            for item in items:
                model_id = str(item.get("id") or item.get("name") or "") if isinstance(item, dict) else str(item)
                if model_id:
                    models.append(
                        _model_option(
                            model_id,
                            label=str(item.get("label") or item.get("name") or model_id)
                            if isinstance(item, dict)
                            else model_id,
                            provider_id="default",
                            provider_label=label,
                            source=source,
                            configured=True,
                            is_default=not models,
                        )
                    )
            if models:
                break
    if models:
        return models, []
    return [
        _model_option(
            "auto",
            label=f"{label} 当前登录配置",
            provider_id="default",
            provider_label=label,
            source=f"{source}（CLI 未公开稳定模型目录）",
            configured=bool(executable),
            is_default=True,
        )
    ], [f"{label} 未返回稳定模型目录；选择“当前登录配置”时由 Agent 自身决定模型"]


def _cursor_text_models(text: str) -> list[tuple[str, str]]:
    """Parse Cursor's human-readable ``agent models`` output defensively."""
    ignored = {
        "available",
        "available model",
        "available models",
        "current",
        "default",
        "id",
        "model",
        "models",
        "name",
    }
    parsed: list[tuple[str, str]] = []
    for raw_line in _ANSI_ESCAPE.sub("", text).splitlines():
        line = raw_line.strip().strip("│|")
        line = re.sub(r"^[*+>✓✔•●○\-]+\s*", "", line).strip()
        if not line or line.lower().rstrip(":") in ignored:
            continue
        match = re.match(
            r"^(?P<id>[A-Za-z0-9][A-Za-z0-9._:/+-]*)"
            r"(?:\s*(?:\||\t|\s+-\s+|\s{2,})\s*(?P<label>.+))?$",
            line,
        )
        if not match:
            continue
        model_id = match.group("id").strip()
        label = (match.group("label") or model_id).strip().strip("│|")
        if model_id.lower() in ignored or label.lower().rstrip(":") in ignored:
            continue
        parsed.append((model_id, label))
    return parsed


def _discover_cursor(executable: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    models: list[dict[str, Any]] = []
    if executable:
        try:
            result = subprocess.run(
                [executable, "models"],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            text = _ANSI_ESCAPE.sub("", result.stdout or "").strip()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            items = (
                payload.get("models") or payload.get("data") or []
                if isinstance(payload, dict)
                else payload
                if isinstance(payload, list)
                else []
            )
            parsed: list[tuple[str, str]] = []
            for item in items:
                if isinstance(item, dict):
                    model_id = str(item.get("id") or item.get("name") or "").strip()
                    label = str(item.get("label") or item.get("name") or model_id).strip()
                else:
                    model_id = str(item).strip()
                    label = model_id
                if model_id:
                    parsed.append((model_id, label))
            if not parsed:
                parsed = _cursor_text_models(text)
            for model_id, model_label in parsed:
                models.append(
                    _model_option(
                        model_id,
                        label=model_label,
                        provider_id="default",
                        provider_label="Cursor Agent",
                        source="Cursor Agent CLI · 账号模型目录",
                        configured=True,
                        is_default=model_id.lower() == "auto" or not models,
                    )
                )
    if models:
        return models, []
    return [
        _model_option(
            "auto",
            label="Cursor 当前账号自动模型",
            provider_id="default",
            provider_label="Cursor Agent",
            source="Cursor Agent CLI · 自动选择",
            configured=bool(executable),
            is_default=True,
        )
    ], ["Cursor Agent 未返回账号模型目录；选择“自动模型”时由 Cursor 自行决定模型"]


def discover_models(
    *,
    source: str,
    provider: str = "openai-compatible",
    base_url: str | None = None,
    api_style: str = "openai",
    api_key: str | None = None,
) -> dict[str, Any]:
    if source not in SOURCE_META:
        raise ValueError("unsupported_model_source")
    source_label, executable = SOURCE_META[source]
    if source == "api":
        provider_id = provider.strip() or "openai-compatible"
        models, warning, endpoint = _request_api_catalog(
            base_url=base_url,
            api_style=api_style,
            api_key=api_key,
            provider_id=provider_id,
            provider_label=provider_id,
            source="API 模型目录",
        )
        models = _deduplicate_models(models)
        providers = _providers_for_models(
            [{"id": provider_id, "label": provider_id, "is_default": True}], models
        )
        return {
            "source": source,
            "source_label": source_label,
            "capability": {"installed": True, "version": "HTTP API", "endpoint": endpoint},
            "models": models,
            "providers": providers,
            "warnings": [warning] if warning else [],
        }

    capability = native_cli_status(executable)
    providers: list[dict[str, Any]] = []
    warnings: list[str] = []
    if source == "codex-cli":
        models, providers, warnings = _discover_codex()
    elif source == "claude-code":
        models, providers, warnings = _discover_claude()
    elif source == "opencode-cli":
        models, warnings = _discover_opencode(capability.get("executable"))
    elif source == "reasonix-cli":
        models, providers, warnings = _discover_reasonix(capability.get("executable"))
    elif source == "kimi-code":
        models, warnings = _discover_headless_agent(
            capability.get("executable"), label="Kimi Code", source="Kimi Code CLI"
        )
    elif source == "qoder-cli":
        models, warnings = _discover_headless_agent(
            capability.get("executable"), label="Qoder", source="Qoder CLI"
        )
    elif source == "cursor-cli":
        models, warnings = _discover_cursor(capability.get("executable"))
    else:
        models = []
        warnings = [f"{source_label} 当前未提供稳定的模型目录命令，请手动输入模型 ID"]
    if capability.get("warning"):
        warnings.insert(0, str(capability["warning"]))
    if not capability.get("installed"):
        detail = capability.get("error") or f"本机尚未检测到 {source_label}"
        install = capability.get("install_command")
        warning = f"{detail}，保存后需安装对应 CLI 才能运行"
        if install:
            warning += f"；安装命令：{install}"
        warnings.insert(0, warning)
    models = _deduplicate_models(models)
    providers = _providers_for_models(providers, models)
    return {
        "source": source,
        "source_label": source_label,
        "capability": capability,
        "models": models,
        "providers": providers,
        "warnings": warnings,
    }
