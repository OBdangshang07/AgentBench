from __future__ import annotations

import json

from agentbench.execution import CommandResult, DockerExecutor, Workspace
from agentbench.scoring import ScoringEngine, ValidationResult, _apply_mastery_curve


def test_deterministic_scoring_and_efficiency(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [{"type": "exact_match", "weight": 90, "config": {"expected": "OK"}}],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="OK\n",
        workspace=workspace,
        steps=2,
        duration_ms=9_000,
        tokens_input=200,
        tokens_output=50,
    )
    assert score.status == "scored"
    assert score.score == 99.84
    assert score.components[0].evidence["actual"] == "OK"
    assert [item.validator_type for item in score.components[-3:]] == [
        "time_efficiency",
        "step_efficiency",
        "token_efficiency",
    ]
    assert sum(item.weight for item in score.components) == 100


def test_zero_weight_math_anchor_applies_score_cap_to_ai_rubric(tmp_path):
    workspace = Workspace(tmp_path / "math-anchor")
    definition = {
        "metadata": {"score_basis": "backend_quality"},
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 0,
                "config": {
                    "fields": {
                        "final_answer": {
                            "kind": "expression",
                            "expected": "3*log(2)/10+pi/10",
                            "variables": [],
                        }
                    },
                    "score_cap_on_failure": 60,
                },
            },
            {"type": "ai_rubric", "weight": 100, "config": {"dimensions": ["推导"]}},
        ],
    }

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer='{"final_answer":"0","solution":"伪造的完整推导"}',
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
        judge_callback=lambda _config, weight: ValidationResult(
            "ai_rubric", weight, 95, "passed", {"judge": "over-generous"}
        ),
    )

    assert score.score == 60
    assert any(item.validator_type == "hard_gate" for item in score.components)
    anchor = next(item for item in score.components if item.validator_type == "symbolic_json")
    assert anchor.evidence["score_caps"][0]["max_score"] == 60


def test_symbolic_anchor_accepts_parenthesized_equivalent_and_decimal(tmp_path):
    workspace = Workspace(tmp_path / "math-equivalent-suffix")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "final_answer": {
                            "kind": "expression",
                            "expected": "-2*pi/sqrt(3)",
                            "variables": [],
                        }
                    }
                },
            }
        ],
    }

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=json.dumps(
            {"final_answer": "-2√3π/3（即 -2π/√3 ≈ -3.6276）"}, ensure_ascii=False
        ),
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"]["final_answer"] == 100


def test_symbolic_anchor_extracts_final_function_from_extension_derivation(tmp_path):
    workspace = Workspace(tmp_path / "math-extension-prose")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "extension_answer": {
                            "kind": "expression",
                            "expected": "u+log(u)+log(u)**2/2",
                            "variables": ["u"],
                        }
                    }
                },
            }
        ],
    }
    answer = json.dumps(
        {
            "extension_answer": (
                "扩展方程 u^2f''(u)+uf'(u)=1+u，积分后得到通解。"
                "由初值得 C=1、D=0，所以新的解为"
                "f(u)=u+\\ln u+\\frac12(\\ln u)^2。"
                "再令 t=\\ln u、F(t)=f(e^t)，齐次方程为 F''=0，"
                "故 F=At+B。"
            )
        },
        ensure_ascii=False,
    )

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=answer,
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"]["extension_answer"] == 100


def test_symbolic_anchor_resolves_later_numeric_integration_constant(tmp_path):
    workspace = Workspace(tmp_path / "math-extension-resolved-constant")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "extension_answer": {
                            "kind": "expression",
                            "expected": "u+log(u)+log(u)**2/2",
                            "variables": ["u"],
                        }
                    }
                },
            }
        ],
    }
    answer = json.dumps(
        {
            "extension_answer": (
                "新的 f(u)=u+ln u+(ln u)^2/2。"
                "再积分得 f(u)=u+ln u+(ln u)^2/2+C，"
                "由 f(1)=1 定出 C=0。"
            )
        },
        ensure_ascii=False,
    )

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=answer,
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"]["extension_answer"] == 100


