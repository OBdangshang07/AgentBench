from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MATH_EXAM_ID = "postgraduate-math-1"
MAX_PDF_BYTES = 80 * 1024 * 1024
QUESTION_RE = re.compile(r"(?m)^\s*(?:第\s*)?(\d{1,2})\s*[.、．)]\s*")


def _question_type(number: int) -> str:
    if number <= 10:
        return "choice"
    if number <= 16:
        return "fill"
    return "solution"


def _question_points(number: int) -> int:
    if number <= 16:
        return 5
    return 20 if number == 22 else 10


def _rubric_template(number: int) -> dict[str, Any]:
    kind = _question_type(number)
    if kind == "choice":
        return {
            "response_schema": {"answer": "A|B|C|D"},
            "validators": [
                {
                    "type": "symbolic_json",
                    "weight": 100,
                    "config": {
                        "fields": {
                            "answer": {
                                "kind": "literal",
                                "expected": None,
                                "accepted": [],
                                "weight": 1,
                            }
                        }
                    },
                }
            ],
        }
    if kind == "fill":
        return {
            "response_schema": {"answer": "symbolic expression"},
            "validators": [
                {
                    "type": "symbolic_json",
                    "weight": 100,
                    "config": {
                        "fields": {
                            "answer": {
                                "kind": "expression",
                                "expected": None,
                                "variables": ["x"],
                                "weight": 1,
                            }
                        }
                    },
                }
            ],
        }
    return {
        "response_schema": {
            "final_answer": "symbolic expression or literal conclusion",
            "solution": "auditable derivation",
        },
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 40,
                "config": {
                    "fields": {
                        "final_answer": {
                            "kind": "expression",
                            "expected": None,
                            "variables": ["x"],
                            "weight": 1,
                        }
                    }
                },
            },
            {
                "type": "ai_rubric",
                "weight": 60,
                "config": {
                    "dimensions": [
                        "建模或定理选择正确",
                        "关键变换与中间结论有效",
                        "使用条件、定义域、边界或分支完整",
                        "推导可复核且最终结论一致",
                    ],
                    "alternate_solutions": (
                        "允许参考答案之外的等价解法；若逻辑有效且结论正确，不得因路径不同扣分。"
                    ),
                    "error_carry_forward": (
                        "前一步独立错误导致的后续机械结果不重复扣分；保留此前正确方法分。"
                    ),
                },
            },
        ],
    }


def build_question_drafts(page_texts: list[str]) -> list[dict[str, Any]]:
    detected: dict[int, dict[str, Any]] = {}
    current_number: int | None = None
    for page_number, text in enumerate(page_texts, 1):
        matches = list(QUESTION_RE.finditer(text))
        if not matches and current_number is not None:
            detected[current_number]["question_text"] += "\n" + text.strip()
            detected[current_number]["source_pages"] = sorted(
                {*detected[current_number]["source_pages"], page_number}
            )
            continue
        for index, match in enumerate(matches):
            number = int(match.group(1))
            if not 1 <= number <= 22:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            content = text[match.end():end].strip()
            detected[number] = {
                "question_text": content,
                "source_pages": [page_number],
                "detection_confidence": "medium" if len(content) >= 20 else "low",
            }
            current_number = number

    drafts: list[dict[str, Any]] = []
    for number in range(1, 23):
        found = detected.get(number, {})
        drafts.append(
            {
                "number": number,
                "type": _question_type(number),
                "points": _question_points(number),
                "question_text": found.get("question_text", ""),
                "source_pages": found.get("source_pages", []),
                "detection_confidence": found.get("detection_confidence", "missing"),
                "answer": None,
                "accepted_answers": [],
                "solution_obligations": [],
                "rubric": _rubric_template(number),
                "review_status": "needs_review",
            }
        )
    return drafts


