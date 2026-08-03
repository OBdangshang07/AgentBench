from __future__ import annotations

import json
import math
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

import jsonschema

from .execution import DockerExecutor, Workspace, WorkspaceViolation, safe_workspace_path

JudgeCallback = Callable[[dict[str, Any], float], "ValidationResult"]

QUALITY_WEIGHT = 94.0
TIME_WEIGHT = 3.0
STEP_WEIGHT = 2.0
TOKEN_WEIGHT = 1.0


@dataclass(slots=True)
class ValidationResult:
    validator_type: str
    weight: float
    score: float
    status: str
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScoreResult:
    score: float | None
    status: str
    components: list[ValidationResult]
    dimensions: list[ValidationResult]


class ScoringEngine:
    def __init__(self, docker: DockerExecutor):
        self.docker = docker

    def score(
        self,
        *,
        definition: dict[str, Any],
        final_answer: str,
        workspace: Workspace,
        steps: int,
        duration_ms: int,
        tokens_input: int,
        tokens_output: int,
        judge_callback: JudgeCallback | None = None,
    ) -> ScoreResult:
        results: list[ValidationResult] = []
        for validator_index, validator in enumerate(definition.get("validators") or []):
            kind = str(validator["type"])
            weight = float(validator["weight"])
            config = validator.get("config") or {}
            if kind == "ai_rubric":
                if judge_callback is None:
                    produced = [
                        ValidationResult(
                            kind,
                            weight,
                            0,
                            "needs_review",
                            {"reason": "No judge model or judge Agent is configured"},
                        )
                    ]
                else:
                    produced = [judge_callback(config, weight)]
            elif kind == "command_metrics":
                produced = self._validate_command_metrics(
                    weight, config, workspace, definition
                )
            else:
                produced = [
                    self._validate(kind, weight, config, final_answer, workspace, definition)
                ]
            for item in produced:
                item.evidence = {
                    **item.evidence,
                    "validator_index": validator_index,
                    "critical": bool(config.get("critical")),
                    "critical_min_score": float(config.get("critical_min_score", 100)),
                }
            results.extend(produced)

        declared_weight = sum(item.weight for item in results)
        if declared_weight:
            quality_scale = QUALITY_WEIGHT / declared_weight
            for item in results:
                item.evidence = {
                    **item.evidence,
                    "declared_weight": item.weight,
                    "scoring_profile": "balanced-v2",
                }
                item.weight = round(item.weight * quality_scale, 4)

        limits = definition.get("limits") or {}
        time_target_seconds = max(
            1,
            int(limits.get("time_target_seconds", limits.get("timeout_seconds", 300))),
        )
        duration_seconds = max(0.0, duration_ms / 1000.0)
        time_ratio = duration_seconds / time_target_seconds
        time_score = (
            100.0
            if time_ratio <= 1.0
            else max(50.0, 100.0 - 12.5 * math.log2(time_ratio))
        )
        results.append(
            ValidationResult(
                "time_efficiency",
                TIME_WEIGHT,
                round(time_score, 2),
                "passed",
                {
                    "duration_ms": max(0, duration_ms),
                    "time_target_seconds": time_target_seconds,
                    "elapsed_multiple": round(time_ratio, 3),
                    "target_exceeded": time_ratio > 1.0,
                    "note": "超过建议时间后继续运行，仅按对数曲线轻微扣分"
                    if time_ratio > 1.0
                    else "在建议时间内完成",
                    "scoring_profile": "balanced-v2",
                },
            )
        )

        max_steps = max(1, int(limits.get("max_steps", 40)))
        step_ratio = min(1.0, max(0, steps) / max_steps)
        step_score = max(60.0, 100.0 - step_ratio * 40.0)
        results.append(
            ValidationResult(
                "step_efficiency",
                STEP_WEIGHT,
                round(step_score, 2),
                "passed",
                {
                    "steps": max(0, steps),
                    "max_steps": max_steps,
                    "budget_used_percent": round(step_ratio * 100, 2),
                    "scoring_profile": "balanced-v2",
                },
            )
        )
        token_budget = max(0, int(limits.get("token_budget", 0)))
        total_tokens = max(0, tokens_input) + max(0, tokens_output)
        tokens_reported = total_tokens > 0 and token_budget > 0
        if tokens_reported:
            token_ratio = min(1.0, total_tokens / token_budget)
            if token_ratio <= 0.25:
                token_score = 100.0
            else:
                token_score = max(10.0, 100.0 - ((token_ratio - 0.25) / 0.75) * 90.0)
        else:
            token_ratio = None
            token_score = 50.0
        results.append(
            ValidationResult(
                "token_efficiency",
                TOKEN_WEIGHT,
                round(token_score, 2),
                "passed" if tokens_reported else "partial",
                {
                    "tokens_input": max(0, tokens_input),
                    "tokens_output": max(0, tokens_output),
                    "total_tokens": total_tokens,
                    "token_budget": token_budget or None,
                    "budget_used_percent": round(token_ratio * 100, 2)
                    if token_ratio is not None
                    else None,
                    "reported": tokens_reported,
                    "note": None
                    if tokens_reported
                    else "Token 未上报或任务未声明预算，使用中性分",
                    "scoring_profile": "balanced-v2",
                },
            )
        )
        dimensions = self._dimensions(results)
        if any(item.status == "environment_unavailable" for item in results):
            return ScoreResult(None, "environment_unavailable", results, dimensions)
        if any(item.status == "needs_review" for item in results):
            return ScoreResult(None, "needs_review", results, dimensions)
        total_weight = sum(item.weight for item in results)
        total = (
            sum(item.score * item.weight for item in results) / total_weight if total_weight else 0
        )
        return ScoreResult(round(total, 2), "scored", results, dimensions)

    def _validate(
        self,
        kind: str,
        weight: float,
        config: dict[str, Any],
        final_answer: str,
        workspace: Workspace,
        definition: dict[str, Any],
    ) -> ValidationResult:
        try:
            if kind == "exact_match":
                expected = str(config.get("expected", ""))
                actual = final_answer.strip()
                score = self._text_similarity(expected, actual, partial_cap=60.0)
                return self._graded(
                    kind, weight, score, {"expected": expected, "actual": actual}
                )
            if kind == "contains":
                expected = str(config.get("text", ""))
                score = (
                    100.0
                    if expected in final_answer
                    else self._text_similarity(expected, final_answer, partial_cap=70.0)
                )
                return self._graded(kind, weight, score, {"expected_text": expected})
            if kind == "regex":
                pattern = str(config.get("pattern", ""))
                passed = re.search(pattern, final_answer, flags=re.MULTILINE) is not None
                return self._boolean(kind, weight, passed, {"pattern": pattern})
            if kind == "json_schema":
                schema = config.get("schema") or {}
                value, strict_json = self._parse_json(final_answer)
                errors = sorted(
                    jsonschema.Draft202012Validator(schema).iter_errors(value),
                    key=lambda item: list(item.absolute_path),
                )
                if not errors and strict_json:
                    return self._graded(kind, weight, 100.0, {"valid": True})
                if not errors:
                    return self._graded(
                        kind,
                        weight,
                        85.0,
                        {"valid": True, "strict_json": False, "reason": "JSON 包含额外包裹文本"},
                    )
                penalty = sum(self._schema_error_penalty(error.validator) for error in errors)
                score = min(90.0, max(0.0, 100.0 - penalty))
                return self._graded(
                    kind,
                    weight,
                    score,
                    {
                        "valid": False,
                        "errors": [
                            {
                                "path": ".".join(str(part) for part in error.absolute_path),
                                "rule": error.validator,
                                "message": error.message,
                            }
                            for error in errors[:12]
                        ],
                    },
                )
            if kind == "file_exists":
                path = str(config["path"])
                passed = safe_workspace_path(workspace.root, path).is_file()
                return self._boolean(kind, weight, passed, {"path": path})
            if kind in {"file_content", "file_contains"}:
                path = str(config["path"])
                actual = workspace.read_file(path)
                if kind == "file_content":
                    expected = str(config.get("expected", ""))
                    score = self._text_similarity(expected, actual, partial_cap=92.0)
                else:
                    expected = str(config.get("text", ""))
                    score = (
                        100.0
                        if expected in actual
                        else self._text_similarity(expected, actual, partial_cap=70.0)
                    )
                return self._graded(
                    kind,
                    weight,
                    score,
                    {"path": path, "expected": expected, "actual_preview": actual[:1000]},
                )
            if kind == "json_file":
                path = str(config["path"])
                actual_text = workspace.read_file(path).lstrip("\ufeff")
                actual = json.loads(actual_text)
                expected = config.get("expected")
                score, field_scores = self._json_similarity(expected, actual)
                return self._graded(
                    kind,
                    weight,
                    score,
                    {
                        "path": path,
                        "field_scores": field_scores,
                        "expected_keys": sorted(expected) if isinstance(expected, dict) else None,
                        "actual_keys": sorted(actual) if isinstance(actual, dict) else None,
                    },
                )
            if kind == "forbidden_paths":
                patterns = [str(item) for item in config.get("paths") or []]
                matches = workspace.matches_any(patterns)
                return self._boolean(
                    kind, weight, not matches, {"patterns": patterns, "matches": matches}
                )
            if kind == "command":
                limits = definition.get("limits") or {}
                result = self._command_result(workspace, config, limits)
                if result.error_code == "sandbox_unavailable":
                    return ValidationResult(
                        kind, weight, 0, "environment_unavailable", result.as_dict()
                    )
                return self._boolean(kind, weight, result.ok, result.as_dict())
            return ValidationResult(kind, weight, 0, "error", {"reason": "Unknown validator"})
        except (
            OSError,
            KeyError,
            ValueError,
            json.JSONDecodeError,
            jsonschema.ValidationError,
            WorkspaceViolation,
        ) as exc:
            return ValidationResult(kind, weight, 0, "failed", {"error": str(exc)})

    def _command_result(
        self,
        workspace: Workspace,
        config: dict[str, Any],
        limits: dict[str, Any],
    ):
        private_files = config.get("private_files")
        private_root: str | None = None
        if private_files is not None and not isinstance(private_files, dict):
            raise ValueError("private_files must be an object")
        try:
            command = str(config["command"])
            if private_files:
                private_root = f".agentbench-private-{uuid.uuid4().hex}"
                for relative, content in private_files.items():
                    if not isinstance(relative, str) or not isinstance(content, str):
                        raise ValueError("Private validator files must contain text paths")
                    workspace.write_file(f"{private_root}/{relative}", content)
                command = command.replace("{private_root}", private_root)
            return self.docker.run(
                workspace,
                command,
                str(limits.get("docker_image", "python:3.12-alpine")),
                timeout=min(int(limits.get("validator_timeout_seconds", 180)), 600),
                network=str(limits.get("network", "disabled")),
            )
        finally:
            if private_root:
                target = safe_workspace_path(workspace.root, private_root)
                if target.is_dir():
                    shutil.rmtree(target)

    def _validate_command_metrics(
        self,
        weight: float,
        config: dict[str, Any],
        workspace: Workspace,
        definition: dict[str, Any],
    ) -> list[ValidationResult]:
        """Run a private validator that reports continuous, independently weighted metrics.

        The validator protocol is a single stdout line beginning with
        ``AGENTBENCH_METRICS=`` followed by a JSON object. Private validators are
        expected to catch candidate failures and still emit the protocol line;
        absence of the line therefore indicates a broken validator/bootstrap,
        not a consumed model attempt.
        """
        limits = definition.get("limits") or {}
        result = self._command_result(workspace, config, limits)
        evidence = result.as_dict()
        if result.error_code == "sandbox_unavailable":
            return [
                ValidationResult(
                    "validator_platform", weight, 0, "environment_unavailable", evidence
                )
            ]

        matches = re.findall(r"(?m)^AGENTBENCH_METRICS=(\{.*\})\s*$", result.stdout)
        if not matches:
            declared = config.get("metrics") or []
            if result.error_code == "command_timeout" and isinstance(declared, list) and declared:
                declared_weight = sum(
                    max(0.0, float(item.get("weight", 0))) for item in declared
                )
                if declared_weight > 0:
                    return [
                        ValidationResult(
                            str(item.get("name") or item["key"]),
                            weight
                            * max(0.0, float(item.get("weight", 0)))
                            / declared_weight,
                            0,
                            "failed",
                            {
                                **evidence,
                                "metric_key": str(item["key"]),
                                "reason": "候选实现导致私有验证超时",
                            },
                        )
                        for item in declared
                    ]
            return [
                ValidationResult(
                    "validator_platform",
                    weight,
                    0,
                    "environment_unavailable",
                    {
                        **evidence,
                        "error_code": "validator_platform_error",
                        "reason": "私有验证器未返回 AgentBench 指标协议；本次不消耗 Ultra 轮次",
                    },
                )
            ]
        try:
            payload = json.loads(matches[-1])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return [
                ValidationResult(
                    "validator_platform",
                    weight,
                    0,
                    "environment_unavailable",
                    {
                        **evidence,
                        "error_code": "validator_platform_error",
                        "reason": f"私有验证器指标协议无效: {exc}",
                    },
                )
            ]

        declared = config.get("metrics") or []
        metric_values = payload.get("metrics") if isinstance(payload, dict) else None
        if not isinstance(declared, list) or not declared or not isinstance(metric_values, dict):
            return [
                ValidationResult(
                    "validator_platform",
                    weight,
                    0,
                    "environment_unavailable",
                    {
                        **evidence,
                        "error_code": "validator_platform_error",
                        "reason": "私有验证器指标声明或结果缺失",
                    },
                )
            ]
        declared_weight = sum(max(0.0, float(item.get("weight", 0))) for item in declared)
        if declared_weight <= 0:
            raise ValueError("command_metrics weights must be positive")

        output: list[ValidationResult] = []
        detail = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        for item in declared:
            key = str(item["key"])
            name = str(item.get("name") or key)
            raw_value = metric_values.get(key, 0)
            try:
                score = min(100.0, max(0.0, float(raw_value)))
            except (TypeError, ValueError):
                score = 0.0
            metric_weight = weight * max(0.0, float(item.get("weight", 0))) / declared_weight
            output.append(
                ValidationResult(
                    name,
                    metric_weight,
                    round(score, 2),
                    "passed" if score == 100 else "partial" if score > 0 else "failed",
                    {
                        "metric_key": key,
                        "detail": detail.get(key),
                        "validator_stdout": result.stdout[-4000:],
                        "validator_stderr": result.stderr[-4000:],
                        "validator_exit_code": result.exit_code,
                    },
                )
            )
        return output

    @staticmethod
    def _boolean(
        kind: str, weight: float, passed: bool, evidence: dict[str, Any]
    ) -> ValidationResult:
        return ValidationResult(
            kind, weight, 100.0 if passed else 0.0, "passed" if passed else "failed", evidence
        )

    @staticmethod
    def _graded(
        kind: str, weight: float, score: float, evidence: dict[str, Any]
    ) -> ValidationResult:
        value = round(min(100.0, max(0.0, score)), 2)
        status = "passed" if value == 100.0 else "partial" if value > 0 else "failed"
        return ValidationResult(kind, weight, value, status, evidence)

    @staticmethod
    def _text_similarity(expected: str, actual: str, *, partial_cap: float) -> float:
        if actual == expected:
            return 100.0
        if not expected or not actual:
            return 0.0
        normalized_expected = expected.replace("\r\n", "\n").strip()
        normalized_actual = actual.replace("\r\n", "\n").strip()
        if normalized_expected == normalized_actual:
            return min(98.0, partial_cap)
        character_ratio = SequenceMatcher(None, normalized_expected, normalized_actual).ratio()
        expected_tokens = re.findall(r"[\w.-]+", normalized_expected.lower())
        actual_tokens = re.findall(r"[\w.-]+", normalized_actual.lower())
        expected_counts: dict[str, int] = {}
        actual_counts: dict[str, int] = {}
        for token in expected_tokens:
            expected_counts[token] = expected_counts.get(token, 0) + 1
        for token in actual_tokens:
            actual_counts[token] = actual_counts.get(token, 0) + 1
        overlap = sum(
            min(count, actual_counts.get(token, 0)) for token, count in expected_counts.items()
        )
        precision = overlap / len(actual_tokens) if actual_tokens else 0.0
        recall = overlap / len(expected_tokens) if expected_tokens else 0.0
        token_f1 = (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
        return round(min(partial_cap, max(character_ratio, token_f1) * partial_cap), 2)

    @staticmethod
    def _parse_json(text: str) -> tuple[Any, bool]:
        cleaned = text.strip().lstrip("\ufeff")
        try:
            return json.loads(cleaned), True
        except json.JSONDecodeError as strict_error:
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.I)
            if match:
                return json.loads(match.group(1)), False
            object_start = min(
                (index for index in (cleaned.find("{"), cleaned.find("[")) if index >= 0),
                default=-1,
            )
            if object_start >= 0:
                decoder = json.JSONDecoder()
                value, _ = decoder.raw_decode(cleaned[object_start:])
                return value, False
            raise strict_error

    @staticmethod
    def _schema_error_penalty(validator: Any) -> float:
        return {
            "required": 18.0,
            "type": 24.0,
            "const": 18.0,
            "enum": 18.0,
            "additionalProperties": 8.0,
            "minItems": 12.0,
            "maxItems": 12.0,
            "minLength": 10.0,
            "maxLength": 10.0,
        }.get(str(validator), 14.0)

    @classmethod
    def _json_similarity(cls, expected: Any, actual: Any) -> tuple[float, dict[str, float]]:
        if expected == actual:
            if isinstance(expected, dict):
                return 100.0, {str(key): 100.0 for key in expected}
            return 100.0, {}
        if isinstance(expected, dict) and isinstance(actual, dict):
            keys = sorted(set(expected) | set(actual), key=str)
            if not keys:
                return 100.0, {}
            field_scores: dict[str, float] = {}
            for key in keys:
                if key not in expected or key not in actual:
                    field_scores[str(key)] = 0.0
                    continue
                field_scores[str(key)] = cls._json_value_score(expected[key], actual[key])
            return round(sum(field_scores.values()) / len(field_scores), 2), field_scores
        return cls._json_value_score(expected, actual), {}

    @classmethod
    def _json_value_score(cls, expected: Any, actual: Any) -> float:
        if expected == actual:
            return 100.0
        if isinstance(expected, bool) or isinstance(actual, bool):
            return 0.0
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            denominator = max(abs(float(expected)), 1.0)
            closeness = max(0.0, 1.0 - abs(float(expected) - float(actual)) / denominator)
            return round(min(80.0, closeness * 80.0), 2)
        if isinstance(expected, str) and isinstance(actual, str):
            return round(
                min(80.0, SequenceMatcher(None, expected.lower(), actual.lower()).ratio() * 80.0),
                2,
            )
        if isinstance(expected, dict) and isinstance(actual, dict):
            return cls._json_similarity(expected, actual)[0]
        if isinstance(expected, list) and isinstance(actual, list):
            total = max(len(expected), len(actual))
            if not total:
                return 100.0
            scores = [
                cls._json_value_score(expected[index], actual[index])
                if index < len(expected) and index < len(actual)
                else 0.0
                for index in range(total)
            ]
            return round(sum(scores) / total, 2)
        return 0.0

    @staticmethod
    def _dimensions(results: list[ValidationResult]) -> list[ValidationResult]:
        groups = {
            "objective_quality": [
                item
                for item in results
                if item.validator_type
                not in {"ai_rubric", "time_efficiency", "step_efficiency", "token_efficiency"}
            ],
            "judge_quality": [item for item in results if item.validator_type == "ai_rubric"],
            "time_efficiency": [
                item for item in results if item.validator_type == "time_efficiency"
            ],
            "step_efficiency": [
                item for item in results if item.validator_type == "step_efficiency"
            ],
            "token_efficiency": [
                item for item in results if item.validator_type == "token_efficiency"
            ],
        }
        dimensions: list[ValidationResult] = []
        for name, items in groups.items():
            weight = sum(item.weight for item in items)
            if not weight:
                continue
            score = sum(item.score * item.weight for item in items) / weight
            status = (
                "needs_review"
                if any(item.status == "needs_review" for item in items)
                else "environment_unavailable"
                if any(item.status == "environment_unavailable" for item in items)
                else "passed"
                if score == 100
                else "partial"
                if score > 0
                else "failed"
            )
            dimensions.append(
                ValidationResult(
                    name,
                    round(weight, 4),
                    round(score, 2),
                    status,
                    {
                        "components": [item.validator_type for item in items],
                        "contribution": round(score * weight / 100.0, 2),
                        "scoring_profile": "balanced-v2",
                    },
                )
            )
        return dimensions
