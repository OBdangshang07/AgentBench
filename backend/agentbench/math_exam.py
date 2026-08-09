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
    return 10 if number == 17 else 12


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