def test_symbolic_anchor_accepts_affirmative_literal_annotation(tmp_path):
    workspace = Workspace(tmp_path / "math-literal-annotation")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "annual_variance": {
                            "kind": "literal",
                            "expected": "infinite",
                            "accepted": ["∞", "diverges", "无穷"],
                        }
                    }
                },
            }
        ],
    }

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=json.dumps(
            {"annual_variance": "+∞（方差不存在/发散，E[Y²] = +∞）"}, ensure_ascii=False
        ),
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert (
        anchor.evidence["field_evidence"]["annual_variance"]["method"]
        == "literal_infinite_annotation"
    )


def test_symbolic_anchor_canonicalizes_structured_literal_arrays(tmp_path):
    workspace = Workspace(tmp_path / "math-structured-literal-array")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "lambda_values": {
                            "kind": "literal",
                            "expected": "{0,1}",
                            "accepted": ["[0,1]"],
                        }
                    }
                },
            }
        ],
    }

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=json.dumps({"lambda_values": [0, 1]}),
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"]["lambda_values"] == 100


def test_symbolic_anchor_extracts_leading_scalar_before_proof_summary(tmp_path):
    workspace = Workspace(tmp_path / "math-leading-scalar-summary")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "extension_answer": {
                            "kind": "expression",
                            "expected": "-log(2)/5+pi/10",
                            "variables": [],
                        }
                    }
                },
            }
        ],
    }

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=json.dumps(
            {
                "extension_answer": (
                    "K=(π−2 ln 2)/10；对所有 s>0、n≥0 有完全单调性，且 H_n(s)>0。"
                )
            },
            ensure_ascii=False,
        ),
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"]["extension_answer"] == 100


def test_symbolic_anchor_extracts_explicit_scenario_scalar_after_general_formula(
    tmp_path,
):
    workspace = Workspace(tmp_path / "math-scenario-scalar")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "affine_flux": {
                            "kind": "expression",
                            "expected": "-90*pi-18*sqrt(3)*pi",
                            "variables": [],
                        },
                        "frustum_flux": {
                            "kind": "expression",
                            "expected": "-260*pi/3-16*sqrt(3)*pi",
                            "variables": [],
                        },
                    }
                },
            }
        ],
    }
    answer = json.dumps(
        {
            "affine_flux": (
                "Φ_circle(H)=2π[H³(tr(M)/3−eᵀMe)−H²(e·c)]；"
                "固定 H>0 时 Φ_circle=0 当且仅当 H(tr(M)−3eᵀMe)=3(e·c)。"
                "给定数据 H=3 时为 −90π−18π√3。"
            ),
            "frustum_flux": (
                "Φ_frustum(a,b,L,H)=πab[(H³−L³)(tr(M)/3−eᵀMe)"
                "−(H²−L²)(e·c)]。"
                "给定 H=3、L=1、a=2、b=1 时为 −260π/3−16π√3。"
            ),
        },
        ensure_ascii=False,
    )

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=answer,
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"] == {
        "affine_flux": 100.0,
        "frustum_flux": 100.0,
    }


def test_symbolic_anchor_treats_bare_decimal_as_exact_scalar(tmp_path):
    workspace = Workspace(tmp_path / "math-exact-decimal")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "explicit_kappa_max": {
                            "kind": "expression",
                            "expected": "21/8",
                            "variables": [],
                        }
                    }
                },
            }
        ],
    }

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=json.dumps({"explicit_kappa_max": 2.625}),
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"]["explicit_kappa_max"] == 100


def test_symbolic_anchor_extracts_hidden_parameter_scalar_specializations(tmp_path):
    workspace = Workspace(tmp_path / "math-parameter-specializations")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "alpha_case_mean": {
                            "kind": "expression",
                            "expected": "100",
                            "variables": [],
                        },
                        "alpha_case_variance": {
                            "kind": "expression",
                            "expected": "40000",
                            "variables": [],
                        },
                        "alpha_case_tail_constant": {
                            "kind": "expression",
                            "expected": "8000000",
                            "variables": [],
                        },
                        "second_order_tail_coefficient": {
                            "kind": "expression",
                            "expected": "-2400000000",
                            "variables": [],
                        },
                    }
                },
            }
        ],
    }
    answer = json.dumps(
        {
            "alpha_case_mean": (
                "0<α≤1时E[S]=+∞；α>1时E[S]=800·2^(1−α)/(α−1)；"
                "α=3时E[S]=100。"
            ),
            "alpha_case_variance": (
                "1<α≤2时Var(S)不有限；α>2时Var(S)=80000·2^(3−α)/"
                "[(α−1)(α−2)]；α=3时Var(S)=40000。"
            ),
            "alpha_case_tail_constant": (
                "P(S>x)~8·100^α·x^(−α)，故尾常数为8·100^α；"
                "α=3时为8000000。"
            ),
            "second_order_tail_coefficient": (
                "α>2时C2=8α·100^α[800·2^(1−α)/(α−1)−200]；"
                "α=3时C2=−2400000000。"
            ),
        },
        ensure_ascii=False,
    )

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=answer,
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert set(anchor.evidence["field_scores"].values()) == {100.0}