def import_math_pdf(
    data_dir: Path,
    *,
    filename: str,
    content: bytes,
    year: int = 2025,
) -> dict[str, Any]:
    if not filename.lower().endswith(".pdf"):
        raise ValueError("math_paper_must_be_pdf")
    if not content.startswith(b"%PDF-"):
        raise ValueError("invalid_pdf_signature")
    if len(content) > MAX_PDF_BYTES:
        raise ValueError("math_paper_too_large")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - packaging regression guard
        raise RuntimeError("pypdf_not_installed") from exc

    reader = PdfReader(io.BytesIO(content), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("encrypted_pdf_requires_password_free_copy") from exc
    page_texts: list[str] = []
    warnings: list[str] = []
    for page_number, page in enumerate(reader.pages, 1):
        try:
            extracted = (page.extract_text() or "").replace("\x00", "").strip()
        except Exception:
            extracted = ""
        page_texts.append(extracted)
        if len(extracted) < 20:
            warnings.append(f"第 {page_number} 页文本很少，可能需要 OCR 或公式人工校对")

    import_id = str(uuid.uuid4())
    target_dir = (data_dir / "math-papers" / import_id).resolve()
    target_dir.mkdir(parents=True, exist_ok=False)
    source_path = target_dir / "source.pdf"
    source_path.write_bytes(content)
    questions = build_question_drafts(page_texts)
    detected_count = sum(bool(item["question_text"]) for item in questions)
    if detected_count < 22:
        warnings.append(f"自动识别到 {detected_count}/22 道题，缺失题目必须人工补录")
    manifest = {
        "id": import_id,
        "status": "needs_review",
        "exam": MATH_EXAM_ID,
        "year": year,
        "title": f"{year} 年全国硕士研究生招生考试数学（一）",
        "created_at": datetime.now(UTC).isoformat(),
        "source": {
            "filename": Path(filename).name,
            "local_path": str(source_path),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "page_count": len(page_texts),
        },
        "score_structure": {
            "total": 150,
            "choice": {"questions": [1, 10], "points": 50},
            "fill": {"questions": [11, 16], "points": 30},
            "solution": {"questions": [17, 22], "points": 70},
        },
        "lanes": [
            {
                "id": "closed-book",
                "name": "闭卷推理",
                "tools": [],
                "native_agent_compatible": False,
                "note": "仅统一 Agent 可技术性禁用工具；原生 CLI 不进入本赛道正式榜单。",
            },
            {
                "id": "tool-augmented",
                "name": "工具增强",
                "tools": ["filesystem", "search", "shell"],
                "native_agent_compatible": True,
            },
        ],
        "questions": questions,
        "pages": [
            {"page": index, "text": text, "char_count": len(text)}
            for index, text in enumerate(page_texts, 1)
        ],
        "warnings": warnings,
        "review_requirements": [
            "逐题核对题号、公式、图形、分值与来源页",
            "录入官方答案并补充至少一种等价解法回归样例",
            "解答题拆分证明义务、典型错误与误差延续规则",
            "所有题目确认后方可生成正式测试套件与榜单",
        ],
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def list_math_imports(data_dir: Path) -> list[dict[str, Any]]:
    root = data_dir / "math-papers"
    if not root.is_dir():
        return []
    output: list[dict[str, Any]] = []
    for manifest_path in root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        output.append(
            {
                "id": manifest.get("id"),
                "status": manifest.get("status"),
                "exam": manifest.get("exam"),
                "year": manifest.get("year"),
                "title": manifest.get("title"),
                "created_at": manifest.get("created_at"),
                "source": manifest.get("source"),
                "warnings": manifest.get("warnings", []),
                "detected_questions": sum(
                    bool(item.get("question_text")) for item in manifest.get("questions", [])
                ),
                "confirmed_questions": sum(
                    item.get("review_status") == "confirmed"
                    for item in manifest.get("questions", [])
                ),
                "published_suites": manifest.get("published_suites", []),
            }
        )
    return sorted(output, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def get_math_import(data_dir: Path, import_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f-]{36}", import_id):
        raise FileNotFoundError(import_id)
    root = (data_dir / "math-papers").resolve()
    manifest_path = (root / import_id / "manifest.json").resolve()
    if not manifest_path.is_relative_to(root) or not manifest_path.is_file():
        raise FileNotFoundError(import_id)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _write_manifest(data_dir: Path, manifest: dict[str, Any]) -> None:
    import_id = str(manifest.get("id") or "")
    root = (data_dir / "math-papers").resolve()
    manifest_path = (root / import_id / "manifest.json").resolve()
    if not manifest_path.is_relative_to(root) or not manifest_path.is_file():
        raise FileNotFoundError(import_id)
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(manifest_path)


def update_math_question(
    data_dir: Path,
    import_id: str,
    number: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    manifest = get_math_import(data_dir, import_id)
    if manifest.get("status") == "published":
        raise ValueError("published_math_paper_is_immutable")
    if not 1 <= number <= 22:
        raise ValueError("invalid_math_question_number")
    question = next(
        (item for item in manifest.get("questions", []) if item.get("number") == number),
        None,
    )
    if question is None:
        raise ValueError("math_question_not_found")
    allowed = {
        "question_text",
        "answer",
        "accepted_answers",
        "variables",
        "solution_obligations",
        "review_status",
    }
    for key, value in changes.items():
        if key not in allowed:
            continue
        if isinstance(value, str):
            value = value.strip()
        elif isinstance(value, list):
            value = [str(item).strip() for item in value if str(item).strip()]
        question[key] = value

    if changes.get("review_status") == "confirmed":
        if not str(question.get("question_text") or "").strip():
            raise ValueError("confirmed_question_requires_text")
        if not str(question.get("answer") or "").strip():
            raise ValueError("confirmed_question_requires_answer")
        if question.get("type") == "solution" and not question.get("solution_obligations"):
            raise ValueError("confirmed_solution_requires_obligations")
    all_confirmed = len(manifest.get("questions", [])) == 22 and all(
        item.get("review_status") == "confirmed" for item in manifest.get("questions", [])
    )
    manifest["status"] = "ready_to_publish" if all_confirmed else "needs_review"
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    _write_manifest(data_dir, manifest)
    return manifest


def validate_publishable_math_import(manifest: dict[str, Any]) -> None:
    questions = manifest.get("questions") or []
    if len(questions) != 22:
        raise ValueError("math_paper_requires_22_questions")
    for question in questions:
        number = int(question.get("number") or 0)
        if question.get("review_status") != "confirmed":
            raise ValueError(f"math_question_{number}_not_confirmed")
        if not str(question.get("question_text") or "").strip():
            raise ValueError(f"math_question_{number}_missing_text")
        if not str(question.get("answer") or "").strip():
            raise ValueError(f"math_question_{number}_missing_answer")
        if question.get("type") == "solution" and not question.get("solution_obligations"):
            raise ValueError(f"math_question_{number}_missing_obligations")


def build_published_math_cases(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    validate_publishable_math_import(manifest)
    source = manifest["source"]
    year = int(manifest["year"])
    source_hash = str(source["sha256"])
    case_version = f"{year}.1.{source_hash[:8]}"
    output: dict[str, list[dict[str, Any]]] = {"closed-book": [], "tool-augmented": []}
    for lane in output:
        for question in manifest["questions"]:
            number = int(question["number"])
            kind = str(question["type"])
            accepted = list(question.get("accepted_answers") or [])
            variables = list(question.get("variables") or [])
            if kind == "choice":
                fields = {
                    "answer": {
                        "kind": "literal",
                        "expected": question["answer"],
                        "accepted": accepted,
                        "weight": 1,
                    }
                }
                validators = [{"type": "symbolic_json", "weight": 100, "config": {"fields": fields}}]
                response_rule = '{"answer":"A"}'
            elif kind == "fill":
                fields = {
                    "answer": {
                        "kind": "expression",
                        "expected": question["answer"],
                        "accepted": accepted,
                        "variables": variables,
                        "weight": 1,
                    }
                }
                validators = [{"type": "symbolic_json", "weight": 100, "config": {"fields": fields}}]
                response_rule = '{"answer":"化简后的最终表达式"}'
            else:
                answer_kind = str(question.get("answer_kind") or "expression")
                objective_weight = max(0, min(100, int(question.get("objective_weight", 40))))
                fields = {
                    "final_answer": {
                        "kind": answer_kind,
                        "expected": question["answer"],
                        "accepted": accepted,
                        "variables": variables,
                        "weight": 1,
                    }
                }
                validators = []
                if objective_weight:
                    validators.append(
                        {
                            "type": "symbolic_json",
                            "weight": objective_weight,
                            "config": {"fields": fields},
                        }
                    )
                validators.append(
                    {
                        "type": "ai_rubric",
                        "weight": 100 - objective_weight,
                        "config": {
                            "reference_answer": question["answer"],
                            "accepted_answers": accepted,
                            "solution_obligations": question.get("solution_obligations") or [],
                            "dimensions": [
                                "建模或定理选择正确",
                                "关键变换与中间结论有效",
                                "使用条件、定义域、边界或分支完整",
                                "推导可复核且最终结论一致",
                            ],
                            "alternate_solutions": "允许任意逻辑有效的等价解法，不得因路径不同扣分。",
                            "error_carry_forward": "前一步独立错误导致的后续机械结果不重复扣分，保留此前正确方法分。",
                        },
                    }
                )
                response_rule = '{"final_answer":"最终结论","solution":"完整、可复核的推导"}'
            lane_name = "闭卷推理" if lane == "closed-book" else "工具增强"
            instruction = (
                f"你正在参加 {year} 年考研数学（一）{lane_name}测试。\n\n"
                f"第 {number} 题（{question['points']} 分）：\n{question['question_text']}\n\n"
                f"请独立作答，最终严格输出 JSON：{response_rule}。"
            )
            output[lane].append(
                {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"agentbench:math:{year}:{lane}:{number}")),
                    "slug": f"postgraduate-math.{year}.math1.q{number:02d}.{lane}",
                    "version": case_version,
                    "category": "postgraduate-math",
                    "title": f"{year} 数学一 · 第 {number} 题 · {lane_name}",
                    "description": f"真题第 {number} 题，{question['points']} 分，来源页 {', '.join(map(str, question.get('source_pages') or [])) or '人工校对'}。",
                    "definition": {
                        "slug": f"postgraduate-math.{year}.math1.q{number:02d}.{lane}",
                        "version": case_version,
                        "category": "postgraduate-math",
                        "title": f"{year} 数学一 · 第 {number} 题 · {lane_name}",
                        "description": f"经人工确认的 {year} 年考研数学（一）真题。",
                        "instruction": instruction,
                        "tools": [] if lane == "closed-book" else ["filesystem", "search", "shell"],
                        "limits": {"max_runtime_seconds": 0, "max_steps": 160, "max_tokens": 100_000},
                        "validators": validators,
                        "tags": ["考研数学", str(year), kind, lane],
                        "initial_files": {},
                        "metadata": {
                            "difficulty": 5,
                            "estimated_minutes": 12 if kind != "solution" else 30,
                            "capability": "高等数学、线性代数与概率统计综合推理",
                            "exam": MATH_EXAM_ID,
                            "year": year,
                            "question_no": number,
                            "points": question["points"],
                            "question_type": kind,
                            "lane": lane,
                            "source_sha256": source_hash,
                            "source_pages": question.get("source_pages") or [],
                            "native_agent_compatible": lane != "closed-book",
                            "private_validation": True,
                        },
                    },
                }
            )
    return output


def mark_math_import_published(
    data_dir: Path,
    import_id: str,
    suites: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest = get_math_import(data_dir, import_id)
    manifest["status"] = "published"
    manifest["published_at"] = datetime.now(UTC).isoformat()
    manifest["published_suites"] = suites
    _write_manifest(data_dir, manifest)
    return manifest
