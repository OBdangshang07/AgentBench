from __future__ import annotations

from agentbench.service import (
    _materialize_private_frontier_variant,
    public_definition,
)
from agentbench.six_dimension_suite import (
    FRONTEND_BLACK_HOLE_PROMPT,
    FRONTEND_CASE_VERSION,
    FRONTEND_HONG_KONG_PROMPT,
    FRONTEND_SELF_PROMPT,
    SUITE_CASE_SLUGS,
    SUITE_VERSION,
    build_frontier_math_cases,
    build_six_dimension_cases,
)


def test_frontend_prompts_and_rubrics_remain_pinned_to_v1():
    cases = {
        item["slug"]: item
        for item in build_six_dimension_cases()
        if item["metadata"]["capability_dimension"] == "creative_frontend"
    }
    prompts = {
        "sixdim.frontend-self-digital-experience": FRONTEND_SELF_PROMPT,
        "sixdim.frontend-hong-kong-voxel": FRONTEND_HONG_KONG_PROMPT,
        "sixdim.frontend-single-file-black-hole": FRONTEND_BLACK_HOLE_PROMPT,
    }

    assert FRONTEND_CASE_VERSION == "1.0.0"
    assert set(cases) == set(prompts)
    for slug, prompt in prompts.items():
        assert cases[slug]["version"] == FRONTEND_CASE_VERSION
        assert cases[slug]["instruction"] == prompt
        assert cases[slug]["validators"] == [
            {
                "type": "manual_rubric",
                "weight": 100,
                "config": {"rubric_version": "six-dimension-frontend/v1"},
            }
        ]
        assert "frontier_profile" not in cases[slug]["metadata"]


def test_frontier_math_v5_is_seeded_three_layer_and_defect_aware():
    cases = build_frontier_math_cases()

    assert [item["slug"] for item in cases] == [
        f"sixdim.math.frontier.q{number}" for number in range(17, 23)
    ]
    assert [
        next(v for v in item["validators"] if v["type"] == "ai_rubric")["config"][
            "max_points"
        ]
        for item in cases
    ] == [40, 40, 40, 40, 45, 45]
    for item in cases:
        assert item["version"] == SUITE_VERSION == "4.1.1"
        assert item["tools"] == []
        assert "工具增强测试" not in item["instruction"]
        assert "闭卷极限测试" in item["instruction"]
        assert "Frontier" in item["instruction"]
        assert item["metadata"]["score_basis"] == "quality_only"
        assert item["metadata"]["frontier_profile"] == "seeded-three-layer-proof-v5"
        assert item["metadata"]["mastery_curve"] == "frontier_v1"
        rubric = next(
            validator["config"]
            for validator in item["validators"]
            if validator["type"] == "ai_rubric"
        )
        assert rubric["required_judges"] == 3
        assert rubric["full_credit_confidence"] == 0.95
        assert rubric["judge_disagreement_threshold"] == 2
        assert rubric["consensus_mode"] == "defect_aware"
        assert rubric["mandatory_failure_score_cap"] == 80
        assert rubric["critical_defect_score_cap"] == 88
        frontier_points = [
            point for point in rubric["scoring_points"] if ".f" in point["point_id"]
        ]
        assert sum(float(point["max_points"]) for point in frontier_points) == 30
        symbolic = next(
            (validator for validator in item["validators"] if validator["type"] == "symbolic_json"),
            None,
        )
        assert symbolic is not None
        assert symbolic["weight"] == 40
        assert symbolic["config"]["score_cap_on_failure"] == 70
        judge = next(v for v in item["validators"] if v["type"] == "ai_rubric")
        assert judge["weight"] == 60
        assert "单个、可解析的 JSON 对象" in item["instruction"]

    by_number = {int(item["slug"].rsplit("q", 1)[1]): item for item in cases}
    assert "λ∈R" in by_number[18]["instruction"]
    assert "有理数" in by_number[19]["instruction"]
    assert "F(r)=Mr+c" in by_number[20]["instruction"]
    assert "f_α" in by_number[22]["instruction"]
    # The two retained probes keep their prior hard extensions.
    assert "再计算 K=" in by_number[17]["instruction"]
    assert "最小多项式和 Jordan 块类型" in by_number[21]["instruction"]
    assert "(-1)^nF^(n)" in by_number[17]["instruction"]
    assert "g_xx+g_yy=0" in by_number[18]["instruction"]
    assert "κ>0" in by_number[19]["instruction"]
    assert "椭圆截面" in by_number[20]["instruction"]
    assert "所有实平方根" in by_number[21]["instruction"]
    assert "一大跳渐近" in by_number[22]["instruction"]
    assert "H_n(s)" in by_number[17]["instruction"]
    assert "L_ρ" in by_number[18]["instruction"]
    assert "固定一个 0<h0<1" in by_number[19]["instruction"]
    assert "椭圆截锥" in by_number[20]["instruction"]
    assert "连通分支" in by_number[21]["instruction"]
    assert "二阶尾展开" in by_number[22]["instruction"]
    for number in (18, 19, 20, 22):
        rubric = next(
            validator["config"]
            for validator in by_number[number]["validators"]
            if validator["type"] == "ai_rubric"
        )
        assert any(point.get("mandatory") for point in rubric["scoring_points"])


