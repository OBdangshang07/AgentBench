from __future__ import annotations

import pytest

from agentbench.math_rubric import (
    RUBRIC_SCHEMA,
    normalize_rubric,
    rubric_json_schema,
    score_rubric,
    structured_rubric_config,
)


def _config() -> dict:
    return structured_rubric_config(
        version="2025.math1.q17.r1",
        source={
            "source_id": "expert-q17",
            "version": "2025.math1.q17.r1",
            "source_tier": "expert_reconstructed",
            "verification_status": "partially_verified",
        },
        scoring_points=[
            {"point_id": "decomp", "description": "分解", "max_points": 3},
            {
                "point_id": "integrate",
                "description": "积分",
                "max_points": 4,
                "depends_on": ["decomp"],
            },
            {
                "point_id": "boundary",
                "description": "上下限",
                "max_points": 3,
                "depends_on": ["integrate"],
                "error_carry_forward": {
                    "enabled": True,
                    "rule": "前一步独立算术错误不重复扣分",
                },
            },
        ],
    )


def _answer(config: dict, *, awards: list[float], confidence: float = 1.0) -> dict:
    return {
        "schema": RUBRIC_SCHEMA,
        "rubric_version": config["rubric_version"],
        "source_tier": config["source_tier"],
        "solution_path": "reference",
        "points": [
            {
                "point_id": point["point_id"],
                "awarded_points": award,
                "status": "met" if award else "not_met",
                "confidence": confidence,
                "evidence": "答案中的对应步骤",
                "rationale": "可复核",
                "propagated_error": False,
                "independent_work": True,
                "defect_severity": "none",
            }
            for point, award in zip(config["scoring_points"], awards, strict=True)
        ],
        "overall_confidence": confidence,
        "summary": "逐点评分",
        "review_flags": [],
    }


def test_structured_rubric_scores_full_solution_by_max_points():
    config = _config()
    result = score_rubric(_answer(config, awards=[3, 4, 3]), config)

    assert result.status == "passed"
    assert result.awarded_points == 10
    assert result.max_points == 10
    assert result.percentage == 100
    assert result.evidence["rubric_source"]["source_tier"] == "expert_reconstructed"
    assert result.evidence["rubric_version"] == "2025.math1.q17.r1"


def test_structured_rubric_applies_dependency_and_clamps_over_award():
    config = _config()
    # ``integrate`` is awarded despite a missing prerequisite, and ``boundary`` is
    # above max_points.  The backend, rather than the model, decides both outcomes.
    answer = _answer(config, awards=[0, 10, 10])
    result = score_rubric(answer, config)

    assert result.status == "needs_review"
    assert "dependency_violation" in result.review_flags
    assert result.awarded_points == 0
    assert result.point_results[1]["awarded_points"] == 0
    assert result.point_results[2]["awarded_points"] == 0


def test_error_carry_forward_preserves_independent_later_work():
    config = _config()
    answer = _answer(config, awards=[0, 0, 3])
    answer["points"][2]["propagated_error"] = True
    answer["points"][2]["independent_work"] = True
    result = score_rubric(answer, config)

    assert result.awarded_points == 3
    assert result.point_results[2]["error_carry_forward_applied"] is True
    assert "dependency_violation" not in result.review_flags


def test_low_confidence_and_new_solution_are_review_flags_with_provisional_score():
    config = _config()
    config["allow_new_solutions"] = False
    answer = _answer(config, awards=[3, 2, 3], confidence=0.4)
    answer["solution_path"] = "new"
    result = score_rubric(answer, config)

    assert result.status == "needs_review"
    assert result.percentage == 80
    assert {"low_confidence", "new_solution"}.issubset(result.review_flags)
    assert result.evidence["review_flags"] == result.review_flags
    assert result.point_results[0]["max_points"] == 3


def test_allowed_new_solution_with_complete_confident_points_passes():
    config = _config()
    answer = _answer(config, awards=[3, 4, 3])
    answer["solution_path"] = "new"

    result = score_rubric(answer, config)

    assert result.status == "passed"
    assert result.percentage == 100
    assert "new_solution" not in result.review_flags


def test_judge_disagreement_is_recorded_without_changing_arithmetic():
    config = _config()
    result = score_rubric(_answer(config, awards=[3, 4, 3]), config, disagreement=True)

    assert result.status == "needs_review"
    assert result.percentage == 100
    assert "judge_disagreement" in result.review_flags


def test_benign_judge_notes_are_audited_without_forcing_manual_review():
    config = _config()
    answer = _answer(config, awards=[3, 4, 3])
    answer["review_flags"] = [
        "candidate_noted_bash_unavailable_manual_verification_only",
        "candidate_self_noted_typo:formatting only",
    ]

    result = score_rubric(answer, config)

    assert result.status == "passed"
    assert result.review_flags == []
    assert result.evidence["judge_review_notes"] == answer["review_flags"]


def test_low_point_confidence_is_a_controlled_review_trigger():
    config = _config()
    answer = _answer(config, awards=[3, 4, 3])
    answer["points"][1]["confidence"] = 0.4

    result = score_rubric(answer, config)

    assert result.status == "needs_review"
    assert "low_point_confidence" in result.review_flags


