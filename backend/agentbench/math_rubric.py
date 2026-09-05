"""Versioned, structured rubrics for postgraduate-mathematics solution questions.

The official marking scheme is a *source* of scoring points; it is not inferred by
the judge at run time.  This module deliberately keeps source provenance next to the
points and performs the arithmetic after the judge has only supplied per-point
decisions.  It is therefore safe to use with a reconstructed rubric as long as the
caller labels its ``source_tier`` honestly.

The module has no dependency on the database or on an LLM.  That makes the protocol
usable by the importer, the runtime scorer, API validation, and regression tests
without coupling those layers together.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

RUBRIC_SCHEMA = "agentbench.math-rubric/v1"
SOURCE_TIERS = {
    "official_national",
    "official_provincial",
    "expert_reconstructed",
    "unverified",
}
SourceTier = Literal[
    "official_national",
    "official_provincial",
    "expert_reconstructed",
    "unverified",
]


class RubricSourceModel(BaseModel):
    """Auditable provenance for a marking scheme.

    ``source_tier`` is intentionally mandatory.  A URL alone is not evidence that a
    page is an official marking scheme, so the UI and reports can never silently
    promote a reconstruction to an official source.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source_id: str = Field(min_length=1, max_length=240)
    version: str = Field(min_length=1, max_length=120)
    source_tier: SourceTier
    title: str = Field(default="", max_length=500)
    issuing_body: str = Field(default="", max_length=240)
    url: str | None = Field(default=None, max_length=4_000)
    accessed_at: str | None = Field(default=None, max_length=80)
    page: str | int | None = None
    evidence: str = Field(default="", max_length=10_000)
    verification_status: Literal["verified", "partially_verified", "unverified"] = (
        "unverified"
    )
    notes: str = Field(default="", max_length=5_000)


class ErrorCarryForwardModel(BaseModel):
    """How the marker should treat a propagated earlier error.

    The AI may identify the propagated error, but it may not alter this policy or the
    point maximum.  ``independent_work_credit`` is a documentation flag used by the
    judge prompt and review UI.  The deterministic scorer only honors the explicit
    ``enabled``/independent-work gate; any numeric deduction cap remains audit
    metadata for the human marker because a model cannot be trusted to infer the
    correct inherited-error magnitude.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    rule: str = Field(min_length=1, max_length=2_000)
    independent_work_credit: bool = True
    max_repeated_deduction: float = Field(default=0, ge=0)


class ScoringPointModel(BaseModel):
    """One independently markable item in a solution question."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    point_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9._:-]+$",
        validation_alias=AliasChoices("point_id", "id"),
    )
    description: str = Field(min_length=1, max_length=4_000)
    max_points: float = Field(gt=0, le=100)
    depends_on: list[str] = Field(default_factory=list, max_length=30)
    mutually_exclusive_with: list[str] = Field(default_factory=list, max_length=30)
    alternate_path: str | None = Field(default=None, max_length=120)
    alternate_for: list[str] = Field(default_factory=list, max_length=30)
    error_carry_forward: ErrorCarryForwardModel | None = None
    evidence_required: list[str] = Field(default_factory=list, max_length=20)
    critical: bool = False
    mandatory: bool = False
    minimum_defect_deduction: float = Field(default=0.0, ge=0, le=100)
    notes: str = Field(default="", max_length=2_000)


