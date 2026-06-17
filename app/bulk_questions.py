from __future__ import annotations

import json
import logging
from typing import Any
from app.utils import CANONICAL_GENRES

logger = logging.getLogger(__name__)

CORRECT_MAP = {"A": 1, "B": 2, "C": 3, "D": 4, "1": 1, "2": 2, "3": 3, "4": 4}
QUESTION_KEYS = ("question", "text", "q", "title", "prompt")
GENRE_KEYS = ("category", "genre", "cat", "subject", "topic")
CORRECT_KEYS = ("correct", "answer", "right", "correct_option", "correctAnswer")
OPTIONS_KEYS = ("options", "choices", "answers")
IGNORED_KEYS = {"added_by", "approved", "approved_by", "created_at"}


def bulk_help_text(genres: list[str] | None = None) -> str:
    genres = genres or CANONICAL_GENRES
    sample = '''{
  "q_0001": {
    "category": "فوتبال",
    "question": "کدام کشور قهرمان جام جهانی ۲۰۲۲ شد؟",
    "options": {"A": "فرانسه", "B": "آرژانتین", "C": "برزیل", "D": "آلمان"},
    "correct": "B"
  }
}'''
    return (
        "📥 افزودن Bulk سوال\n\n"
        "ژانرهای معتبر دقیقاً یکی از این موارد هستند:\n"
        + "، ".join(genres)
        + "\n\nنمونه JSON قابل قبول:\n"
        + f"<pre>{sample}</pre>\n"
        + "می‌توانی JSON را در چند پیام پشت‌سرهم بفرستی یا فایل .json/.txt ارسال کنی. "
        + "وقتی تمام شد، دستور /done را بفرست. برای لغو /cancel یا دکمه انصراف."
    )


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
        pairs = []
        for i, x in enumerate(data):
            if isinstance(x, dict):
                pairs.append((f"item_{i+1}", x))
            else:
                pairs.append((f"item_{i+1}", {"__invalid__": x}))
        return pairs
    if isinstance(data, dict):
        if all(isinstance(v, dict) for v in data.values()):
            return [(str(k), v) for k, v in data.items()]
        return [("item_1", data)]
    return []


def parse_bulk_questions(payload: str, valid_genres: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    valid = set(valid_genres or CANONICAL_GENRES)
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
        if "__invalid__" in obj:
            rejected.append(f"{key}: آیتم باید آبجکت سوال باشد")
            continue
        question = _pick(obj, QUESTION_KEYS)
        genre = _pick(obj, GENRE_KEYS)
        options_raw = _pick(obj, OPTIONS_KEYS)
        correct_raw = _pick(obj, CORRECT_KEYS)
        if not question or not str(question).strip():
            rejected.append(f"{key}: متن سوال خالی یا نامعتبر است")
            continue
        if not genre or str(genre).strip() not in valid:
            rejected.append(f"{key}: ژانر نامعتبر است: {genre!r}. ژانر باید دقیقاً یکی از لیست رسمی باشد")
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
            "genre": str(genre).strip(),
        })
    if rejected:
        return [], rejected
    return accepted, []


def format_bulk_report(success: int, rejected: list[str]) -> str:
    if rejected:
        text = f"📥 گزارش افزودن Bulk سوال\n\n❌ کل batch رد شد و هیچ سوالی درج نشد.\nتعداد خطا: {len(rejected)}"
        text += "\n\nدلایل رد:\n" + "\n".join(f"- {r}" for r in rejected[:60])
        if len(rejected) > 60:
            text += f"\n... و {len(rejected) - 60} مورد دیگر"
        return text
    return f"📥 گزارش افزودن Bulk سوال\n\n✅ همه سوالات معتبر بودند و {success} سوال با موفقیت اضافه شد."