def test_mutually_exclusive_alternate_paths_use_best_route_as_denominator():
    config = structured_rubric_config(
        version="r1",
        source={"source_id": "s", "source_tier": "expert_reconstructed"},
        scoring_points=[
            {"point_id": "common", "description": "共同前置", "max_points": 2},
            {"point_id": "a", "description": "路径 A", "max_points": 3},
            {"point_id": "b", "description": "路径 B", "max_points": 4},
        ],
        alternate_paths=[
            {"path_id": "path-a", "point_ids": ["common", "a"]},
            {"path_id": "path-b", "point_ids": ["common", "b"]},
        ],
    )
    answer = _answer(config, awards=[2, 3, 4])
    result = score_rubric(answer, config)

    assert config["max_points"] == 6
    assert result.awarded_points == 6
    assert result.percentage == 100
    assert result.status == "passed"
    assert result.evidence["selected_alternate_path"] == "path-b"


def test_rubric_json_schema_is_point_specific_and_legacy_is_explicit():
    config = _config()
    schema = rubric_json_schema(config)
    assert schema["$id"] == RUBRIC_SCHEMA
    assert schema["properties"]["points"]["items"]["properties"]["point_id"]["enum"] == [
        "decomp",
        "integrate",
        "boundary",
    ]

    legacy = normalize_rubric({"reference_answer": "x", "weight": 100})
    assert legacy["rubric_protocol"] == "legacy-v1"
    assert legacy["source_tier"] == "unverified"


def test_strict_exam_rounds_down_and_forces_defect_deductions():
    config = structured_rubric_config(
        version="strict-v2",
        source={"source_id": "strict", "source_tier": "expert_reconstructed"},
        scoring_points=[
            {"point_id": "proof", "description": "完整证明", "max_points": 3},
            {"point_id": "result", "description": "最终结论", "max_points": 2},
        ],
        marking_mode="strict_exam",
        point_increment=0.5,
        minor_defect_deduction=0.5,
        major_defect_deduction=1.0,
        full_credit_confidence=0.9,
        required_judges=2,
    )
    answer = _answer(config, awards=[2.9, 2], confidence=0.95)
    answer["points"][0]["status"] = "partial"
    answer["points"][0]["defect_severity"] = "minor"

    result = score_rubric(answer, config)

    assert result.status == "passed"
    assert result.awarded_points == 4.5
    assert result.point_results[0]["awarded_points"] == 2.5
    assert "rounded_down_to_point_increment" in result.point_results[0]["strict_adjustments"]
    assert config["required_judges"] == 2
    schema = rubric_json_schema(config)
    assert "defect_severity" in schema["properties"]["points"]["items"]["required"]


def test_strict_exam_full_score_guard_deducts_unresolved_logical_gap():
    config = structured_rubric_config(
        version="strict-v2",
        source={"source_id": "strict", "source_tier": "expert_reconstructed"},
        scoring_points=[{"point_id": "proof", "description": "完整证明", "max_points": 3}],
        marking_mode="strict_exam",
        required_judges=2,
    )
    answer = _answer(config, awards=[3], confidence=0.95)
    answer["review_flags"] = ["论证衔接存在可修补缺口"]
    answer["points"][0]["defect_severity"] = "minor"

    result = score_rubric(answer, config)

    assert result.status == "passed"
    assert result.awarded_points == 2.5
    assert "minor_defect_minimum_deduction" in result.point_results[0]["strict_adjustments"]


def test_strict_exam_presentation_note_does_not_manufacture_deduction():
    config = structured_rubric_config(
        version="strict-v3",
        source={"source_id": "strict", "source_tier": "expert_reconstructed"},
        scoring_points=[{"point_id": "proof", "description": "完整证明", "max_points": 3}],
        marking_mode="strict_exam",
        required_judges=2,
    )
    answer = _answer(config, awards=[3], confidence=0.95)
    answer["review_flags"] = ["附加小数校验末位舍入差，不影响精确推导"]
    answer["points"][0]["defect_severity"] = "presentation"

    result = score_rubric(answer, config)

    assert result.status == "passed"
    assert result.awarded_points == 3.0
    assert result.evidence["strict_question_adjustment"] is None


def test_rubric_rejects_unknown_dependency_and_version_mismatch():
    with pytest.raises(ValueError, match="reference_not_found"):
        normalize_rubric(
            {
                "rubric_version": "r1",
                "rubric_source": {
                    "source_id": "s",
                    "version": "r1",
                    "source_tier": "official_national",
                },
                "source_tier": "official_national",
                "scoring_points": [
                    {
                        "point_id": "p1",
                        "description": "point",
                        "max_points": 1,
                        "depends_on": ["missing"],
                    }
                ],
            }
        )

    config = _config()
    answer = _answer(config, awards=[3, 4, 3])
    answer["rubric_version"] = "old"
    with pytest.raises(ValueError, match="version_mismatch"):
        score_rubric(answer, config)