class AlternatePathModel(BaseModel):
    """A mutually exclusive valid solution route.

    Shared prerequisite points may appear in multiple paths.  The deterministic
    scorer counts the shared points once and chooses the path with the highest
    non-shared awarded total (ties resolve by lexical ``path_id``).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9._:-]+$",
        validation_alias=AliasChoices("path_id", "id"),
    )
    point_ids: list[str] = Field(min_length=1, max_length=50)
    label: str = Field(default="", max_length=500)
    mutually_exclusive: bool = True


class MathRubricModel(BaseModel):
    """The private rubric payload embedded in a test-case definition."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    protocol_schema: str = Field(default=RUBRIC_SCHEMA, alias="schema")
    rubric_version: str = Field(
        min_length=1,
        max_length=120,
        validation_alias=AliasChoices("rubric_version", "version"),
    )
    rubric_source: RubricSourceModel
    source_tier: SourceTier
    scoring_points: list[ScoringPointModel] = Field(min_length=1, max_length=100)
    alternate_paths: list[AlternatePathModel] = Field(default_factory=list, max_length=30)
    allow_new_solutions: bool = True
    low_confidence_threshold: float = Field(default=0.70, ge=0, le=1)
    judge_disagreement_threshold: float = Field(default=12.0, ge=0, le=100)
    marking_mode: Literal["standard", "strict_exam"] = "standard"
    point_increment: float = Field(default=0.5, gt=0, le=10)
    minor_defect_deduction: float = Field(default=0.5, gt=0, le=10)
    major_defect_deduction: float = Field(default=1.0, gt=0, le=20)
    full_credit_confidence: float = Field(default=0.90, ge=0, le=1)
    required_judges: int = Field(default=1, ge=1, le=3)
    consensus_mode: Literal["median", "defect_aware"] = "median"
    critical_failure_score_cap: float = Field(default=60.0, ge=0, le=100)
    # Compatibility defaults are neutral.  Frontier v3 opts into 90/95
    # explicitly so frozen v1/v2 rubrics retain their historical score semantics.
    mandatory_failure_score_cap: float = Field(default=100.0, ge=0, le=100)
    critical_defect_score_cap: float = Field(default=100.0, ge=0, le=100)

    @model_validator(mode="after")
    def source_tier_matches_source(self) -> MathRubricModel:
        if self.rubric_source.source_tier != self.source_tier:
            raise ValueError("rubric_source.source_tier_mismatch")
        return self


class PointDecisionModel(BaseModel):
    """The only score-bearing output the AI judge is allowed to produce."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    point_id: str = Field(min_length=1, max_length=120)
    awarded_points: float = Field(ge=0, le=100)
    status: Literal["met", "partial", "not_met", "not_applicable", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(default="", max_length=10_000)
    rationale: str = Field(default="", max_length=5_000)
    propagated_error: bool = False
    independent_work: bool = False
    defect_severity: Literal["none", "presentation", "minor", "major", "fatal"] = (
        "none"
    )


class AIRubricResultModel(BaseModel):
    """Strict judge response envelope; score is computed by the backend."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    protocol_schema: str = Field(default=RUBRIC_SCHEMA, alias="schema")
    rubric_version: str = Field(min_length=1, max_length=120)
    source_tier: SourceTier
    solution_path: Literal["reference", "alternate", "new", "unclear"] = "reference"
    points: list[PointDecisionModel] = Field(max_length=100)
    overall_confidence: float = Field(ge=0, le=1)
    summary: str = Field(default="", max_length=10_000)
    review_flags: list[str] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True, slots=True)
class StructuredRubricScore:
    """Deterministic score and audit details returned by :func:`score_rubric`."""

    awarded_points: float
    max_points: float
    percentage: float
    status: Literal["passed", "needs_review", "invalid"]
    point_results: list[dict[str, Any]]
    review_flags: list[str]
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "awarded_points": self.awarded_points,
            "max_points": self.max_points,
            "percentage": self.percentage,
            "status": self.status,
            "point_results": deepcopy(self.point_results),
            "point_awards": deepcopy(self.point_results),
            "review_flags": list(self.review_flags),
            "review_status": self.status,
            "review_reasons": list(self.review_flags),
            "evidence": deepcopy(self.evidence),
        }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, Mapping):
            return dict(parsed)
    raise ValueError("math_rubric_result_must_be_json_object")


def _source_from_config(config: Mapping[str, Any]) -> dict[str, Any]:
    source = config.get("rubric_source")
    if not isinstance(source, Mapping):
        # Keep the migration path explicit: a legacy config is not elevated to an
        # official source merely because it has a reference answer.
        return {
            "source_id": "legacy-unversioned",
            "version": str(config.get("rubric_version") or "legacy"),
            "source_tier": "unverified",
            "verification_status": "unverified",
        }
    return dict(source)