def test_symbolic_anchor_normalizes_unicode_subscripts_in_literal(tmp_path):
    workspace = Workspace(tmp_path / "math-literal-unicode-subscript")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "jordan_type": {
                            "kind": "literal",
                            "expected": "J2(1)+J1(1)",
                            "accepted": ["J2(1)⊕J1(1)"],
                        }
                    }
                },
            }
        ],
    }

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=json.dumps(
            {"jordan_type": "J₂(1)⊕J₁(1)"}, ensure_ascii=False
        ),
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"]["jordan_type"] == 100


def test_symbolic_anchor_ignores_equation_inside_parenthetical_annotation(tmp_path):
    workspace = Workspace(tmp_path / "math-parenthetical-equation")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "poisson_lambda": {
                            "kind": "expression",
                            "expected": "2",
                            "variables": [],
                        }
                    }
                },
            }
        ],
    }

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=json.dumps(
            {
                "poisson_lambda": (
                    "2（即 M ~ Poisson(2)，λ_M = 8 × 1/4 = 2）"
                )
            },
            ensure_ascii=False,
        ),
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"]["poisson_lambda"] == 100


def test_symbolic_anchor_accepts_explanatory_structured_math_fields(tmp_path):
    workspace = Workspace(tmp_path / "math-explanatory-fields")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "beta_coefficient": {
                            "kind": "expression",
                            "expected": "-x-y+2*z",
                            "variables": ["x", "y", "z"],
                        },
                        "nonzero_constraint": {
                            "kind": "expression",
                            "expected": "a1+a2-2*a3",
                            "variables": ["a1", "a2", "a3"],
                            "equivalent_up_to_nonzero_scalar": True,
                        },
                        "minimal_polynomial": {
                            "kind": "expression",
                            "expected": "(t-1)**2",
                            "variables": ["t"],
                        },
                        "jordan_type": {
                            "kind": "literal",
                            "expected": "J2(1)+J1(1)",
                            "accepted": ["J_2(1)⊕J_1(1)"],
                        },
                    }
                },
            }
        ],
    }
    answer = json.dumps(
        {
            "beta_coefficient": (
                "令 α=(x,y,z)^T，则 β=c(1,1,1)^T，其中 c=-x-y+2z。"
            ),
            "nonzero_constraint": (
                "α 为任意满足 x1+x2-2x3≠0 的向量；该条件保证 β≠0。"
                "等价地：β=c(1,1,1)^T（c≠0），α 取遍平面 -x1-x2+2x3=c 上的所有向量"
            ),
            "minimal_polynomial": "m(λ) = (λ - 1)^2",
            "jordan_type": "J = J_2(1)⊕J_1(1)，即 Jordan 块大小为 2 和 1",
        },
        ensure_ascii=False,
    )

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=answer,
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"] == {
        "beta_coefficient": 100.0,
        "nonzero_constraint": 100.0,
        "minimal_polynomial": 100.0,
        "jordan_type": 100.0,
    }
    assert (
        anchor.evidence["field_evidence"]["jordan_type"]["method"]
        == "literal_explanatory_suffix"
    )


