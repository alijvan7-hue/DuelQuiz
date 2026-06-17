from __future__ import annotations
import logging
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import Message
from app.db import Database
from app.keyboards import MAIN_MENU_TEXTS

logger = logging.getLogger(__name__)


class ActiveDuelMenuGuardMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[Message, dict[str, Any]], Awaitable[Any]], event: Message, data: dict[str, Any]) -> Any:
        if isinstance(event, Message) and event.text in MAIN_MENU_TEXTS:
            try:
                db: Database | None = data.get("db")
                if db and event.from_user:
                    duel = await db.active_duel_for_user(event.from_user.id)
                    if duel and duel["status"] in {"waiting", "invite_waiting", "genre_selection", "playing"}:
                        await event.answer("شما در حال بازی/دوئل فعال هستید؛ لطفاً ابتدا دوئل را تمام کنید.")
                        return None
            except Exception:
                logger.exception("Active duel guard failed")
        return await handler(event, data)