def test_private_math_variants_are_hidden_and_seed_deterministic():
    cases = {item["slug"]: item for item in build_frontier_math_cases()}
    for number in range(17, 23):
        definition = cases[f"sixdim.math.frontier.q{number}"]
        assert len(definition["_private_frontier_variants"]["variants"]) == 3
        assert "_private_frontier_variants" not in public_definition(definition)

        selected_by_id = {}
        for seed_number in range(256):
            seed = f"{seed_number:064x}"
            first, first_selection = _materialize_private_frontier_variant(
                definition, seed
            )
            second, second_selection = _materialize_private_frontier_variant(
                definition, seed
            )
            assert first == second
            assert first_selection == second_selection
            assert "_private_frontier_variants" not in first
            selected_by_id[first_selection["variant_id"]] = first

        assert len(selected_by_id) == 3
        for materialized in selected_by_id.values():
            symbolic = next(
                validator["config"]
                for validator in materialized["validators"]
                if validator["type"] == "symbolic_json"
            )
            rubric = next(
                validator["config"]
                for validator in materialized["validators"]
                if validator["type"] == "ai_rubric"
            )
            assert symbolic["fields"]
            assert rubric["reference_answer"]
            assert materialized["metadata"]["frontier_variant_pool"].endswith(
                "pool-v3"
            )


def test_frontier_math_variant_anchor_values_are_audited():
    cases = {item["slug"]: item for item in build_frontier_math_cases()}
    expected = {
        17: {
            "stieltjes-shift-1": "-log(2)/5+pi/10",
            "stieltjes-shift-2": "-7*log(2)/10+pi/20+2*log(3)/5",
            "stieltjes-shift-3": "-9*log(3)/17+pi/34+14*log(2)/17",
        },
        18: {
            "anisotropic-rho-half": "1/2",
            "anisotropic-rho-minus-half": "-1/2",
            "anisotropic-rho-third": "1/3",
        },
        19: {
            "quartic-p1-q3": "21/8",
            "quartic-p2-q4": "5/2",
            "quartic-pminus1-q5": "37/8",
        },
        20: {
            "affine-h2-a": "-42*pi",
            "affine-h3-b": "-260*pi/3-16*sqrt(3)*pi",
            "affine-h4-c": "-84*pi",
        },
        21: {
            "matrix-root-power-2": "2",
            "matrix-root-power-3": "3",
            "matrix-root-power-5": "5",
        },
        22: {
            "pareto-alpha-3": "-2400000000",
            "pareto-alpha-4-lambda-5": "-1075000000000/3",
            "pareto-alpha-5-lambda-12": "-108750000000000",
        },
    }
    anchor_key = {
        17: "extension_answer",
        18: "anisotropic_rho",
        19: "explicit_kappa_max",
        20: "frustum_flux",
        21: "root_target_power",
        22: "second_order_tail_coefficient",
    }

    for number, variants in expected.items():
        definition = cases[f"sixdim.math.frontier.q{number}"]
        materialized_by_id = {}
        for seed_number in range(512):
            materialized, selection = _materialize_private_frontier_variant(
                definition, f"{seed_number:064x}"
            )
            materialized_by_id[selection["variant_id"]] = materialized
            if len(materialized_by_id) == 3:
                break
        assert set(materialized_by_id) == set(variants)
        for variant_id, wanted in variants.items():
            symbolic = next(
                validator["config"]
                for validator in materialized_by_id[variant_id]["validators"]
                if validator["type"] == "symbolic_json"
            )
            assert symbolic["fields"][anchor_key[number]]["expected"] == wanted
            instruction = materialized_by_id[variant_id]["instruction"]
            if variant_id == "pareto-alpha-4-lambda-5":
                assert "P(S>x)~5P(Y>x)" in instruction
                assert "P(S>x)~8P(Y>x)" not in instruction
            if variant_id == "pareto-alpha-5-lambda-12":
                assert "P(S>x)~12P(Y>x)" in instruction
                assert "P(S>x)~8P(Y>x)" not in instruction