def test_symbolic_anchor_maps_indexed_coordinates_by_suffix(tmp_path):
    workspace = Workspace(tmp_path / "math-indexed-coordinate-order")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "beta_coefficient": {
                            "kind": "expression",
                            "expected": "2*a3-a1-a2",
                            "variables": ["a1", "a2", "a3"],
                        },
                        "jordan_type": {
                            "kind": "literal",
                            "expected": "J2(1)+J1(1)",
                            "accepted": ["J2(1)⊕J1(1)"],
                        },
                    }
                },
            }
        ],
    }
    answer = json.dumps(
        {
            "beta_coefficient": (
                "令 α=(x1,x2,x3)^T，β=c(1,1,1)^T，其中 c=2x3-x1-x2"
            ),
            "jordan_type": "J = J2(1) ⊕ J1(1)，即 Jordan 块大小为 2 和 1",
        },
        ensure_ascii=False,
    )

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=answer,
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=10,
        tokens_output=10,
    )

    anchor = next(
        item for item in score.components if item.validator_type == "symbolic_json"
    )
    assert anchor.score == 100
    assert anchor.evidence["field_scores"] == {
        "beta_coefficient": 100.0,
        "jordan_type": 100.0,
    }


def test_symbolic_anchor_accepts_unicode_greek_subscripts_and_fullwidth_domain(tmp_path):
    workspace = Workspace(tmp_path / "math-unicode-notation")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "metadata": {"score_basis": "quality_only"},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "coefficient": {
                            "kind": "expression",
                            "expected": "2*a3-a1-a2",
                            "variables": ["a1", "a2", "a3"],
                        },
                        "function": {
                            "kind": "expression",
                            "expected": "u+log(u)+log(u)**2/2",
                            "variables": ["u"],
                        },
                    }
                },
            }
        ],
    }
    answer = json.dumps(
        {
            "coefficient": "2α₃−α₁−α₂（α₁>0）",
            "function": "u+ln u+(ln u)^2/2（u>0，唯一）",
        },
        ensure_ascii=False,
    )
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer=answer,
        workspace=workspace,
        steps=1,
        duration_ms=1,
        tokens_input=0,
        tokens_output=0,
    )
    anchor = next(item for item in score.components if item.validator_type == "symbolic_json")
    assert anchor.score == 100
    assert anchor.evidence["field_scores"] == {"coefficient": 100.0, "function": 100.0}


def test_frontier_mastery_curve_reserves_top_band_for_near_complete_work():
    assert _apply_mastery_curve(0, "frontier_v1") == 0
    assert _apply_mastery_curve(80, "frontier_v1") == 67
    assert _apply_mastery_curve(90, "frontier_v1") == 80
    assert _apply_mastery_curve(95, "frontier_v1") == 89
    assert _apply_mastery_curve(100, "frontier_v1") == 100
    assert _apply_mastery_curve(83, "unknown") == 83


def test_file_validator(tmp_path):
    workspace = Workspace(tmp_path / "run")
    workspace.write_file("result.txt", "done")
    definition = {
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {"type": "file_exists", "weight": 40, "config": {"path": "result.txt"}},
            {
                "type": "file_content",
                "weight": 50,
                "config": {"path": "result.txt", "expected": "done"},
            },
        ],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=2,
        duration_ms=20_000,
        tokens_input=200,
        tokens_output=50,
    )
    assert score.score == 99.6


def test_private_command_validator_is_injected_then_removed(tmp_path):
    workspace = Workspace(tmp_path / "private-run")

    class FakeDocker:
        def run(self, target, command, _image, **_kwargs):
            private_path = command.split()[-1]
            assert private_path.startswith(".agentbench-private-")
            assert target.read_file(private_path) == "print('private')\n"
            return CommandResult(True, 0, "ok", "", 5)

    definition = {
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {
                "type": "command",
                "weight": 90,
                "config": {
                    "command": "python {private_root}/verify.py",
                    "private_files": {"verify.py": "print('private')\n"},
                },
            }
        ],
    }
    score = ScoringEngine(FakeDocker()).score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
    )

    assert score.status == "scored"
    assert not any(path.startswith(".agentbench-private-") for path in workspace.list_files())


