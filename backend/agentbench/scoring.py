from __future__ import annotations

import json
import keyword
import math
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import jsonschema

from .execution import (
    CommandResult,
    DockerExecutor,
    Workspace,
    WorkspaceViolation,
    safe_workspace_path,
)
from .private_validators import PrivateValidatorError, PrivateValidatorStore

JudgeCallback = Callable[[dict[str, Any], float], "ValidationResult"]

QUALITY_WEIGHT = 94.0
TIME_WEIGHT = 3.0
STEP_WEIGHT = 2.0
TOKEN_WEIGHT = 1.0
CURRENT_SCORING_PROFILE = "balanced-v3"
SUPPORTED_SCORING_PROFILES = {"balanced-v2", CURRENT_SCORING_PROFILE}


def _extract_structured_answer(
    raw: str, required_fields: set[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read a structured final answer without confusing presentation with correctness.

    Native coding Agents frequently add a short explanation before the requested JSON or
    wrap it in a Markdown code fence.  The validator still requires the declared fields
    and applies the original literal/symbolic checks; this helper only recovers the JSON
    object from that presentation layer.
    """

    text = raw.lstrip("\ufeff").strip()
    try:
        strict = json.loads(text)
    except json.JSONDecodeError:
        strict = None
    if isinstance(strict, dict) and required_fields.issubset(strict):
        return strict, {
            "mode": "strict_json",
            "format_compliant": True,
            "embedded": False,
        }

    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for match in re.finditer(r"\{", text):
        try:
            value, consumed = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and required_fields.issubset(value):
            candidates.append((match.start(), match.start() + consumed, value))
    if not candidates:
        raise ValueError(
            "No JSON object containing the required answer fields was found"
        )

    start, end, value = candidates[-1]
    before_fence = text.rfind("```", 0, start)
    after_fence = text.find("```", end)
    fenced = before_fence >= 0 and after_fence >= 0
    return value, {
        "mode": "json_code_fence" if fenced else "embedded_json",
        "format_compliant": False,
        "embedded": True,
        "offset": start,
        "warning": "答案 JSON 外包含说明文字；数学正确性照常评分，格式单独留痕",
    }


def _normalize_symbolic_candidate(
    candidate: Any, *, prefer_scenario_scalar: bool = False
) -> str:
    """Normalize common human math notation before strict symbolic comparison."""

    text = re.sub(r"[\x00-\x1f\x7f]", "", str(candidate)).strip().strip("`$")
    text = text.translate(
        str.maketrans(
            {
                "（": "(",
                "）": ")",
                "［": "[",
                "］": "]",
                "｛": "{",
                "｝": "}",
                "₀": "0",
                "₁": "1",
                "₂": "2",
                "₃": "3",
                "₄": "4",
                "₅": "5",
                "₆": "6",
                "₇": "7",
                "₈": "8",
                "₉": "9",
            }
        )
    )
    # A scalar result field may include both the general formula and a later,
    # explicitly labelled specialization, for example
    # ``Phi(H)=...; 给定数据 H=3 时为 -90pi-18sqrt(3)pi``.  When the validator
    # declares no variables, the specialization is the value being anchored.
    # Requiring both the scenario marker and ``时为``/``结果为`` keeps this
    # narrow: an ordinary formula field or an incidental equality is untouched.
    scenario_scalars: list[re.Match[str]] = []
    if prefer_scenario_scalar:
        scenario_scalars.extend(
            re.finditer(
                r"(?:给定(?:数据)?|本次(?:数据)?|本次数值)"
                r"[^；;。\r\n]{0,180}?"
                r"(?:时|结果|数值(?:核验)?|通量)\s*(?:为|=)\s*"
                r"([^；;。\r\n]+)",
                text,
            )
        )
        # Hidden-parameter questions often use a result field for both the
        # general classification and a requested numerical specialization:
        # ``...; α=3 时 E[S]=100``.  Match only that explicit parameter/time
        # structure in a validator-declared constant field; a generic equality
        # or a variable-valued formula cannot take this path.
        scenario_scalars.extend(
            re.finditer(
                r"(?:α|alpha)\s*=\s*[+-]?\d+(?:\.\d+)?\s*时"
                r"[^；;。\r\n]{0,120}?(?:为|=)\s*([^；;。\r\n]+)",
                text,
                flags=re.I,
            )
        )
    if scenario_scalars:
        text = max(scenario_scalars, key=lambda match: match.start()).group(1).strip()

    # A structured coefficient field may explain a vector using an auxiliary
    # scalar, for example ``β=c(1,1,1)^T，其中 c=-x-y+2z``.  In that narrow
    # presentation, the explicitly introduced scalar is the field value.  Greek
    # coordinate/vector assignments are intentionally not matched here.
    scalar_definitions = list(
        re.finditer(
            r"(?:其中|式中|where)\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
            r"([^，,；;。\r\n]+)",
            text,
            flags=re.I,
        )
    )
    if scenario_scalars:
        pass
    elif scalar_definitions:
        text = scalar_definitions[-1].group(2).strip()
    else:
        # A structured scalar field may lead with its ordinary mathematical
        # label and then append a proof summary, e.g. ``K=(pi-2log(2))/10；...``.
        # The labelled value before the first sentence delimiter is
        # unambiguous; the appended reasoning is evaluated by the rubric.
        leading_assignment = re.match(
            r"\s*[A-Za-z_][A-Za-z0-9_]*(?:\s*\([^()]*\))?\s*=\s*"
            r"([^；;。\r\n]+)",
            text,
        )
        if leading_assignment:
            text = leading_assignment.group(1).strip()
    text = text.replace("\\left", "").replace("\\right", "")
    text = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"((\1)/(\2))", text)
    # Models frequently emit the compact LaTeX form ``\frac12``.  It is
    # unambiguous for single-token numerator/denominator and should not turn a
    # correct final answer into an anchor failure.
    text = re.sub(r"\\frac\s*([0-9A-Za-z])\s*([0-9A-Za-z])", r"((\1)/(\2))", text)
    text = re.sub(r"\\(?:quad|qquad|,|;|!|:)\s*", " ", text)
    text = text.replace("\\cdot", "*").replace("\\times", "*")
    text = text.replace("\\pi", "pi").replace("\\ln", "ln").replace("\\log", "log")
    text = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", text)
    # Expand the Unicode radical before translating adjacent constants such as
    # ``π``.  Otherwise ``√3π`` first becomes ``√3pi`` and the radical's
    # token matcher incorrectly swallows ``pi`` as part of its argument.
    text = re.sub(r"√\s*\(([^()]*)\)", r"sqrt(\1)", text)
    text = re.sub(r"√\s*([0-9]+(?:\.[0-9]+)?)", r"sqrt(\1)", text)
    text = re.sub(r"√\s*([A-Za-z_][A-Za-z0-9_]*)", r"sqrt(\1)", text)
    text = text.translate(
        str.maketrans(
            {
                "π": "pi",
                "λ": "lambda",
                "α": "alpha",
                "β": "beta",
                "·": "*",
                "×": "*",
                "−": "-",
                "–": "-",
                "²": "**2",
                "³": "**3",
                "½": "(1/2)",
            }
        )
    )
    # ``18π√3`` is conventional implicit multiplication.  After Unicode
    # normalization it becomes ``18pisqrt(3)``; split the two known constants
    # before the strict name allow-list so they are not mistaken for an unknown
    # identifier named ``pisqrt``.
    text = re.sub(r"pi(?=sqrt\()", "pi*", text)
    # Chinese exam answers commonly omit both the multiplication sign and
    # parentheses around a one-token function argument (for example
    # ``2sin1`` or ``cos pi``). SymPy otherwise reads ``sin1`` as an unknown
    # symbol and turns a mathematically correct answer into a parser failure.
    text = re.sub(
        r"(?<![A-Za-z_])(sin|cos|exp|log|ln)\s*(?!\()([0-9]+(?:/[0-9]+)?|pi|[A-Za-z_][A-Za-z0-9_]*)",
        r"\1(\2)",
        text,
    )
    # Structured final-answer fields still tend to carry a short explanatory
    # suffix (for example ``-x-y+2z，其中 α=(x,y,z)^T``).  The expression
    # anchor checks the field value, while the rubric checks that explanation.
    text = re.split(r"(?:，|,|；|;)\s*(?:其中|式中|where)", text, maxsplit=1)[0]
    # Remove an explicitly marked parenthetical equivalent/approximation before
    # looking for a labelled equation.  Otherwise a value such as
    # ``2（即 M~Poisson(2)，λ_M=8×1/4=2）`` is incorrectly reduced to the last
    # equality inside the annotation (``2）``) instead of the asserted value.
    # The marker requirement keeps ordinary function parentheses untouched.
    text = re.split(
        r"\s*[（(]\s*(?:即(?:为)?|亦即|约(?:为)?|也就是|i\.?\s*e\.?|approximately|approx\.?)\s*",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    if "≈" in text:
        text = text.split("≈", 1)[0]
    # Pull out an explicitly asserted non-zero symbolic constraint before the
    # generic equation split.  Long explanations may contain later equalities;
    # choosing the constraint with the richest variable set avoids replacing the
    # answer with a trailing auxiliary ``c = ...`` clause.
    nonzero_candidates = re.findall(
        r"(?<![A-Za-z0-9_])"
        r"([+-]?\s*(?:\d+(?:\.\d+)?\s*\*?\s*)?[A-Za-z_][A-Za-z0-9_]*"
        r"(?:\s*[+\-]\s*(?:\d+(?:\.\d+)?\s*\*?\s*)?"
        r"[A-Za-z_][A-Za-z0-9_]*)*)\s*(?:≠|!=)\s*0",
        text,
    )
    if nonzero_candidates:
        text = max(
            nonzero_candidates,
            key=lambda item: (len(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", item))), len(item)),
        ).strip()
    # A final-answer field often contains a label or the complete equation.  Only
    # the right-hand side is the candidate expression being compared.  This runs
    # after suffix removal so an explanatory ``α=(...)`` does not win the split.
    elif "=" in text:
        text = text.rsplit("=", 1)[1]
    # A non-zero constraint is represented by its left-hand expression in the
    # answer anchor.  Accept the ordinary prose wrappers used in Chinese exam
    # answers without treating ``R`` or ``且`` as symbolic variables.
    nonzero = re.search(
        r"(?:^|[，,；;]\s*)(?:且\s*)?([^，,；;]+?)\s*(?:≠|!=)\s*0"
        r"(?=\s|$|[（(])",
        text,
    )
    if nonzero and not nonzero_candidates:
        text = nonzero.group(1).strip()
    # A function answer may append its domain, e.g. ``f(u)=...\quad(u>0)``.
    # The domain is graded by the rubric; the deterministic expression anchor
    # compares only the function body.
    text = re.sub(
        r"\s*[,;，；]?\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\s*(?:>=|<=|>|<|≥|≤)\s*[^()]+\)\s*$",
        "",
        text,
    )
    return text.strip().replace("^", "**")


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


def _apply_mastery_curve(score: float, curve: str) -> float:
    """Map raw coverage to a transparent frontier-mastery scale.

    Frontier cases contain many independently necessary obligations.  A plain
    arithmetic mean makes several material gaps look like an 80+ result.  This
    monotone curve preserves 0 and 100, but reserves the top band for nearly
    complete hidden-test coverage.  It never changes validator evidence or
    turns an incorrect result into a correct one.
    """

    if curve != "frontier_v1":
        return score
    points = (
        (0.0, 0.0),
        (40.0, 24.0),
        (60.0, 42.0),
        (70.0, 54.0),
        (80.0, 67.0),
        (90.0, 80.0),
        (95.0, 89.0),
        (98.0, 95.0),
        (100.0, 100.0),
    )
    value = min(100.0, max(0.0, float(score)))
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:], strict=False):
        if value <= right_x:
            ratio = (value - left_x) / (right_x - left_x)
            return left_y + ratio * (right_y - left_y)
    return 100.0


class ScoringEngine:
    def __init__(
        self,
        docker: DockerExecutor,
        private_validators: PrivateValidatorStore | None = None,
    ):
        self.docker = docker
        self.private_validators = private_validators

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
        scoring_profile: str = CURRENT_SCORING_PROFILE,
    ) -> ScoreResult:
        if scoring_profile not in SUPPORTED_SCORING_PROFILES:
            raise ValueError(f"Unsupported scoring profile: {scoring_profile}")
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
            elif kind == "manual_rubric":
                produced = [
                    ValidationResult(
                        kind,
                        weight,
                        0,
                        "needs_review",
                        {
                            "reason": "作品已交付，等待用户按人工量表评分",
                            "rubric_version": config.get("rubric_version", "1.0"),
                        },
                    )
                ]
            elif kind == "command_metrics":
                produced = self._validate_command_metrics(
                    weight, config, workspace, definition
                )
            elif kind == "symbolic_json":
                produced = [
                    self._validate_symbolic_json(weight, config, final_answer, workspace)
                ]
            elif kind == "constraint_plan":
                produced = self._validate_constraint_plan(weight, config, workspace)
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

        score_basis = str((definition.get("metadata") or {}).get("score_basis") or "balanced")
        quality_only = score_basis in {"backend_quality", "quality_only"}
        quality_time = score_basis == "backend_quality_time"
        metadata = definition.get("metadata") or {}
        quality_weight = (
            max(0.0, min(100.0, float(metadata.get("quality_weight", 90.0))))
            if quality_time
            else 100.0 if quality_only else QUALITY_WEIGHT
        )
        time_weight = (
            max(0.0, 100.0 - quality_weight)
            if quality_time
            else 0.0 if quality_only else TIME_WEIGHT
        )
        declared_weight = sum(item.weight for item in results)
        if declared_weight:
            quality_scale = quality_weight / declared_weight
            for item in results:
                item.evidence = {
                    **item.evidence,
                    "declared_weight": item.weight,
                    "scoring_profile": scoring_profile,
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
                time_weight,
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
                    "scoring_profile": scoring_profile,
                },
            )
        )

        max_steps = max(1, int(limits.get("max_steps", 40)))
        step_ratio = min(1.0, max(0, steps) / max_steps)
        step_score = max(60.0, 100.0 - step_ratio * 40.0)
        results.append(
            ValidationResult(
                "step_efficiency",
                0.0 if (quality_only or quality_time) else STEP_WEIGHT,
                round(step_score, 2),
                "passed",
                {
                    "steps": max(0, steps),
                    "max_steps": max_steps,
                    "budget_used_percent": round(step_ratio * 100, 2),
                    "scoring_profile": scoring_profile,
                },
            )
        )
        token_budget = max(
            0, int(limits.get("token_budget", limits.get("max_tokens", 0)))
        )
        total_tokens = max(0, tokens_input) + max(0, tokens_output)
        tokens_reported = total_tokens > 0 and token_budget > 0
        if tokens_reported:
            # Keep the real ratio for evidence.  Clamping at 100% made a modest
            # overrun and a multi-budget runaway indistinguishable in reports.
            token_ratio = total_tokens / token_budget
            if token_ratio <= 0.25:
                token_score = 100.0
            elif token_ratio <= 1.0:
                token_score = 100.0 - ((token_ratio - 0.25) / 0.75) * 90.0
            else:
                # Token budgets remain a soft target, like time targets.  The
                # final one-percent weight is deliberately small, but exceeding
                # the declared budget must still be explicit and may reach zero.
                token_score = max(0.0, 10.0 - (token_ratio - 1.0) * 40.0)
        else:
            token_ratio = None
            token_score = 50.0
        results.append(
            ValidationResult(
                "token_efficiency",
                0.0 if (quality_only or quality_time) else TOKEN_WEIGHT,
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
                    "budget_exceeded": bool(token_ratio is not None and token_ratio > 1.0),
                    "over_budget_tokens": max(0, total_tokens - token_budget)
                    if tokens_reported
                    else None,
                    "reported": tokens_reported,
                    "note": (
                        "超过 Token 软预算；继续保留结果并按超额比例扣分"
                        if token_ratio is not None and token_ratio > 1.0
                        else None
                        if tokens_reported
                        else "Token 未上报或任务未声明预算，使用中性分"
                    ),
                    "scoring_profile": scoring_profile,
                },
            )
        )
        if any(item.status == "environment_unavailable" for item in results):
            dimensions = self._dimensions(results, scoring_profile)
            return ScoreResult(None, "environment_unavailable", results, dimensions)
        if any(item.status == "needs_review" for item in results):
            dimensions = self._dimensions(results, scoring_profile)
            return ScoreResult(None, "needs_review", results, dimensions)
        total_weight = sum(item.weight for item in results)
        total = (
            sum(item.score * item.weight for item in results) / total_weight if total_weight else 0
        )
        applied_caps: list[dict[str, Any]] = []
        for item in results:
            raw_caps = item.evidence.get("score_caps")
            if not isinstance(raw_caps, list):
                continue
            for raw_cap in raw_caps:
                if not isinstance(raw_cap, dict):
                    continue
                try:
                    maximum = min(100.0, max(0.0, float(raw_cap["max_score"])))
                except (KeyError, TypeError, ValueError):
                    continue
                applied_caps.append(
                    {
                        "key": str(raw_cap.get("key") or "hard_gate"),
                        "max_score": maximum,
                        "reason": str(raw_cap.get("reason") or "触发严重错误评分上限"),
                    }
                )
        raw_total = round(total, 2)
        mastery_curve = str(metadata.get("mastery_curve") or "")
        curved_total = _apply_mastery_curve(total, mastery_curve)
        if mastery_curve:
            total = curved_total
            results.append(
                ValidationResult(
                    "mastery_curve",
                    0.0,
                    round(total, 2),
                    "passed" if total == 100 else "partial",
                    {
                        "curve": mastery_curve,
                        "raw_quality_score": raw_total,
                        "calibrated_score": round(total, 2),
                        "note": "前沿掌握度曲线保留满分，仅压缩存在实质缺口的高分段",
                    },
                )
            )
        score_before_cap = round(total, 2)
        if applied_caps:
            total = min(total, min(item["max_score"] for item in applied_caps))
            results.append(
                ValidationResult(
                    "hard_gate",
                    0.0,
                    round(total, 2),
                    "failed",
                    {
                        "score_before_cap": score_before_cap,
                        "applied_score_cap": round(total, 2),
                        "failures": applied_caps,
                        "score_basis": score_basis,
                    },
                )
            )
        dimensions = self._dimensions(results, scoring_profile)
        if applied_caps or mastery_curve:
            for dimension in dimensions:
                if dimension.validator_type != "objective_quality":
                    continue
                dimension.evidence = {
                    **dimension.evidence,
                    "score_before_cap": dimension.score,
                    "applied_score_cap": round(total, 2),
                    "hard_failures": applied_caps,
                    "mastery_curve": mastery_curve or None,
                    "raw_quality_score": raw_total,
                }
                dimension.score = min(dimension.score, round(total, 2))
                dimension.status = "partial" if dimension.score > 0 else "failed"
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
            if kind == "research_claims":
                return self._validate_research_claims(
                    weight, config, workspace, definition
                )
            if kind == "command":
                limits = definition.get("limits") or {}
                result, private_provenance = self._command_result(workspace, config, limits)
                if result.error_code in {
                    "sandbox_unavailable",
                    "private_validator_unavailable",
                }:
                    return ValidationResult(
                        kind,
                        weight,
                        0,
                        "environment_unavailable",
                        {**result.as_dict(), "private_validator": private_provenance},
                    )
                return self._boolean(
                    kind,
                    weight,
                    result.ok,
                    {**result.as_dict(), "private_validator": private_provenance},
                )
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

    def _validate_research_claims(
        self,
        weight: float,
        config: dict[str, Any],
        workspace: Workspace,
        definition: dict[str, Any],
    ) -> ValidationResult:
        """Deterministically audit research citations and copied numeric facts.

        The semantic judge still grades reasoning and decision quality.  This
        validator covers the parts that should not depend on judge generosity:
        JSON shape, citation existence, page targeting, and numeric fidelity for
        claims explicitly labelled as facts.
        """

        report_path = str(config.get("report_path") or "report.md")
        claims_path = str(config.get("claims_path") or "claims.json")
        min_claims = max(1, int(config.get("min_claims", 12)))
        citation_pattern = re.compile(r"S\d+:p\d+")
        number_pattern = re.compile(
            r"(?<![A-Za-z0-9])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
        )
        percent_pattern = re.compile(
            r"(?<![A-Za-z0-9])([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*%"
        )

        def normalized_numbers(text: str) -> list[str]:
            normalized: list[str] = []
            for match in number_pattern.finditer(text):
                raw_number = match.group(0).replace(",", "")
                try:
                    value = Decimal(raw_number)
                    normalized.append(
                        format(value.quantize(Decimal(1)), "f")
                        if value == value.to_integral_value()
                        else format(value.normalize(), "f")
                    )
                except InvalidOperation:
                    normalized.append(raw_number)
            return normalized

        source_pages: dict[str, str] = {}
        for path, content in (definition.get("initial_files") or {}).items():
            source_match = re.match(r"^(S\d+)", Path(str(path)).name, flags=re.I)
            if not source_match or not isinstance(content, str) or content.startswith("base64:"):
                continue
            source_id = source_match.group(1).upper()
            markers = list(re.finditer(r"\[p(\d+)\]", content, flags=re.I))
            # A source's title/date/version are document metadata and apply to
            # every cited page.  Without this prefix, a faithful claim such as
            # ``董事会材料（2026-06-18）... [S1:p1]`` is incorrectly treated as
            # inventing the date because the date appears before the first [p1].
            document_metadata = content[: markers[0].start()].strip() if markers else ""
            for index, marker in enumerate(markers):
                start = marker.end()
                end = markers[index + 1].start() if index + 1 < len(markers) else len(content)
                page_text = content[start:end].strip()
                source_pages[f"{source_id}:P{marker.group(1)}"] = "\n".join(
                    part for part in (document_metadata, page_text) if part
                )

        try:
            report = workspace.read_file(report_path)
            payload = json.loads(workspace.read_file(claims_path).lstrip("\ufeff"))
            # The public task contract asks for a ``claims.json`` list of claim
            # records but does not require an object wrapper.  Accept both the
            # direct array form and the documented ``{"claims": [...]}`` form
            # so a valid, unambiguous submission is not rejected by a hidden
            # serialization preference.
            claims = payload if isinstance(payload, list) else (
                payload.get("claims") if isinstance(payload, dict) else None
            )
            if not isinstance(claims, list):
                raise ValueError("claims.json must contain a claims array")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return self._graded(
                "research_claims",
                weight,
                0.0,
                {
                    "error": str(exc),
                    "report_path": report_path,
                    "claims_path": claims_path,
                    "score_caps": [
                        {
                            "key": "research_claims_unreadable",
                            "max_score": 45,
                            "reason": "研究主张清单缺失或无法解析",
                        }
                    ],
                },
            )

        # ``type`` and ``confidence`` are required by the public contract, but
        # that contract intentionally does not prescribe an English-only enum.
        # Keep the deterministic check language-neutral and leave semantic
        # appropriateness to the rubric judges.  Only explicit fact labels are
        # subjected to copied-number fidelity checks below.
        fact_types = {"fact", "known_fact", "known fact", "事实", "已知事实"}
        schema_valid = 0
        total_citations = 0
        invalid_citations: list[dict[str, Any]] = []
        numeric_mismatches: list[dict[str, Any]] = []
        derived_numeric_claims: list[dict[str, Any]] = []
        cited_sources: set[str] = set()
        fact_claims = 0
        for index, item in enumerate(claims):
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim") or "").strip()
            citations = item.get("citations")
            claim_type = str(item.get("type") or "").strip().lower()
            confidence = str(item.get("confidence") or "").strip().lower()
            if (
                claim
                and isinstance(citations, list)
                and all(isinstance(value, str) for value in citations)
                and bool(claim_type)
                and bool(confidence)
            ):
                schema_valid += 1
            else:
                continue
            # The task's public example uses Markdown-style ``[S2:p1]`` while
            # JSON submissions also commonly store the bare ``S2:p1`` token.
            # They identify the same page and must be audited identically.
            normalized_citations = [
                str(value).strip().strip("[]").strip().upper() for value in citations
            ]
            total_citations += len(normalized_citations)
            for citation in normalized_citations:
                if citation not in source_pages:
                    invalid_citations.append({"claim_index": index, "citation": citation})
                else:
                    cited_sources.add(citation.split(":", 1)[0])
            if claim_type not in fact_types:
                continue
            fact_claims += 1
            claim_numbers = normalized_numbers(claim)
            if not claim_numbers:
                continue
            cited_text = "\n".join(
                source_pages[citation]
                for citation in normalized_citations
                if citation in source_pages
            )
            source_numbers = set(normalized_numbers(cited_text))
            missing = [value for value in claim_numbers if value not in source_numbers]
            if missing:
                # Permit only an explicitly marked percentage that can be
                # recomputed from two numbers on the cited pages.  This covers
                # transparent statements such as ``31/47 = 66.0%`` while a bare
                # unsupported number (or a wrong calculation) still triggers the
                # hard cap.
                percent_values: set[str] = set()
                for percent_match in percent_pattern.finditer(claim):
                    percent_values.update(normalized_numbers(percent_match.group(1)))
                source_decimals: list[Decimal] = []
                for source_number in source_numbers:
                    try:
                        source_decimals.append(Decimal(source_number))
                    except InvalidOperation:
                        continue
                supported_derived: list[str] = []
                for missing_value in missing:
                    if missing_value not in percent_values:
                        continue
                    try:
                        target = Decimal(missing_value)
                    except InvalidOperation:
                        continue
                    tolerance = max(Decimal("0.11"), abs(target) * Decimal("0.001"))
                    if any(
                        denominator != 0
                        and abs((numerator / denominator * Decimal(100)) - target)
                        <= tolerance
                        for numerator in source_decimals
                        for denominator in source_decimals
                    ):
                        supported_derived.append(missing_value)
                if supported_derived:
                    missing = [value for value in missing if value not in supported_derived]
                    derived_numeric_claims.append(
                        {
                            "claim_index": index,
                            "numbers": supported_derived,
                            "method": "cited_ratio_percentage",
                            "citations": normalized_citations,
                        }
                    )
            if missing:
                numeric_mismatches.append(
                    {
                        "claim_index": index,
                        "numbers": missing,
                        "citations": normalized_citations,
                    }
                )

        report_citations = [value.upper() for value in citation_pattern.findall(report)]
        invalid_report_citations = sorted(
            {citation for citation in report_citations if citation not in source_pages}
        )
        schema_score = 100.0 * schema_valid / max(1, len(claims))
        coverage_score = min(
            100.0,
            55.0 * len(claims) / min_claims
            + 25.0 * min(1.0, total_citations / max(1, min_claims))
            + 20.0 * min(1.0, len(cited_sources) / max(1, len({
                key.split(":", 1)[0] for key in source_pages
            }))),
        )
        citation_checks = total_citations + len(report_citations)
        citation_failures = len(invalid_citations) + len(invalid_report_citations)
        citation_score = (
            100.0 * max(0, citation_checks - citation_failures) / max(1, citation_checks)
        )
        numeric_score = 100.0 * max(
            0, fact_claims - len(numeric_mismatches)
        ) / max(1, fact_claims)
        score = (
            0.20 * schema_score
            + 0.20 * coverage_score
            + 0.25 * citation_score
            + 0.35 * numeric_score
        )
        caps: list[dict[str, Any]] = []
        if invalid_citations or invalid_report_citations:
            caps.append(
                {
                    "key": "research_invalid_citation",
                    "max_score": 65,
                    "reason": "存在无法定位到给定资料页的引用",
                }
            )
        if numeric_mismatches:
            caps.append(
                {
                    "key": "research_numeric_mismatch",
                    "max_score": 75,
                    "reason": "事实型主张中的数字未出现在所引资料页",
                }
            )
        if len(claims) < min_claims:
            caps.append(
                {
                    "key": "research_claim_coverage",
                    "max_score": 85,
                    "reason": f"claims.json 少于要求的 {min_claims} 项主张",
                }
            )
        return self._graded(
            "research_claims",
            weight,
            score,
            {
                "components": {
                    "schema": round(schema_score, 2),
                    "coverage": round(coverage_score, 2),
                    "citations": round(citation_score, 2),
                    "numeric_fidelity": round(numeric_score, 2),
                },
                "claims": len(claims),
                "fact_claims": fact_claims,
                "citations": total_citations,
                "sources_cited": sorted(cited_sources),
                "invalid_citations": invalid_citations[:20],
                "invalid_report_citations": invalid_report_citations[:20],
                "numeric_mismatches": numeric_mismatches[:20],
                "derived_numeric_claims": derived_numeric_claims[:20],
                "score_caps": caps,
            },
        )

    def _validate_symbolic_json(
        self,
        weight: float,
        config: dict[str, Any],
        final_answer: str,
        workspace: Workspace,
    ) -> ValidationResult:
        cap_value = config.get("score_cap_on_failure")
        try:
            failure_cap = (
                min(100.0, max(0.0, float(cap_value))) if cap_value is not None else None
            )
        except (TypeError, ValueError):
            failure_cap = None
        cap_threshold = min(
            100.0, max(0.0, float(config.get("score_cap_threshold", 100.0)))
        )

        def anchor_evidence(evidence: dict[str, Any], score: float) -> dict[str, Any]:
            if failure_cap is None or score >= cap_threshold:
                return evidence
            return {
                **evidence,
                "score_caps": [
                    {
                        "key": str(config.get("score_cap_key") or "answer_anchor_failed"),
                        "max_score": failure_cap,
                        "reason": str(
                            config.get("score_cap_reason")
                            or "确定性最终答案锚点缺失或不等价"
                        ),
                    }
                ],
            }

        try:
            from sympy import E, cos, exp, log, pi, simplify, sin, sqrt, symbols
            from sympy.parsing.sympy_parser import (
                implicit_multiplication_application,
                parse_expr,
                standard_transformations,
            )

            path = config.get("path")
            raw = workspace.read_file(str(path)).lstrip("\ufeff") if path else final_answer
            fields = config.get("fields") or {}
            if not isinstance(fields, dict) or not fields:
                raise ValueError("symbolic_json requires a JSON object and field specifications")
            required_fields = {str(item).split(".", 1)[0] for item in fields}
            if path:
                actual = json.loads(raw)
                extraction = {
                    "mode": "strict_json_file",
                    "format_compliant": True,
                    "embedded": False,
                }
            else:
                actual, extraction = _extract_structured_answer(raw, required_fields)
            if not isinstance(actual, dict):
                raise ValueError("symbolic_json requires a JSON object")
            allowed_functions = {
                "sin": sin,
                "cos": cos,
                "exp": exp,
                "log": log,
                "ln": log,
                "sqrt": sqrt,
                "pi": pi,
                "E": E,
            }
            field_scores: dict[str, float] = {}
            field_evidence: dict[str, Any] = {}
            weighted_total = 0.0
            declared_total = 0.0
            for dotted_path, raw_spec in fields.items():
                spec = raw_spec if isinstance(raw_spec, dict) else {"expected": raw_spec}
                field_weight = max(0.0, float(spec.get("weight", 1)))
                declared_total += field_weight
                value: Any = actual
                try:
                    for part in str(dotted_path).split("."):
                        value = value[int(part)] if isinstance(value, list) else value[part]
                except (KeyError, IndexError, TypeError, ValueError):
                    field_scores[str(dotted_path)] = 0.0
                    field_evidence[str(dotted_path)] = {"reason": "missing"}
                    continue
                expected = spec.get("expected")
                kind = str(spec.get("kind", "literal"))
                if kind == "expression":
                    variables = [str(item) for item in spec.get("variables") or ["x"]]
                    symbol_values = symbols(" ".join(variables), real=True)
                    if not isinstance(symbol_values, tuple):
                        symbol_values = (symbol_values,)
                    local_dict = {
                        **allowed_functions,
                        **dict(zip(variables, symbol_values, strict=True)),
                    }
                    keyword_aliases = {
                        name: f"agentbench_variable_{index}"
                        for index, name in enumerate(variables)
                        if keyword.iskeyword(name)
                    }
                    parse_locals = {
                        **local_dict,
                        **{
                            alias: local_dict[name]
                            for name, alias in keyword_aliases.items()
                        },
                    }

                    scenario_scalar_preference = (
                        spec.get("variables") is not None
                        and not bool(spec.get("variables"))
                    )

                    def parse_expression(
                        candidate: Any,
                        allowed_locals=local_dict,
                        aliases=keyword_aliases,
                        parser_locals=parse_locals,
                        field_variables=variables,
                        prefer_scenario_scalar=scenario_scalar_preference,
                    ):
                        raw_candidate = str(candidate)
                        assignment_context = raw_candidate
                        # ``extension_answer`` is sometimes a self-contained
                        # derivation rather than a bare formula.  The suite asks
                        # for that field but does not forbid explanatory work in
                        # it, so locate the last explicit function assignment for
                        # the declared variable before applying the strict parser.
                        # This stays fail-closed: only a concrete ``name(u)=...``
                        # equation is extracted, and the resulting RHS still goes
                        # through the ordinary allow-list and equivalence checks.
                        function_assignments: list[tuple[int, str]] = []
                        for variable in field_variables:
                            pattern = re.compile(
                                rf"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*\s*\(\s*"
                                rf"{re.escape(variable)}\s*\)\s*=\s*"
                                r"([^，；。\r\n]+)"
                            )
                            function_assignments.extend(
                                (match.start(), match.group(1))
                                for match in pattern.finditer(raw_candidate)
                            )
                        if function_assignments:
                            assignment_start, raw_candidate = max(
                                function_assignments, key=lambda pair: pair[0]
                            )
                            assignment_context = assignment_context[assignment_start:]
                        text = _normalize_symbolic_candidate(
                            raw_candidate,
                            prefer_scenario_scalar=prefer_scenario_scalar,
                        )
                        # A bare finite decimal is an exact structured scalar,
                        # not attribute syntax.  Convert it to an integer ratio
                        # before the general dot ban; all other dotted text still
                        # fails closed.  This makes ``2.625`` exactly equal to
                        # ``21/8`` instead of relying on floating tolerance.
                        if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+)", text):
                            decimal_value = Decimal(text)
                            numerator, denominator = decimal_value.as_integer_ratio()
                            text = f"({numerator}/{denominator})"
                        if len(text) > 2000 or "__" in text or "." in text:
                            raise ValueError("unsafe symbolic expression")
                        if not re.fullmatch(r"[A-Za-z0-9_+\-*/(),\s]+", text):
                            raise ValueError("unsupported symbolic notation")
                        names = set(re.findall(r"[A-Za-z][A-Za-z0-9]*", text))
                        unknown_names = names - set(allowed_locals)
                        # A derivation may display the general antiderivative
                        # after an already-stated final answer, then determine a
                        # constant immediately afterwards, for example
                        # ``f(u)=...+C, C=0``.  Treat only an explicit later
                        # numeric assignment as resolving that symbol.  This is
                        # narrower than accepting arbitrary extra names and keeps
                        # the symbolic anchor fail-closed for unresolved constants.
                        for unknown_name in sorted(unknown_names):
                            constant_pattern = re.compile(
                                rf"(?<![A-Za-z0-9_]){re.escape(unknown_name)}\s*=\s*"
                                r"([+-]?(?:\d+(?:\.\d+)?|\d+\s*/\s*\d+))"
                                r"(?![A-Za-z0-9_.])"
                            )
                            resolved = list(constant_pattern.finditer(assignment_context))
                            if not resolved:
                                continue
                            replacement = resolved[-1].group(1).replace(" ", "")
                            text = re.sub(
                                rf"(?<![A-Za-z0-9_]){re.escape(unknown_name)}"
                                r"(?![A-Za-z0-9_])",
                                f"({replacement})",
                                text,
                            )
                        names = set(re.findall(r"[A-Za-z][A-Za-z0-9]*", text))
                        unknown_names = names - set(allowed_locals)
                        # Parameter names are dummy variables.  A correct answer
                        # may use (x,y,z) where the reference uses (a1,a2,a3).
                        # Permit only a complete one-to-one positional rename;
                        # constants/functions or a partial/mismatched rename still
                        # fail closed.  Ordering by first appearance preserves the
                        # candidate's declared coordinate order.
                        declared_variables = [
                            name for name in allowed_locals if name not in allowed_functions
                        ]
                        if (
                            unknown_names
                            and not (names & set(declared_variables))
                            and len(unknown_names) == len(declared_variables)
                        ):
                            # Indexed coordinates carry their own positional
                            # meaning.  In ``2x3-x1-x2`` the first appearance is
                            # x3, but it must map to a3 rather than a1.  Prefer a
                            # complete numeric-suffix correspondence and retain
                            # first-appearance ordering only for unindexed dummy
                            # names.
                            candidate_indexed = {
                                int(match.group(2)): name
                                for name in unknown_names
                                if (
                                    match := re.fullmatch(
                                        r"([A-Za-z_]+)([0-9]+)", name
                                    )
                                )
                            }
                            declared_indexed = {
                                int(match.group(2)): name
                                for name in declared_variables
                                if (
                                    match := re.fullmatch(
                                        r"([A-Za-z_]+)([0-9]+)", name
                                    )
                                )
                            }
                            if (
                                len(candidate_indexed) == len(unknown_names)
                                and len(declared_indexed) == len(declared_variables)
                                and candidate_indexed.keys() == declared_indexed.keys()
                            ):
                                candidate_order = [
                                    candidate_indexed[index]
                                    for index in sorted(candidate_indexed)
                                ]
                                declared_variables = [
                                    declared_indexed[index]
                                    for index in sorted(declared_indexed)
                                ]
                            else:
                                candidate_order = sorted(
                                    unknown_names,
                                    key=text.find,
                                )
                            for candidate_name, declared_name in zip(
                                candidate_order, declared_variables, strict=True
                            ):
                                text = re.sub(
                                    rf"(?<![A-Za-z_]){re.escape(candidate_name)}(?![A-Za-z0-9_])",
                                    declared_name,
                                    text,
                                )
                            names = set(re.findall(r"[A-Za-z][A-Za-z0-9]*", text))
                        if not names.issubset(allowed_locals):
                            raise ValueError(
                                f"unsupported symbolic names: {sorted(names - set(allowed_locals))}"
                            )
                        for name, alias in aliases.items():
                            text = re.sub(rf"\b{re.escape(name)}\b", alias, text)
                        return parse_expr(
                            text,
                            local_dict=parser_locals,
                            transformations=(
                                *standard_transformations,
                                implicit_multiplication_application,
                            ),
                            evaluate=True,
                        )

                    candidate_expr = parse_expression(value)
                    expected_expr = parse_expression(expected)
                    equivalent = simplify(candidate_expr - expected_expr) == 0
                    method = "symbolic_simplify"
                    if not equivalent and bool(spec.get("equivalent_up_to_nonzero_scalar")):
                        try:
                            ratio = simplify(candidate_expr / expected_expr)
                            equivalent = bool(ratio != 0 and not ratio.free_symbols)
                        except (TypeError, ValueError, ZeroDivisionError):
                            equivalent = False
                        if equivalent:
                            method = "symbolic_nonzero_scalar_equivalence"
                    if not equivalent:
                        comparisons = 0
                        equivalent = True
                        for sample_index, base in enumerate([0.17, 0.43, 0.91, 1.37, 2.11]):
                            substitutions = {
                                symbol: base + position * 0.31 + sample_index * 0.07
                                for position, symbol in enumerate(symbol_values)
                            }
                            try:
                                delta = complex(
                                    (candidate_expr - expected_expr).evalf(
                                        40, subs=substitutions
                                    )
                                )
                            except (TypeError, ValueError, ZeroDivisionError):
                                continue
                            if not math.isfinite(delta.real) or not math.isfinite(delta.imag):
                                continue
                            comparisons += 1
                            if abs(delta) > 1e-9:
                                equivalent = False
                                break
                        equivalent = equivalent and comparisons >= 3
                        method = "private_numeric_sampling"
                    score = 100.0 if equivalent else 0.0
                    field_evidence[str(dotted_path)] = {
                        "equivalent": equivalent,
                        "method": method,
                        "variables": variables,
                    }
                else:
                    def normalize_literal(item: Any) -> str:
                        # JSON arrays/objects are already unambiguous structured
                        # literals.  Canonicalize them before comparison so a
                        # valid value such as ``[0, 1]`` matches an accepted
                        # compact spelling ``[0,1]`` instead of being rejected
                        # because Python's ``str(list)`` inserts spaces.
                        raw = (
                            json.dumps(
                                item,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            if isinstance(item, (list, dict))
                            else str(item)
                        )
                        raw = raw.translate(
                            str.maketrans(
                                {
                                    "₀": "0",
                                    "₁": "1",
                                    "₂": "2",
                                    "₃": "3",
                                    "₄": "4",
                                    "₅": "5",
                                    "₆": "6",
                                    "₇": "7",
                                    "₈": "8",
                                    "₉": "9",
                                    "（": "(",
                                    "）": ")",
                                }
                            )
                        )
                        return re.sub(
                            r"\s*([⊕+])\s*",
                            r"\1",
                            raw.strip().casefold(),
                        )

                    normalized_actual = normalize_literal(value)
                    # Structured literal fields sometimes repeat a narrow label,
                    # for example ``J = J2(1) ⊕ J1(1)``.  Strip only recognised
                    # answer/type labels; arbitrary left-hand prose still fails.
                    labeled_literal = re.fullmatch(
                        r"\s*(?:j|jordan(?:[_\s-]?type)?|type|answer|答案)\s*=\s*(.+)",
                        normalized_actual,
                    )
                    if labeled_literal:
                        normalized_actual = labeled_literal.group(1).strip()
                    accepted = [expected, *(spec.get("accepted") or [])]
                    normalized_accepted = {normalize_literal(item) for item in accepted}
                    normalized_actual = re.sub(
                        r"\s*([⊕+])\s*", r"\1", normalized_actual
                    )
                    equivalent = normalized_actual in normalized_accepted
                    match_method = "literal_exact"
                    if not equivalent:
                        # Infinity is often written with an explicit positive sign
                        # and a parenthetical proof note.  Accept it only when the
                        # configured literals themselves allow infinity and the
                        # note contains an affirmative divergence marker without a
                        # contradiction marker.
                        infinite_allowed = bool(
                            normalized_accepted
                            & {"∞", "+∞", "infinite", "diverges", "无穷"}
                        )
                        infinite_annotated = re.fullmatch(
                            r"\s*\+?∞(?:\s*[（(]\s*(.*?)\s*[)）])?\s*",
                            normalized_actual,
                        )
                        if infinite_allowed and infinite_annotated:
                            annotation = infinite_annotated.group(1) or "∞"
                            affirmative = re.search(
                                r"(?:不存在有限|无有限|发散|无穷|∞|infinite|diverges)",
                                annotation,
                            )
                            contradiction = re.search(
                                r"(?:并非|不是|不等于|而非|not|instead)",
                                annotation,
                            )
                            equivalent = affirmative is not None and contradiction is None
                            if equivalent:
                                match_method = "literal_infinite_annotation"
                    if not equivalent:
                        # A short, affirmative parenthetical is presentation, not
                        # a different literal answer.  Keep this deliberately
                        # narrow so contradictory or arbitrary prose cannot pass.
                        annotated = re.fullmatch(
                            r"\s*(.*?)\s*[（(]\s*(.*?)\s*[)）]\s*",
                            normalized_actual,
                        )
                        affirmative_annotation = (
                            r"(?:不存在有限方差|无有限方差|二阶矩发散|发散|"
                            r"无穷|无限|infinite|diverges|no finite variance)"
                        )
                        if annotated:
                            base, annotation = annotated.groups()
                            equivalent = (
                                base.strip() in normalized_accepted
                                and re.fullmatch(
                                    affirmative_annotation, annotation.strip()
                                )
                                is not None
                            )
                            if equivalent:
                                match_method = "literal_affirmative_annotation"
                    if not equivalent:
                        # ``literal，即 explanation`` still declares the exact
                        # literal before the explanatory suffix.  Reject suffixes
                        # containing explicit contradiction markers.
                        explanatory = re.fullmatch(
                            r"\s*(.*?)\s*(?:，|,)\s*(?:即|也就是|i\.e\.)\s*(.+)",
                            normalized_actual,
                        )
                        if explanatory:
                            base, explanation = explanatory.groups()
                            contradiction = re.search(
                                r"(?:并非|不是|不等于|而非|not|instead)",
                                explanation,
                            )
                            equivalent = (
                                base.strip() in normalized_accepted
                                and explanation.strip() != ""
                                and contradiction is None
                            )
                            if equivalent:
                                match_method = "literal_explanatory_suffix"
                    score = 100.0 if equivalent else 0.0
                    field_evidence[str(dotted_path)] = {
                        "matched": equivalent,
                        "method": match_method,
                    }
                field_scores[str(dotted_path)] = score
                weighted_total += score * field_weight
            score = weighted_total / declared_total if declared_total else 0.0
            return self._graded(
                "symbolic_json",
                weight,
                score,
                anchor_evidence(
                    {
                        "field_scores": field_scores,
                        "field_evidence": field_evidence,
                        "answer_format": extraction,
                    },
                    score,
                ),
            )
        except (ImportError, json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            return self._graded(
                "symbolic_json",
                weight,
                0.0,
                anchor_evidence({"error": str(exc)}, 0.0),
            )

    def _validate_constraint_plan(
        self,
        weight: float,
        config: dict[str, Any],
        workspace: Workspace,
    ) -> list[ValidationResult]:
        metric_specs = [
            ("coverage", "计划覆盖与接口", 10.0),
            ("dependencies", "依赖时序", 20.0),
            ("resources", "资源容量", 20.0),
            ("budget_deadline", "预算、期限与发布窗口", 20.0),
            ("safety_controls", "人工兜底与回滚", 15.0),
            ("objective_quality", "可计算方案质量", 15.0),
        ]
        scores = {key: 0.0 for key, _name, _metric_weight in metric_specs}
        details: dict[str, Any] = {}
        try:
            plan_path = str(config.get("path") or "deliverables/plan.json")
            scenario_path = str(config.get("scenario_path") or "scenario.json")
            plan = json.loads(workspace.read_file(plan_path).lstrip("\ufeff"))
            scenario = json.loads(workspace.read_file(scenario_path).lstrip("\ufeff"))
            task_specs = {str(item["id"]): item for item in scenario["tasks"]}
            if not isinstance(plan, dict) or not task_specs:
                raise ValueError("invalid constraint plan payload")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            details["bootstrap"] = {"error": str(exc)}
            plan = {}
            scenario = {}
            task_specs = {}

        scheduled: dict[str, dict[str, Any]] = {}
        try:
            if plan.get("scenario_id") != scenario.get("scenario_id"):
                raise ValueError("scenario id mismatch")
            raw_tasks = plan.get("tasks")
            if not isinstance(raw_tasks, list) or len(raw_tasks) != len(task_specs):
                raise ValueError("task coverage mismatch")
            for item in raw_tasks:
                if not isinstance(item, dict) or set(item) != {"id", "mode", "start"}:
                    raise ValueError("each scheduled task must contain id, mode and start")
                task_id = str(item["id"])
                if task_id not in task_specs or task_id in scheduled:
                    raise ValueError("unknown or duplicate task")
                mode_name = str(item["mode"])
                mode = task_specs[task_id]["modes"][mode_name]
                if type(item["start"]) is not int or item["start"] < 0:
                    raise ValueError("start must be a non-negative integer")
                duration = int(mode["duration"])
                scheduled[task_id] = {
                    **item,
                    "duration": duration,
                    "cost": int(mode["cost"]),
                    "finish": int(item["start"]) + duration,
                }
            if set(scheduled) != set(task_specs):
                raise ValueError("not all tasks are scheduled")
            scores["coverage"] = 100.0
            details["coverage"] = {"scheduled_tasks": len(scheduled)}
        except (KeyError, TypeError, ValueError) as exc:
            details["coverage"] = {"error": str(exc)}

        try:
            if set(scheduled) != set(task_specs):
                raise ValueError("coverage must pass before dependency validation")
            for task_id, item in scheduled.items():
                for dependency in task_specs[task_id].get("depends_on") or []:
                    if item["start"] < scheduled[str(dependency)]["finish"]:
                        raise ValueError(f"{task_id} starts before dependency {dependency}")
            scores["dependencies"] = 100.0
            details["dependencies"] = {"valid": True}
        except (KeyError, TypeError, ValueError) as exc:
            details["dependencies"] = {"error": str(exc)}

        try:
            if set(scheduled) != set(task_specs):
                raise ValueError("coverage must pass before resource validation")
            capacities = {
                str(name): int(value)
                for name, value in scenario["resource_capacity"].items()
            }
            makespan = max(item["finish"] for item in scheduled.values())
            peak = {name: 0 for name in capacities}
            for moment in range(makespan):
                used = {name: 0 for name in capacities}
                for task_id, item in scheduled.items():
                    if item["start"] <= moment < item["finish"]:
                        for resource, amount in task_specs[task_id]["resources"].items():
                            used[str(resource)] += int(amount)
                for name, capacity in capacities.items():
                    peak[name] = max(peak[name], used[name])
                    if used[name] > capacity:
                        raise ValueError(f"{name} exceeds capacity at {moment}")
            scores["resources"] = 100.0
            details["resources"] = {"peak": peak}
        except (KeyError, TypeError, ValueError) as exc:
            details["resources"] = {"error": str(exc)}

        try:
            total_cost = sum(item["cost"] for item in scheduled.values())
            makespan = max(item["finish"] for item in scheduled.values())
            rollout = scheduled["H"]
            rollout_window = scenario["rollout_window"]
            if total_cost > int(scenario["budget"]):
                raise ValueError("budget exceeded")
            if makespan > int(scenario["deadline"]):
                raise ValueError("deadline exceeded")
            if rollout["start"] < int(rollout_window["earliest_start"]):
                raise ValueError("rollout starts before its window")
            if rollout["finish"] > int(rollout_window["latest_finish"]):
                raise ValueError("rollout finishes after its window")
            scores["budget_deadline"] = 100.0
            details["budget_deadline"] = {"cost": total_cost, "makespan": makespan}
        except (KeyError, TypeError, ValueError) as exc:
            details["budget_deadline"] = {"error": str(exc)}

        try:
            rollback = plan["rollback"]
            requirements = scenario["requirements"]
            if rollback.get("human_override") is not True:
                raise ValueError("human override is required")
            if not 0 < int(rollback["max_minutes"]) <= int(
                requirements["rollback_minutes_max"]
            ):
                raise ValueError("rollback time exceeds the limit")
            if len(str(rollback["owner"]).strip()) < 3:
                raise ValueError("rollback owner is missing")
            if len(str(rollback["trigger"]).strip()) < 20:
                raise ValueError("rollback trigger is not actionable")
            contingencies = plan["contingencies"]
            if not isinstance(contingencies, list) or len(contingencies) < int(
                requirements["minimum_contingencies"]
            ):
                raise ValueError("insufficient contingencies")
            if any(len(str(item).strip()) < 25 for item in contingencies):
                raise ValueError("contingencies are too vague")
            scores["safety_controls"] = 100.0
            details["safety_controls"] = {"contingencies": len(contingencies)}
        except (KeyError, TypeError, ValueError) as exc:
            details["safety_controls"] = {"error": str(exc)}

        try:
            makespan = max(item["finish"] for item in scheduled.values())
            total_cost = sum(item["cost"] for item in scheduled.values())
            reserve = int(scenario["budget"]) - total_cost
            tradeoffs = plan["tradeoffs"]
            if makespan > 16 or reserve < 4:
                raise ValueError("plan misses the calibrated quality frontier")
            if not isinstance(tradeoffs, list) or len(tradeoffs) < 2:
                raise ValueError("tradeoffs are missing")
            if any(len(str(item).strip()) < 30 for item in tradeoffs):
                raise ValueError("tradeoffs are too vague")
            scores["objective_quality"] = 100.0
            details["objective_quality"] = {
                "makespan": makespan,
                "budget_reserve": reserve,
            }
        except (KeyError, TypeError, ValueError) as exc:
            details["objective_quality"] = {"error": str(exc)}

        return [
            ValidationResult(
                name,
                weight * metric_weight / 100.0,
                scores[key],
                "passed" if scores[key] == 100 else "failed",
                {
                    "metric_key": key,
                    "detail": details.get(key) or details.get("bootstrap"),
                },
            )
            for key, name, metric_weight in metric_specs
        ]

    def _command_result(
        self,
        workspace: Workspace,
        config: dict[str, Any],
        limits: dict[str, Any],
    ) -> tuple[CommandResult, dict[str, Any]]:
        private_files = config.get("private_files")
        private_reference = config.get("private_validator_ref")
        private_provenance: dict[str, Any] = {}
        private_root: str | None = None
        if private_files is not None and not isinstance(private_files, dict):
            raise ValueError("private_files must be an object")
        if private_files and private_reference:
            return (
                CommandResult(
                    False,
                    None,
                    "",
                    "A validator cannot declare private_files and private_validator_ref together",
                    0,
                    "private_validator_unavailable",
                ),
                private_provenance,
            )
        try:
            command = str(config.get("command") or "")
            if private_reference:
                if self.private_validators is None:
                    raise PrivateValidatorError("private validator store is not configured")
                resolved = self.private_validators.resolve(private_reference)
                private_files = resolved.files
                private_provenance = resolved.provenance
                command = resolved.command
            if not command:
                raise PrivateValidatorError("private validator command is missing")
            if private_files:
                private_root = f".agentbench-private-{uuid.uuid4().hex}"
                for relative, content in private_files.items():
                    if not isinstance(relative, str) or not isinstance(content, str):
                        raise ValueError("Private validator files must contain text paths")
                    workspace.write_file(f"{private_root}/{relative}", content)
                command = command.replace("{private_root}", private_root)
            validation_seed = str(limits.get("_validation_seed") or "")
            if "{validation_seed}" in command:
                if not re.fullmatch(r"[0-9a-f]{64}", validation_seed):
                    raise PrivateValidatorError("validation seed is unavailable")
                command = command.replace("{validation_seed}", validation_seed)
            return (
                self.docker.run(
                    workspace,
                    command,
                    str(limits.get("docker_image", "python:3.12-alpine")),
                    timeout=min(int(limits.get("validator_timeout_seconds", 180)), 1800),
                    network=str(limits.get("network", "disabled")),
                    cpus=float(limits.get("validator_cpus", 1.0)),
                    memory=str(limits.get("validator_memory", "768m")),
                    pids_limit=int(limits.get("validator_pids_limit", 128)),
                    tmpfs_size=str(limits.get("validator_tmpfs", "128m")),
                ),
                private_provenance,
            )
        except PrivateValidatorError as exc:
            return (
                CommandResult(
                    False,
                    None,
                    "",
                    str(exc),
                    0,
                    "private_validator_unavailable",
                ),
                private_provenance,
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
        result, private_provenance = self._command_result(workspace, config, limits)
        evidence = {**result.as_dict(), "private_validator": private_provenance}
        if result.error_code in {"sandbox_unavailable", "private_validator_unavailable"}:
            return [
                ValidationResult(
                    "validator_platform",
                    weight,
                    0,
                    "environment_unavailable",
                    {
                        **evidence,
                        "error_code": result.error_code,
                        "reason": result.stderr or "私有验证环境不可用",
                    },
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

        configured_caps = config.get("hard_caps") or []
        reported_failures = payload.get("hard_failures") if isinstance(payload, dict) else None
        failure_keys = {
            str(item) for item in reported_failures
        } if isinstance(reported_failures, list) else set()
        score_caps: list[dict[str, Any]] = []
        if isinstance(configured_caps, list):
            for cap in configured_caps:
                if not isinstance(cap, dict) or str(cap.get("key") or "") not in failure_keys:
                    continue
                try:
                    maximum = min(100.0, max(0.0, float(cap["max_score"])))
                except (KeyError, TypeError, ValueError):
                    continue
                score_caps.append(
                    {
                        "key": str(cap["key"]),
                        "max_score": maximum,
                        "reason": str(cap.get("reason") or "触发严重错误评分上限"),
                    }
                )
        configured_metric_caps = config.get("metric_caps") or []
        if isinstance(configured_metric_caps, list):
            for cap in configured_metric_caps:
                if not isinstance(cap, dict):
                    continue
                key = str(cap.get("metric_key") or cap.get("key") or "")
                if not key:
                    continue
                try:
                    value = float(metric_values.get(key, 0))
                    minimum = float(cap.get("min_score", 100))
                    maximum = min(100.0, max(0.0, float(cap["max_score"])))
                except (KeyError, TypeError, ValueError):
                    continue
                if value >= minimum:
                    continue
                score_caps.append(
                    {
                        "key": str(cap.get("key") or f"{key}_below_mastery"),
                        "metric_key": key,
                        "metric_score": round(value, 2),
                        "required_score": round(minimum, 2),
                        "max_score": maximum,
                        "reason": str(
                            cap.get("reason")
                            or f"关键指标 {key} 未达到 {minimum:g} 分"
                        ),
                    }
                )
        output: list[ValidationResult] = []
        detail = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        for position, item in enumerate(declared):
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
                        "private_validator": private_provenance,
                        "hard_failures": sorted(failure_keys) if position == 0 else [],
                        "score_caps": score_caps if position == 0 else [],
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
    def _dimensions(
        results: list[ValidationResult], scoring_profile: str
    ) -> list[ValidationResult]:
        groups = {
            "objective_quality": [
                item
                for item in results
                if item.validator_type
                not in {
                    "ai_rubric",
                    "manual_rubric",
                    "time_efficiency",
                    "step_efficiency",
                    "token_efficiency",
                }
            ],
            "judge_quality": [item for item in results if item.validator_type == "ai_rubric"],
            "manual_quality": [
                item for item in results if item.validator_type == "manual_rubric"
            ],
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
                        "scoring_profile": scoring_profile,
                    },
                )
            )
        return dimensions