def test_research_cases_require_adversarial_evidence_audit():
    cases = [
        item
        for item in build_six_dimension_cases()
        if item["metadata"]["capability_dimension"] == "research_writing"
    ]

    assert len(cases) == 2
    for item in cases:
        assert len(item["initial_files"]) >= 10
        assert item["metadata"]["score_basis"] == "quality_only"
        assert item["metadata"]["frontier_profile"] == "evidence-adversarial-v3"
        assert item["metadata"]["mastery_curve"] == "frontier_v1"
        assert [validator["weight"] for validator in item["validators"]] == [2, 2, 2, 34, 60]
        audit = next(
            validator for validator in item["validators"] if validator["type"] == "research_claims"
        )
        assert audit["config"]["min_claims"] == 30
        assert "三个最脆弱的关键假设" in item["instruction"]
        assert "decision_model.json" in item["instruction"]
        judge = next(v for v in item["validators"] if v["type"] == "ai_rubric")
        assert judge["config"]["required_judges"] == 3


def test_six_dimension_data_cases_use_hidden_holdouts_and_mastery_caps():
    catalog = {item["slug"]: item for item in build_six_dimension_cases()}
    data_slugs = [slug for slug in SUITE_CASE_SLUGS if slug.startswith("sixdim.data-")]

    assert data_slugs == [
        "sixdim.data-incremental-revenue-ledger",
        "sixdim.data-online-experiment-audit",
        "sixdim.data-temporal-risk-model",
    ]
    for slug in data_slugs:
        case = catalog[slug]
        assert case["metadata"]["capability_dimension"] == "data_engineering_science"
        assert case["metadata"]["mastery_curve"] == "frontier_v1"
        command = next(
            validator
            for validator in case["validators"]
            if validator["type"] == "command_metrics"
        )
        assert sum(item["weight"] for item in command["config"]["metrics"]) == 100
        assert command["config"]["private_files"]["validate.py"]
        assert command["config"]["metric_caps"]


def test_online_experiment_hidden_payload_obeys_binary_received_contract():
    case = next(
        item
        for item in build_six_dimension_cases()
        if item["slug"] == "sixdim.data-online-experiment-audit"
    )
    command = next(
        validator
        for validator in case["validators"]
        if validator["type"] == "command_metrics"
    )
    source = command["config"]["private_files"]["validate.py"]
    setup_source = source.split("try: analyze=", 1)[0]
    namespace: dict[str, object] = {}
    exec(compile(setup_source, "<experiment-validator-setup>", "exec"), namespace)
    payload = namespace["payload"]

    for reversal, zero_stage in ((False, False), (True, False), (False, True)):
        generated = payload(reversal, zero_stage)
        received = [row["received"] for row in generated["units"]]
        assert received
        assert set(received) <= {0, 1}

    assert {
        row["received"] for row in payload(False, True)["units"]
    } == {0}
