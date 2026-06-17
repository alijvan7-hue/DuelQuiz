import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from app.db import Database
from app.keyboards import main_menu, leaderboard_basis_keyboard, leaderboard_period_keyboard, CANCEL_TEXT
from app.utils import ensure_user, xp_progress_text, rtl_line

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def start(message: Message, db: Database, state: FSMContext, command: CommandObject | None = None) -> None:
    await state.clear()
    payload = command.args if command else None
    try:
        await ensure_user(db, message.from_user, payload)
        is_admin = await db.is_admin(message.from_user.id)
        if payload and payload.startswith('invite_'):
            from app.handlers.duel import join_invite_from_start
            await join_invite_from_start(message, db, payload.removeprefix('invite_'))
            return
        welcome = await db.get_setting("welcome_text", "سلام! به ربات کوییز دوئلی خوش آمدی. از منوی پایین انتخاب کن:")
        photo_id = await db.get_setting("start_photo_file_id", "")
        if photo_id:
            await message.answer_photo(photo_id, caption=welcome, reply_markup=main_menu(is_admin))
        else:
            await message.answer(welcome, reply_markup=main_menu(is_admin))
    except Exception:
        logger.exception("Start failed")
        await message.answer("خطایی رخ داد. لطفاً دوباره تلاش کن.")


@router.message(Command("help"))
async def help_command(message: Message, db: Database) -> None:
    try:
        await message.answer(await db.get_setting("help_text", "راهنما فعلاً تنظیم نشده است."), reply_markup=ReplyKeyboardRemove())
    except Exception:
        logger.exception("Help failed")
        await message.answer("خطا در نمایش راهنما.")


@router.message(Command("cancel"))
@router.message(F.text == CANCEL_TEXT)
async def cancel(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    is_admin = await db.is_admin(message.from_user.id)
    await message.answer("عملیات لغو شد. به منوی اصلی برگشتی.", reply_markup=main_menu(is_admin))


@router.callback_query(F.data == "nav:home")
async def nav_home(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    is_admin = await db.is_admin(call.from_user.id)
    await call.message.answer("به منوی اصلی برگشتی.", reply_markup=main_menu(is_admin))
    await call.answer()


@router.message(F.text == "👤 پروفایل")
async def profile(message: Message, db: Database) -> None:
    try:
        u = await db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        rank = await db.get_rank_title(u['level'])
        league = await db.get_user_league(u['cups'])
        cur, nxt = await db.level_bounds(u['level'])
        total_duels = int(u['wins']) + int(u['losses']) + int(u['draws'])
        wrong = max(0, int(u['total_answers']) - int(u['correct_answers']))
        username = f"@{u['username']}" if u['username'] else "—"
        joined = str(u['created_at']).split('T')[0]
        xp_bar = xp_progress_text(u['xp'], cur, nxt)
        await message.answer(
            f"👤 <b>{u['first_name'] or 'کاربر'}</b>  {username}\n"
            f"🏅 {rank} | <b>Level {u['level']}</b> | XP {xp_bar}\n"
            f"🏆 {league['name'] if league else 'بدون لیگ'} — <b>{u['cups']} جام</b>\n"
            f"🪙 سکه: <b>{u['coins']}</b>\n\n"
            f"⚔️ دوئل‌ها: {total_duels} | برد <b>{u['wins']}</b> / مساوی {u['draws']} / شکست <b>{u['losses']}</b>\n"
            f"✅ پاسخ صحیح: {u['correct_answers']} | ❌ غلط: {wrong}\n"
            f"📅 عضویت: {joined}",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception:
        logger.exception("Profile failed")
        await message.answer("خطا در نمایش پروفایل.")


@router.message(F.text == "🏆 لیدربورد")
async def leaderboard_entry(message: Message) -> None:
    await message.answer("لیدربورد را بر چه اساسی ببینی؟", reply_markup=ReplyKeyboardRemove())
    await message.answer("انتخاب کن:", reply_markup=leaderboard_basis_keyboard())


@router.callback_query(F.data.startswith("lb_basis:"))
async def leaderboard_basis(call: CallbackQuery) -> None:
    basis = call.data.split(":", 1)[1]
    await call.message.edit_text("بازه زمانی را انتخاب کن:", reply_markup=leaderboard_period_keyboard(basis))
    await call.answer()


@router.callback_query(F.data == "lb_back:basis")
async def leaderboard_back(call: CallbackQuery) -> None:
    await call.message.edit_text("لیدربورد را بر چه اساسی ببینی؟", reply_markup=leaderboard_basis_keyboard())
    await call.answer()


@router.callback_query(F.data.startswith("lb:"))
async def leaderboard_callback(call: CallbackQuery, db: Database) -> None:
    try:
        _, basis, period = call.data.split(":")
        basis_title = "سطح" if basis == "level" else "لیگ"
        period_title = {"daily": "روزانه", "monthly": "ماهانه", "all": "کلی"}.get(period, "کلی")
        rows = await db.leaderboard(basis, period)
        text = rtl_line(f"🏆 لیدربورد {basis_title} — {period_title}") + "\n\n"
        if not rows:
            text += rtl_line("هنوز امتیازی ثبت نشده است.")
        for i, r in enumerate(rows, 1):
            name = r['first_name'] or (('@' + r['username']) if r['username'] else str(r['telegram_id']))
            score_label = "کاپ" if basis == "league" else "امتیاز"
            text += rtl_line(f"{i}. {name} | {r['league_name']} | 🏆 {r['cups']} | سطح {r['level']} | {score_label}: {r['score']}") + "\n"
        await call.message.edit_text(text, reply_markup=leaderboard_period_keyboard(basis))
        await call.answer()
    except Exception:
        logger.exception("Leaderboard failed")
        await call.answer("خطا", show_alert=True)


@router.message(F.text == "🎁 رفرال")
async def referral(message: Message, db: Database, bot_username: str) -> None:
    await db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    link = f"https://t.me/{bot_username}?start=ref_{message.from_user.id}"
    await message.answer(
        "🎁 لینک دعوت اختصاصی شما:\n"
        f"{link}\n\n"
        "وقتی دوستت با این لینک وارد شود و حداقل یک دوئل بازی کند، پاداش برای هر دو نفر فعال می‌شود.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(F.text == "🏰 کلن (به‌زودی)")
async def clan_placeholder(message: Message) -> None:
    await message.answer("🏰 قابلیت کلن به‌زودی اضافه می‌شود.", reply_markup=ReplyKeyboardRemove())