def normalize_rubric(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a rubric config without mutating its input.

    ``scoring_points`` is the new protocol.  A config without it is returned as a
    legacy rubric marker and must be scored by the old compatibility path.  This is
    important for historical runs: loading an old test case must not silently change
    its score semantics.
    """

    raw = deepcopy(dict(config))
    points = raw.get("scoring_points")
    if not points:
        raw.setdefault("rubric_protocol", "legacy-v1")
        raw.setdefault("rubric_version", "legacy")
        raw.setdefault("source_tier", "unverified")
        return raw
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        raise ValueError("scoring_points_must_be_array")
    source = _source_from_config(raw)
    if raw.get("source_tier") and source.get("source_tier") and raw["source_tier"] != source["source_tier"]:
        raise ValueError("rubric_source.source_tier_mismatch")
    source.setdefault("source_tier", raw.get("source_tier", "unverified"))
    source.setdefault("version", str(raw.get("rubric_version") or "unversioned"))
    source.setdefault("source_id", "unversioned")
    if source.get("source_tier") not in SOURCE_TIERS:
        raise ValueError("invalid_rubric_source_tier")
    raw["rubric_source"] = source
    raw["source_tier"] = source["source_tier"]
    raw["rubric_version"] = str(raw.get("rubric_version") or source.get("version"))
    raw["schema"] = str(raw.get("schema") or RUBRIC_SCHEMA)
    if raw["schema"] != RUBRIC_SCHEMA:
        raise ValueError("unsupported_math_rubric_schema")

    normalized_points: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in points:
        if not isinstance(item, Mapping):
            raise ValueError("scoring_point_must_be_object")
        point = dict(item)
        point_id = str(point.get("point_id") or point.get("id") or "").strip()
        if not point_id:
            raise ValueError("scoring_point_missing_id")
        if point_id in seen:
            raise ValueError(f"duplicate_scoring_point:{point_id}")
        seen.add(point_id)
        description = str(point.get("description") or point.get("label") or "").strip()
        if not description:
            raise ValueError(f"scoring_point_missing_description:{point_id}")
        try:
            max_points = float(point.get("max_points"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"scoring_point_invalid_max_points:{point_id}") from exc
        if not math.isfinite(max_points) or max_points <= 0:
            raise ValueError(f"scoring_point_invalid_max_points:{point_id}")
        point["point_id"] = point_id
        point.pop("id", None)
        point["description"] = description
        point["max_points"] = max_points
        point["depends_on"] = [str(item) for item in point.get("depends_on") or []]
        point["mutually_exclusive_with"] = [
            str(item) for item in point.get("mutually_exclusive_with") or []
        ]
        point["alternate_for"] = [str(item) for item in point.get("alternate_for") or []]
        point["critical"] = bool(point.get("critical", False))
        point["mandatory"] = bool(point.get("mandatory", False))
        try:
            minimum_defect_deduction = float(
                point.get("minimum_defect_deduction", 0.0) or 0.0
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"scoring_point_invalid_minimum_defect_deduction:{point_id}"
            ) from exc
        if (
            not math.isfinite(minimum_defect_deduction)
            or minimum_defect_deduction < 0
            or minimum_defect_deduction > max_points
        ):
            raise ValueError(
                f"scoring_point_invalid_minimum_defect_deduction:{point_id}"
            )
        point["minimum_defect_deduction"] = minimum_defect_deduction
        if point.get("alternate_path") is not None:
            point["alternate_path"] = str(point["alternate_path"])
        normalized_points.append(point)
    point_ids = {item["point_id"] for item in normalized_points}
    for point in normalized_points:
        missing = set(point["depends_on"]) | set(point["mutually_exclusive_with"])
        missing |= set(point["alternate_for"])
        missing -= point_ids
        if missing:
            raise ValueError(
                f"scoring_point_reference_not_found:{point['point_id']}:{','.join(sorted(missing))}"
            )
        if point.get("error_carry_forward") is not None and not isinstance(
            point["error_carry_forward"], Mapping
        ):
            raise ValueError(f"invalid_error_carry_forward:{point['point_id']}")

    alternate_paths: list[dict[str, Any]] = []
    for item in raw.get("alternate_paths") or []:
        if not isinstance(item, Mapping):
            raise ValueError("alternate_path_must_be_object")
        path = dict(item)
        path_id = str(path.get("path_id") or path.get("id") or "").strip()
        path_points = [str(point) for point in path.get("point_ids") or []]
        if not path_id or not path_points:
            raise ValueError("alternate_path_requires_id_and_points")
        if not set(path_points).issubset(point_ids):
            missing = sorted(set(path_points) - point_ids)
            raise ValueError(f"alternate_path_reference_not_found:{','.join(missing)}")
        path["path_id"] = path_id
        path["point_ids"] = path_points
        path.pop("id", None)
        alternate_paths.append(path)
    raw["scoring_points"] = normalized_points
    raw["alternate_paths"] = alternate_paths
    raw.setdefault("allow_new_solutions", True)
    raw.setdefault("low_confidence_threshold", 0.70)
    raw.setdefault("judge_disagreement_threshold", 12.0)
    raw.setdefault("marking_mode", "standard")
    raw.setdefault("point_increment", 0.5)
    raw.setdefault("minor_defect_deduction", 0.5)
    raw.setdefault("major_defect_deduction", 1.0)
    raw.setdefault("full_credit_confidence", 0.90)
    raw.setdefault("required_judges", 1)
    raw.setdefault("consensus_mode", "median")
    raw.setdefault("critical_failure_score_cap", 60.0)
    raw.setdefault("mandatory_failure_score_cap", 100.0)
    raw.setdefault("critical_defect_score_cap", 100.0)
    raw["rubric_protocol"] = RUBRIC_SCHEMA
    raw["max_points"] = _effective_max_points(normalized_points, alternate_paths)
    return raw


def rubric_json_schema(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return the strict JSON schema shown to the anonymous judge.

    Point IDs are constrained to the IDs from ``config`` when present, while the
    backend still validates the full payload (including duplicate/missing points)
    after JSON parsing.
    """

    normalized = normalize_rubric(config or {}) if config else {}
    point_ids = [
        str(item["point_id"])
        for item in normalized.get("scoring_points") or []
        if isinstance(item, Mapping) and item.get("point_id")
    ]
    decision_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "point_id",
            "awarded_points",
            "status",
            "confidence",
            "evidence",
            "rationale",
            "propagated_error",
            "independent_work",
        ],
        "properties": {
            "point_id": {"type": "string", "minLength": 1},
            "awarded_points": {"type": "number", "minimum": 0},
            "status": {
                "type": "string",
                "enum": ["met", "partial", "not_met", "not_applicable", "uncertain"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "string"},
            "rationale": {"type": "string"},
            "propagated_error": {"type": "boolean"},
            "independent_work": {"type": "boolean"},
            "defect_severity": {
                "type": "string",
                "enum": ["none", "presentation", "minor", "major", "fatal"],
            },
        },
    }
    if normalized.get("marking_mode") == "strict_exam":
        decision_schema["required"].append("defect_severity")
    if point_ids:
        decision_schema["properties"]["point_id"]["enum"] = point_ids
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": RUBRIC_SCHEMA,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema",
            "rubric_version",
            "source_tier",
            "solution_path",
            "points",
            "overall_confidence",
            "summary",
            "review_flags",
        ],
        "properties": {
            "schema": {"const": RUBRIC_SCHEMA},
            "rubric_version": {"type": "string", "minLength": 1},
            "source_tier": {"enum": sorted(SOURCE_TIERS)},
            "solution_path": {"enum": ["reference", "alternate", "new", "unclear"]},
            "points": {"type": "array", "items": decision_schema},
            "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": {"type": "string"},
            "review_flags": {"type": "array", "items": {"type": "string"}},
        },
    }