def test_private_metric_validator_returns_continuous_components(tmp_path):
    workspace = Workspace(tmp_path / "metric-run")

    class FakeDocker:
        def run(self, _target, _command, _image, **_kwargs):
            return CommandResult(
                True,
                0,
                'AGENTBENCH_METRICS={"metrics":{"correctness":72.5,"quality":91},"evidence":{"correctness":"partial"}}\n',
                "",
                5,
            )

    definition = {
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {
                "type": "command_metrics",
                "weight": 100,
                "config": {
                    "command": "python {private_root}/verify.py",
                    "private_files": {"verify.py": "print('unused')\n"},
                    "metrics": [
                        {"key": "correctness", "name": "约束正确性", "weight": 70},
                        {"key": "quality", "name": "解质量", "weight": 30},
                    ],
                },
            }
        ],
    }
    score = ScoringEngine(FakeDocker()).score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
    )

    assert score.status == "scored"
    assert [item.validator_type for item in score.components[:2]] == ["约束正确性", "解质量"]
    assert [item.score for item in score.components[:2]] == [72.5, 91.0]
    assert not any(path.startswith(".agentbench-private-") for path in workspace.list_files())


def test_private_metric_mastery_cap_triggers_only_below_threshold(tmp_path):
    workspace = Workspace(tmp_path / "metric-cap-run")

    class FakeDocker:
        metric_score = 99

        def run(self, _target, _command, _image, **_kwargs):
            return CommandResult(
                    True,
                    0,
                    f'AGENTBENCH_METRICS={{"metrics":{{"critical":{self.metric_score},'
                    '"secondary":100}}\n',
                    "",
                    5,
                )

    docker = FakeDocker()
    definition = {
        "metadata": {"score_basis": "quality_only"},
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {
                "type": "command_metrics",
                "weight": 100,
                "config": {
                    "command": "python {private_root}/verify.py",
                    "private_files": {"verify.py": "print('unused')\n"},
                    "metrics": [
                        {"key": "critical", "weight": 50},
                        {"key": "secondary", "weight": 50},
                    ],
                    "metric_caps": [
                        {
                            "metric_key": "critical",
                            "min_score": 100,
                            "max_score": 70,
                            "reason": "critical capability incomplete",
                        }
                    ],
                },
            }
        ],
    }
    engine = ScoringEngine(docker)

    capped = engine.score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
    )
    assert capped.score == 70
    gate = next(item for item in capped.components if item.validator_type == "hard_gate")
    assert gate.evidence["failures"][0]["key"] == "critical_below_mastery"

    docker.metric_score = 100
    uncapped = engine.score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
    )
    assert uncapped.score == 100
    assert not any(item.validator_type == "hard_gate" for item in uncapped.components)


def test_quality_only_profile_ignores_time_steps_and_tokens(tmp_path):
    workspace = Workspace(tmp_path / "quality-only")
    definition = {
        "metadata": {"score_basis": "quality_only"},
        "limits": {
            "max_steps": 1,
            "time_target_seconds": 1,
            "token_budget": 1,
        },
        "validators": [
            {"type": "exact_match", "weight": 100, "config": {"expected": "OK"}}
        ],
    }

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=999,
        duration_ms=999_000,
        tokens_input=999_000,
        tokens_output=999_000,
    )

    assert score.score == 100
    efficiency = {
        item.validator_type: item.weight
        for item in score.components
        if item.validator_type.endswith("_efficiency")
    }
    assert efficiency == {
        "time_efficiency": 0,
        "step_efficiency": 0,
        "token_efficiency": 0,
    }


def _research_definition(*, min_claims: int = 2) -> dict:
    return {
        "metadata": {"score_basis": "quality_only"},
        "limits": {"max_steps": 10, "token_budget": 1000},
        "initial_files": {
            "S1_capacity.md": "[p1] 可实施屋面为 420 万平方米。\n",
            "S2_budget.md": "[p1] 五年预算为 4,000 万元。\n",
        },
        "validators": [
            {
                "type": "research_claims",
                "weight": 10,
                "config": {
                    "report_path": "report.md",
                    "claims_path": "claims.json",
                    "min_claims": min_claims,
                },
            },
            {"type": "ai_rubric", "weight": 90, "config": {"criteria": ["quality"]}},
        ],
    }


def _score_research(tmp_path, claims: list[dict], report: str, *, min_claims: int = 2):
    workspace = Workspace(tmp_path)
    workspace.write_file("report.md", report)
    workspace.write_file("claims.json", json.dumps({"claims": claims}, ensure_ascii=False))
    return ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=_research_definition(min_claims=min_claims),
        final_answer="done",
        workspace=workspace,
        steps=999,
        duration_ms=999_000,
        tokens_input=999_000,
        tokens_output=999_000,
        judge_callback=lambda _config, weight: ValidationResult(
            "ai_rubric", weight, 100, "passed", {"judge": "optimistic"}
        ),
    )


