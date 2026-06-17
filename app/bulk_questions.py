from __future__ import annotations

import json
import logging
from typing import Any
from app.utils import normalize_genre

logger = logging.getLogger(__name__)

CORRECT_MAP = {"A": 1, "B": 2, "C": 3, "D": 4, "1": 1, "2": 2, "3": 3, "4": 4}
QUESTION_KEYS = ("question", "text", "q", "title", "prompt")
GENRE_KEYS = ("category", "genre", "cat", "subject", "topic")
CORRECT_KEYS = ("correct", "answer", "right", "correct_option", "correctAnswer")
OPTIONS_KEYS = ("options", "choices", "answers")


def _pick(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in obj:
            return obj[k]
    lowered = {str(k).lower(): v for k, v in obj.items()}
    for k in keys:
        if k.lower() in lowered:
            return lowered[k.lower()]
    return None


def _extract_options(raw: Any) -> list[str] | None:
    if isinstance(raw, dict):
        vals = []
        for key in ("A", "B", "C", "D"):
            val = raw.get(key) or raw.get(key.lower())
            if val is None:
                return None
            vals.append(str(val).strip())
        return vals
    if isinstance(raw, list) and len(raw) >= 4:
        return [str(x).strip() for x in raw[:4]]
    return None


def _extract_correct(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int) and raw in (1, 2, 3, 4):
        return raw
    text = str(raw).strip().upper()
    return CORRECT_MAP.get(text)


def _iter_question_objects(data: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(data, list):
        return [(f"item_{i+1}", x) for i, x in enumerate(data) if isinstance(x, dict)]
    if isinstance(data, dict):
        # Common format: {"q_123": {...}}
        if all(isinstance(v, dict) for v in data.values()):
            return [(str(k), v) for k, v in data.items()]
        # Single question object
        return [("item_1", data)]
    return []


def parse_bulk_questions(payload: str) -> tuple[list[dict[str, Any]], list[str]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[str] = []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        logger.exception("Bulk JSON parse failed")
        return [], [f"JSON خراب است: خط {exc.lineno} ستون {exc.colno} — {exc.msg}"]

    items = _iter_question_objects(data)
    if not items:
        return [], ["ساختار JSON قابل تشخیص نیست؛ باید آرایه‌ای از سوال‌ها یا آبجکت q_xxx باشد."]

    for key, obj in items:
        question = _pick(obj, QUESTION_KEYS)
        genre = _pick(obj, GENRE_KEYS)
        options_raw = _pick(obj, OPTIONS_KEYS)
        correct_raw = _pick(obj, CORRECT_KEYS)
        if not question or not str(question).strip():
            rejected.append(f"{key}: متن سوال خالی یا نامعتبر است")
            continue
        options = _extract_options(options_raw)
        if not options or any(not o for o in options):
            rejected.append(f"{key}: گزینه‌ها باید چهار مورد A/B/C/D یا لیست ۴تایی باشند")
            continue
        correct = _extract_correct(correct_raw)
        if correct is None:
            rejected.append(f"{key}: گزینه‌ی صحیح نامعتبر است؛ A/B/C/D یا 1..4 قابل قبول است")
            continue
        accepted.append({
            "question": str(question).strip(),
            "options": options,
            "correct": correct,
            "genre": normalize_genre(str(genre or "علم و دانش")),
        })
    return accepted, rejected


def format_bulk_report(success: int, rejected: list[str]) -> str:
    text = f"📥 گزارش افزودن Bulk سوال\n\n✅ افزوده شد: {success}\n❌ رد شد: {len(rejected)}"
    if rejected:
        text += "\n\nدلایل رد:\n" + "\n".join(f"- {r}" for r in rejected[:40])
        if len(rejected) > 40:
            text += f"\n... و {len(rejected) - 40} مورد دیگر"
    return text