def _decision_map(payload: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    raw_points = payload.get("points")
    if not isinstance(raw_points, Sequence) or isinstance(raw_points, (str, bytes)):
        raise ValueError("judge_points_must_be_array")
    decisions: dict[str, dict[str, Any]] = {}
    flags: list[str] = []
    for raw in raw_points:
        if not isinstance(raw, Mapping):
            flags.append("invalid_point_decision")
            continue
        point_id = str(raw.get("point_id") or raw.get("id") or "").strip()
        if not point_id:
            flags.append("invalid_point_decision")
            continue
        if point_id in decisions:
            flags.append("duplicate_point_decision")
            continue
        decisions[point_id] = dict(raw)
    return decisions, flags


def _effective_max_points(
    points: Sequence[Mapping[str, Any]], alternate_paths: Sequence[Mapping[str, Any]]
) -> float:
    """Return the denominator after collapsing mutually exclusive solution routes."""

    point_lookup = {str(item["point_id"]): item for item in points}
    exclusive_paths = [
        path
        for path in alternate_paths
        if bool(path.get("mutually_exclusive", True))
    ]
    path_point_ids = {
        str(point_id)
        for path in exclusive_paths
        for point_id in path.get("point_ids") or []
    }
    outside_total = sum(
        float(item["max_points"])
        for item in points
        if str(item["point_id"]) not in path_point_ids
    )
    if not exclusive_paths:
        return round(outside_total + sum(float(item["max_points"]) for item in points if str(item["point_id"]) in path_point_ids), 6)
    path_totals = [
        sum(float(point_lookup[str(point_id)]["max_points"]) for point_id in path.get("point_ids") or [])
        for path in exclusive_paths
    ]
    return round(outside_total + max(path_totals, default=0.0), 6)


def score_rubric(
    payload: Mapping[str, Any] | str,
    config: Mapping[str, Any],
    *,
    disagreement: bool = False,
) -> StructuredRubricScore:
    """Parse an AI response and compute a score solely from rubric point maxima.

    The function never trusts a model-provided total score.  It rejects incomplete
    point lists, clamps individual awards to their configured maxima, applies
    dependencies/exclusive paths deterministically, and leaves review flags in the
    evidence for the human reviewer.
    """

    normalized = normalize_rubric(config)
    points = normalized.get("scoring_points") or []
    if not points:
        raise ValueError("structured_rubric_requires_scoring_points")
    try:
        data = _as_mapping(payload)
        parsed = AIRubricResultModel.model_validate(data)
    except Exception as exc:
        raise ValueError(f"invalid_structured_rubric_result:{exc}") from exc
    if data.get("schema") != RUBRIC_SCHEMA:
        raise ValueError("judge_rubric_schema_mismatch")
    if parsed.rubric_version != str(normalized.get("rubric_version")):
        raise ValueError("judge_rubric_version_mismatch")
    if parsed.source_tier != normalized.get("source_tier"):
        raise ValueError("judge_rubric_source_tier_mismatch")

    decisions, flags = _decision_map(data)
    expected_ids = [str(item["point_id"]) for item in points]
    missing = [point_id for point_id in expected_ids if point_id not in decisions]
    unknown = sorted(set(decisions) - set(expected_ids))
    if missing:
        flags.append("missing_point_decision")
    if unknown:
        flags.append("unknown_point_decision")
    if disagreement:
        flags.append("judge_disagreement")
    if parsed.solution_path == "new" and not bool(
        normalized.get("allow_new_solutions", True)
    ):
        flags.append("new_solution")
    if parsed.solution_path == "unclear":
        flags.append("unclear_solution_path")
    # Judge-authored notes are useful audit evidence, but arbitrary prose must not
    # decide workflow state.  Escalation is derived below from controlled fields
    # (coverage, confidence, solution path, rule consistency, and disagreement).
    judge_review_notes = list(dict.fromkeys(str(item) for item in parsed.review_flags))
    threshold = float(normalized.get("low_confidence_threshold", 0.70))
    strict_exam = normalized.get("marking_mode") == "strict_exam"
    point_increment = float(normalized.get("point_increment", 0.5))
    minor_deduction = float(normalized.get("minor_defect_deduction", point_increment))
    major_deduction = float(normalized.get("major_defect_deduction", 1.0))
    full_credit_confidence = float(normalized.get("full_credit_confidence", 0.90))
    if parsed.overall_confidence < threshold:
        flags.append("low_confidence")

    point_lookup = {str(item["point_id"]): item for item in points}
    awarded: dict[str, float] = {}
    point_results: list[dict[str, Any]] = []
    for point_id in expected_ids:
        spec = point_lookup[point_id]
        raw = decisions.get(point_id, {})
        try:
            value = float(raw.get("awarded_points", 0))
        except (TypeError, ValueError):
            value = 0.0
            flags.append("invalid_awarded_points")
        if not math.isfinite(value):
            value = 0.0
            flags.append("invalid_awarded_points")
        max_points = float(spec["max_points"])
        value = min(max_points, max(0.0, value))
        try:
            point_confidence = float(raw.get("confidence", 0))
        except (TypeError, ValueError):
            point_confidence = 0.0
        if raw.get("status") == "uncertain" or point_confidence < threshold:
            flags.append("low_point_confidence")
        strict_adjustments: list[str] = []
        defect_severity = str(raw.get("defect_severity") or "none")
        point_minimum_deduction = float(spec.get("minimum_defect_deduction", 0.0))
        if strict_exam:
            # Exam marks are awarded in fixed half-point units.  Always round down:
            # a judge may not create extra credit through a generous decimal.
            quantized = math.floor((value + 1e-9) / point_increment) * point_increment
            if abs(quantized - value) > 1e-9:
                strict_adjustments.append("rounded_down_to_point_increment")
            value = quantized
            status = str(raw.get("status") or "not_met")
            if status in {"not_met", "not_applicable"} or defect_severity == "fatal":
                if value > 0:
                    strict_adjustments.append("zeroed_unmet_or_fatal_point")
                value = 0.0
            elif status == "partial" and value >= max_points:
                value = max(0.0, max_points - point_increment)
                strict_adjustments.append("partial_status_cannot_receive_full_credit")
            if defect_severity == "minor":
                cap = max(
                    0.0,
                    max_points
                    - max(point_increment, minor_deduction, point_minimum_deduction),
                )
                if value > cap:
                    value = cap
                    strict_adjustments.append("minor_defect_minimum_deduction")
            elif defect_severity == "major":
                cap = max(
                    0.0,
                    max_points
                    - max(point_increment, major_deduction, point_minimum_deduction),
                )
                if value > cap:
                    value = cap
                    strict_adjustments.append("major_defect_minimum_deduction")
            if value >= max_points and point_confidence < full_credit_confidence:
                value = max(0.0, max_points - point_increment)
                strict_adjustments.append("full_credit_confidence_not_met")
            value = round(value, 6)
        awarded[point_id] = value
        point_results.append(
            {
                "point_id": point_id,
                "description": spec["description"],
                "max_points": max_points,
                "awarded_points_before_rules": round(value, 6),
                "awarded_points": round(value, 6),
                "status": raw.get("status", "not_met"),
                "confidence": raw.get("confidence"),
                "evidence": raw.get("evidence", ""),
                "rationale": raw.get("rationale", ""),
                "propagated_error": bool(raw.get("propagated_error", False)),
                "independent_work": bool(raw.get("independent_work", False)),
                "defect_severity": defect_severity,
                "strict_adjustments": strict_adjustments,
                "depends_on": list(spec.get("depends_on") or []),
                "mutually_exclusive_with": list(spec.get("mutually_exclusive_with") or []),
                "alternate_path": spec.get("alternate_path"),
                "error_carry_forward": deepcopy(spec.get("error_carry_forward")),
                "critical": bool(spec.get("critical", False)),
                "mandatory": bool(spec.get("mandatory", False)),
                "minimum_defect_deduction": point_minimum_deduction,
            }
        )

    result_by_id = {item["point_id"]: item for item in point_results}
    # Dependencies are intentionally conservative: a dependent mark cannot be
    # awarded when any declared prerequisite is absent.  The rubric author can model
    # independent credit by splitting the point or leaving ``depends_on`` empty.
    for point_id in expected_ids:
        spec = point_lookup[point_id]
        deps = [str(item) for item in spec.get("depends_on") or []]
        if deps and any(awarded.get(dep, 0.0) <= 0 for dep in deps):
            carry_policy = spec.get("error_carry_forward")
            decision = decisions.get(point_id) or {}
            if (
                isinstance(carry_policy, Mapping)
                and bool(carry_policy.get("enabled", True))
                and bool(decision.get("propagated_error"))
                and bool(decision.get("independent_work"))
            ):
                # The candidate's prerequisite is wrong, but the current step is
                # independently and mechanically correct.  Preserve this point in
                # accordance with the declared error-carry-forward policy.
                result_by_id[point_id]["error_carry_forward_applied"] = True
                continue
            if awarded[point_id] > 0:
                flags.append("dependency_violation")
            awarded[point_id] = 0.0
            result_by_id[point_id]["dependency_blocked"] = True

    # Explicit pairwise mutual exclusion: retain the highest awarded member.  A
    # lexical tie-break makes repeated scoring bit-for-bit reproducible.
    handled_pairs: set[tuple[str, str]] = set()
    for point_id in expected_ids:
        for other in point_lookup[point_id].get("mutually_exclusive_with") or []:
            pair = tuple(sorted((point_id, str(other))))
            if pair in handled_pairs or pair[0] not in awarded or pair[1] not in awarded:
                continue
            handled_pairs.add(pair)
            left, right = pair
            loser = left if awarded[left] <= awarded[right] else right
            if awarded[loser] > 0:
                flags.append("mutual_exclusion_applied")
                awarded[loser] = 0.0
                result_by_id[loser]["mutual_exclusion_blocked"] = True

    # Alternative paths: count the best complete route only.  Points shared by
    # multiple paths are counted once, so a prerequisite cannot inflate the score.
    paths = [item for item in normalized.get("alternate_paths") or [] if item.get("mutually_exclusive", True)]
    selected_alternate_path: str | None = None
    if paths:
        path_scores = {
            str(path["path_id"]): sum(
                awarded.get(str(point_id), 0.0) for point_id in path.get("point_ids") or []
            )
            for path in paths
        }
        best_path = sorted(path_scores, key=lambda key: (-path_scores[key], key))[0]
        selected_alternate_path = best_path
        allowed = {str(item) for path in paths if str(path["path_id"]) == best_path for item in path.get("point_ids") or []}
        for path in paths:
            if str(path["path_id"]) == best_path:
                continue
            for point_id in path.get("point_ids") or []:
                point_id = str(point_id)
                if point_id not in allowed and awarded.get(point_id, 0.0) > 0:
                    awarded[point_id] = 0.0
                    result_by_id[point_id]["alternate_path_blocked"] = True

    for item in point_results:
        item["awarded_points"] = round(awarded[item["point_id"]], 6)
    max_total = float(normalized["max_points"])
    strict_question_adjustment: dict[str, Any] | None = None
    substantive_flag = any(
        str(item.get("defect_severity") or "none") in {"minor", "major", "fatal"}
        for item in point_results
    )
    if strict_exam and parsed.review_flags and substantive_flag and sum(awarded.values()) >= max_total:
        # Only a controlled mathematical defect may activate the full-score guard.
        # Free-form review notes can also describe rounding, notation or presentation
        # issues; those remain in the audit evidence but must not manufacture a
        # deduction when every point is mathematically sound.
        credited = [item for item in point_results if awarded[item["point_id"]] > 0]
        if credited:
            target = min(
                credited,
                key=lambda item: (float(item.get("confidence") or 0), item["point_id"]),
            )
            point_id = str(target["point_id"])
            before = awarded[point_id]
            awarded[point_id] = max(0.0, before - point_increment)
            target["awarded_points"] = round(awarded[point_id], 6)
            target["strict_adjustments"].append("substantive_review_flag_full_score_guard")
            strict_question_adjustment = {
                "point_id": point_id,
                "before": round(before, 6),
                "after": round(awarded[point_id], 6),
                "judge_review_notes": judge_review_notes,
            }
    awarded_total = round(sum(awarded.values()), 6)
    percentage_before_cap = (
        round(awarded_total / max_total * 100.0, 2) if max_total else 0.0
    )
    critical_failures = [
        point_id
        for point_id in expected_ids
        if bool(point_lookup[point_id].get("critical")) and awarded.get(point_id, 0.0) <= 0
    ]
    mandatory_failures = [
        point_id
        for point_id in expected_ids
        if bool(point_lookup[point_id].get("mandatory"))
        and awarded.get(point_id, 0.0) + 1e-9 < float(point_lookup[point_id]["max_points"])
    ]
    critical_defects = [
        point_id
        for point_id in expected_ids
        if bool(point_lookup[point_id].get("critical"))
        and str(result_by_id[point_id].get("defect_severity") or "none")
        in {"minor", "major", "fatal"}
    ]
    critical_cap = float(normalized.get("critical_failure_score_cap", 60.0))
    mandatory_cap = float(normalized.get("mandatory_failure_score_cap", 100.0))
    critical_defect_cap = float(normalized.get("critical_defect_score_cap", 100.0))
    active_caps: list[tuple[str, float]] = []
    if critical_failures:
        active_caps.append(("critical_failure_score_cap", critical_cap))
    if mandatory_failures:
        active_caps.append(("mandatory_failure_score_cap", mandatory_cap))
    if critical_defects:
        active_caps.append(("critical_defect_score_cap", critical_defect_cap))
    percentage = min(
        [percentage_before_cap, *(cap for _name, cap in active_caps)]
    )
    # A point omission, malformed decision, low confidence, a new route, or judge
    # disagreement is reviewable even though a provisional arithmetic score exists.
    review_flags = list(dict.fromkeys(flags))
    status: Literal["passed", "needs_review", "invalid"] = (
        "needs_review" if review_flags else "passed"
    )
    if not expected_ids or missing or unknown:
        status = "invalid"
    return StructuredRubricScore(
        awarded_points=awarded_total,
        max_points=round(max_total, 6),
        percentage=percentage,
        status=status,
        point_results=point_results,
        review_flags=review_flags,
        evidence={
            "rubric_protocol": RUBRIC_SCHEMA,
            "rubric_version": normalized["rubric_version"],
            "rubric_source": deepcopy(normalized["rubric_source"]),
            "source_tier": normalized["source_tier"],
            "calculation": (
                "min(raw_percentage, active_question_caps)"
                if active_caps
                else "sum(clamp(awarded_points, 0, max_points)) / sum(max_points) * 100"
            ),
            "awarded_points": awarded_total,
            "max_points": round(max_total, 6),
            "percentage": percentage,
            "percentage_before_cap": percentage_before_cap,
            "critical_failures": critical_failures,
            "critical_failure_score_cap": critical_cap,
            "mandatory_failures": mandatory_failures,
            "mandatory_failure_score_cap": mandatory_cap,
            "critical_defects": critical_defects,
            "critical_defect_score_cap": critical_defect_cap,
            "active_question_caps": [
                {"reason": reason, "cap": cap} for reason, cap in active_caps
            ],
            "review_flags": review_flags,
            "judge_review_notes": judge_review_notes,
            "review_status": status,
            "review_reasons": review_flags,
            "point_awards": deepcopy(point_results),
            "selected_alternate_path": selected_alternate_path,
            "marking_mode": normalized.get("marking_mode", "standard"),
            "point_increment": point_increment,
            "strict_question_adjustment": strict_question_adjustment,
            "scored_at": _now_iso(),
        },
    )


def structured_rubric_config(
    *,
    version: str,
    source: Mapping[str, Any],
    scoring_points: Sequence[Mapping[str, Any]],
    alternate_paths: Sequence[Mapping[str, Any]] | None = None,
    allow_new_solutions: bool = True,
    low_confidence_threshold: float = 0.70,
    judge_disagreement_threshold: float = 12.0,
    marking_mode: Literal["standard", "strict_exam"] = "standard",
    point_increment: float = 0.5,
    minor_defect_deduction: float = 0.5,
    major_defect_deduction: float = 1.0,
    full_credit_confidence: float = 0.90,
    required_judges: int = 1,
    consensus_mode: Literal["median", "defect_aware"] = "median",
    critical_failure_score_cap: float = 60.0,
    mandatory_failure_score_cap: float = 100.0,
    critical_defect_score_cap: float = 100.0,
) -> dict[str, Any]:
    """Build a normalized config for a published solution case."""

    source_payload = dict(source)
    source_payload.setdefault("version", version)
    source_payload.setdefault("source_id", "unversioned")
    source_payload.setdefault("source_tier", "unverified")
    config = {
        "schema": RUBRIC_SCHEMA,
        "rubric_version": version,
        "rubric_source": source_payload,
        "source_tier": source_payload["source_tier"],
        "scoring_points": list(scoring_points),
        "alternate_paths": list(alternate_paths or []),
        "allow_new_solutions": allow_new_solutions,
        "low_confidence_threshold": low_confidence_threshold,
        "judge_disagreement_threshold": judge_disagreement_threshold,
        "marking_mode": marking_mode,
        "point_increment": point_increment,
        "minor_defect_deduction": minor_defect_deduction,
        "major_defect_deduction": major_defect_deduction,
        "full_credit_confidence": full_credit_confidence,
        "required_judges": required_judges,
        "consensus_mode": consensus_mode,
        "critical_failure_score_cap": critical_failure_score_cap,
        "mandatory_failure_score_cap": mandatory_failure_score_cap,
        "critical_defect_score_cap": critical_defect_score_cap,
    }
    return normalize_rubric(config)


__all__ = [
    "AIRubricResultModel",
    "AlternatePathModel",
    "ErrorCarryForwardModel",
    "MathRubricModel",
    "PointDecisionModel",
    "RUBRIC_SCHEMA",
    "RubricSourceModel",
    "SOURCE_TIERS",
    "ScoringPointModel",
    "StructuredRubricScore",
    "normalize_rubric",
    "rubric_json_schema",
    "score_rubric",
    "structured_rubric_config",
]