def test_research_claims_accepts_valid_pages_and_numeric_facts(tmp_path):
    score = _score_research(
        tmp_path / "valid",
        [
            {
                "claim": "可实施屋面为 420 万平方米",
                "citations": ["S1:p1"],
                "type": "fact",
                "confidence": "high",
            },
            {
                "claim": "五年预算为 4,000 万元",
                "citations": ["S2:p1"],
                "type": "fact",
                "confidence": "high",
            },
        ],
        "容量为 420 万平方米 [S1:p1]，预算为 4,000 万元 [S2:p1]。",
    )

    assert score.score == 100
    audit = next(item for item in score.components if item.validator_type == "research_claims")
    assert audit.evidence["components"] == {
        "schema": 100.0,
        "coverage": 100.0,
        "citations": 100.0,
        "numeric_fidelity": 100.0,
    }


def test_research_claims_accepts_top_level_claims_array(tmp_path):
    workspace = Workspace(tmp_path / "top-level-array")
    definition = _research_definition(min_claims=2)
    claims = [
        {
            "claim": "可实施屋面为 420 万平方米",
            "citations": ["[S1:p1]"],
            "type": "fact",
            "confidence": "高",
        },
        {
            "claim": "五年预算为 4,000 万元",
            "citations": ["[S2:p1]"],
            "type": "policy",
            "confidence": "中高",
        },
    ]
    workspace.write_file(
        "report.md",
        "容量为 420 万平方米 [S1:p1]，预算为 4,000 万元 [S2:p1]。",
    )
    workspace.write_file("claims.json", json.dumps(claims, ensure_ascii=False))

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="done",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
        judge_callback=lambda _config, weight: ValidationResult(
            "ai_rubric", weight, 100, "passed", {"judge": "test"}
        ),
    )

    audit = next(item for item in score.components if item.validator_type == "research_claims")
    assert score.score == 100
    assert audit.status == "passed"
    assert audit.evidence["claims"] == 2


def test_research_claims_treats_trailing_decimal_zero_as_equivalent(tmp_path):
    workspace = Workspace(tmp_path / "decimal-equivalence")
    definition = _research_definition(min_claims=1)
    definition["initial_files"] = {
        "S1_terms.md": "[p1] 收购报价为 6.2 亿美元。\n"
    }
    workspace.write_file("report.md", "收购报价为 6.20 亿美元 [S1:p1]。")
    workspace.write_file(
        "claims.json",
        json.dumps(
            {
                "claims": [
                    {
                        "claim": "收购报价为 6.20 亿美元",
                        "citations": ["S1:p1"],
                        "type": "fact",
                        "confidence": "high",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="done",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
        judge_callback=lambda _config, weight: ValidationResult(
            "ai_rubric", weight, 100, "passed", {"judge": "test"}
        ),
    )

    audit = next(item for item in score.components if item.validator_type == "research_claims")
    assert audit.evidence["numeric_mismatches"] == []
    assert audit.evidence["components"]["numeric_fidelity"] == 100


def test_research_claims_includes_document_header_metadata_in_page_citation(tmp_path):
    workspace = Workspace(tmp_path / "header-metadata")
    definition = _research_definition(min_claims=1)
    definition["initial_files"] = {
        "S1_board.md": (
            "# S1 · 董事会材料（2026-06-18）\n\n"
            "[p1] 2025 ARR 为 4,800 万美元，同比增长 41%。\n"
        )
    }
    workspace.write_file("report.md", "董事会材料披露 ARR [S1:p1]。")
    workspace.write_file(
        "claims.json",
        json.dumps(
            {
                "claims": [
                    {
                        "claim": "董事会材料（2026-06-18）载明 2025 ARR 为 4,800 万美元",
                        "citations": ["S1:p1"],
                        "type": "fact",
                        "confidence": "high",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="done",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
        judge_callback=lambda _config, weight: ValidationResult(
            "ai_rubric", weight, 100, "passed", {"judge": "test"}
        ),
    )

    audit = next(item for item in score.components if item.validator_type == "research_claims")
    assert audit.evidence["numeric_mismatches"] == []


def test_research_claims_accepts_recomputable_cited_percentage(tmp_path):
    workspace = Workspace(tmp_path / "derived-percentage")
    definition = _research_definition(min_claims=1)
    definition["initial_files"] = {
        "S1_interviews.md": "[p1] 47 名受访者中 31 人表示担忧。\n"
    }
    workspace.write_file("report.md", "31 名受访者表示担忧 [S1:p1]。")
    workspace.write_file(
        "claims.json",
        json.dumps(
            {
                "claims": [
                    {
                        "claim": "47 名受访者中 31 人表示担忧（占 66.0%）",
                        "citations": ["S1:p1"],
                        "type": "fact",
                        "confidence": "high",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="done",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
        judge_callback=lambda _config, weight: ValidationResult(
            "ai_rubric", weight, 100, "passed", {"judge": "test"}
        ),
    )

    audit = next(item for item in score.components if item.validator_type == "research_claims")
    assert audit.evidence["numeric_mismatches"] == []
    assert audit.evidence["derived_numeric_claims"] == [
        {
            "claim_index": 0,
            "numbers": ["66"],
            "method": "cited_ratio_percentage",
            "citations": ["S1:P1"],
        }
    ]


def test_research_claims_invalid_page_caps_optimistic_judge_at_65(tmp_path):
    score = _score_research(
        tmp_path / "bad-page",
        [
            {
                "claim": "容量约束需要复核",
                "citations": ["S1:p9"],
                "type": "inference",
                "confidence": "medium",
            }
        ],
        "给定资料记载容量为 420 万平方米 [S1:p1]。",
        min_claims=1,
    )

    assert score.score == 65
    gate = next(item for item in score.components if item.validator_type == "hard_gate")
    assert {item["key"] for item in gate.evidence["failures"]} == {
        "research_invalid_citation"
    }


def test_research_claims_numeric_mismatch_caps_optimistic_judge_at_75(tmp_path):
    score = _score_research(
        tmp_path / "bad-number",
        [
            {
                "claim": "可实施屋面为 4,200 万平方米",
                "citations": ["S1:p1"],
                "type": "fact",
                "confidence": "high",
            }
        ],
        "来源实际写明 420 万平方米 [S1:p1]。",
        min_claims=1,
    )

    assert score.score == 75
    audit = next(item for item in score.components if item.validator_type == "research_claims")
    assert audit.evidence["numeric_mismatches"][0]["numbers"] == ["4200"]


def test_missing_private_metric_protocol_is_platform_failure(tmp_path):
    workspace = Workspace(tmp_path / "metric-platform-run")

    class FakeDocker:
        def run(self, _target, _command, _image, **_kwargs):
            return CommandResult(False, 1, "", "validator bootstrap failed", 5)

    definition = {
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {
                "type": "command_metrics",
                "weight": 100,
                "config": {
                    "command": "python {private_root}/verify.py",
                    "private_files": {"verify.py": "broken"},
                    "metrics": [{"key": "quality", "weight": 100}],
                },
            }
        ],
    }
    score = ScoringEngine(FakeDocker()).score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
    )

    assert score.status == "environment_unavailable"
    assert score.components[0].evidence["error_code"] == "validator_platform_error"


def test_private_metric_timeout_is_candidate_failure(tmp_path):
    workspace = Workspace(tmp_path / "metric-timeout-run")

    class TimeoutDocker:
        def run(self, _target, _command, _image, **_kwargs):
            return CommandResult(False, None, "", "Command timed out", 1000, "command_timeout")

    definition = {
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {
                "type": "command_metrics",
                "weight": 100,
                "config": {
                    "command": "python {private_root}/verify.py",
                    "private_files": {"verify.py": "broken"},
                    "metrics": [{"key": "quality", "weight": 100}],
                },
            }
        ],
    }
    score = ScoringEngine(TimeoutDocker()).score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=1,
        duration_ms=1000,
        tokens_input=1,
        tokens_output=1,
    )

    assert score.status == "scored"
    assert score.components[0].validator_type == "quality"
    assert score.components[0].score == 0
    assert score.components[0].status == "failed"


def test_partial_text_score_is_continuous(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "timeout_seconds": 100, "token_budget": 1000},
        "validators": [
            {"type": "exact_match", "weight": 90, "config": {"expected": "READY-001"}}
        ],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="READY-002",
        workspace=workspace,
        steps=3,
        duration_ms=30_000,
        tokens_input=300,
        tokens_output=50,
    )
    assert score.status == "scored"
    assert 40 < score.score < 65
    assert score.components[0].status == "partial"
    assert 0 < score.components[0].score < 100


def test_json_file_scores_fields_and_accepts_utf8_bom(tmp_path):
    workspace = Workspace(tmp_path / "run")
    workspace.write_file(
        "deliverables/report.json",
        '\ufeff{"total": 12, "region": "west", "refunds": 2}',
    )
    definition = {
        "limits": {"max_steps": 10, "timeout_seconds": 100, "token_budget": 1000},
        "validators": [
            {
                "type": "json_file",
                "weight": 95,
                "config": {
                    "path": "deliverables/report.json",
                    "expected": {
                        "total": 12,
                        "region": "west",
                        "refunds": 2,
                        "high_value": 4,
                    },
                },
            }
        ],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="done",
        workspace=workspace,
        steps=4,
        duration_ms=25_000,
        tokens_input=250,
        tokens_output=50,
    )
    objective = next(
        item for item in score.dimensions if item.validator_type == "objective_quality"
    )
    assert objective.score == 75
    assert score.components[0].evidence["field_scores"]["high_value"] == 0


def test_time_has_small_but_visible_weight(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "timeout_seconds": 100, "token_budget": 1000},
        "validators": [{"type": "exact_match", "weight": 100, "config": {"expected": "OK"}}],
    }
    engine = ScoringEngine(DockerExecutor(executable="missing-docker"))
    fast = engine.score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=10_000,
        tokens_input=200,
        tokens_output=50,
    )
    slow = engine.score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=400_000,
        tokens_input=200,
        tokens_output=50,
    )
    assert 0 < fast.score - slow.score <= 3
    time_component = next(
        item for item in fast.components if item.validator_type == "time_efficiency"
    )
    assert time_component.weight == 3


def test_time_target_is_soft_and_uses_logarithmic_penalty(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "time_target_seconds": 100, "token_budget": 1000},
        "validators": [{"type": "exact_match", "weight": 100, "config": {"expected": "OK"}}],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=400_000,
        tokens_input=200,
        tokens_output=50,
    )
    time_component = next(
        item for item in score.components if item.validator_type == "time_efficiency"
    )

    assert score.status == "scored"
    assert time_component.score == 75
    assert time_component.evidence["target_exceeded"] is True
    assert time_component.evidence["elapsed_multiple"] == 4
    assert score.score > 98


def test_token_efficiency_uses_small_weight_and_missing_usage_is_neutral(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "timeout_seconds": 100, "token_budget": 1000},
        "validators": [{"type": "exact_match", "weight": 100, "config": {"expected": "OK"}}],
    }
    engine = ScoringEngine(DockerExecutor(executable="missing-docker"))
    efficient = engine.score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=10_000,
        tokens_input=200,
        tokens_output=50,
    )
    unreported = engine.score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=10_000,
        tokens_input=0,
        tokens_output=0,
    )
    efficient_component = next(
        item for item in efficient.components if item.validator_type == "token_efficiency"
    )
    neutral_component = next(
        item for item in unreported.components if item.validator_type == "token_efficiency"
    )
    assert efficient_component.weight == 1
    assert efficient_component.score == 100
    assert neutral_component.score == 50
    assert efficient.score - unreported.score == 0.5


def test_token_efficiency_reports_and_penalizes_soft_budget_overrun(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "timeout_seconds": 100, "token_budget": 1000},
        "validators": [{"type": "exact_match", "weight": 100, "config": {"expected": "OK"}}],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=10_000,
        tokens_input=1200,
        tokens_output=50,
    )
    component = next(
        item for item in score.components if item.validator_type == "token_efficiency"
    )

    assert score.status == "scored"
    assert component.score == 0
    assert component.evidence["budget_used_percent"] == 125
    assert component.evidence["budget_exceeded"] is True
    assert component.evidence["over_budget_tokens"] == 250
    assert "软预算" in component.evidence["note"]
