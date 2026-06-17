import logging
from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from app.db import Database, now_iso
from app.keyboards import (
    admin_panel, settings_keyboard, user_admin_keyboard, main_menu, cancel_keyboard,
    admin_shop_types_keyboard, admin_shop_packages_keyboard, admin_shop_edit_keyboard,
    admin_leagues_keyboard, admin_league_edit_keyboard,
)
from app.states import AdminFlow, BulkQuestionImport, ShopPackageFlow, LeagueFlow
from app.bulk_questions import parse_bulk_questions, format_bulk_report

logger = logging.getLogger(__name__)
router = Router()


async def require_admin_message(message: Message, db: Database) -> bool:
    if not await db.is_admin(message.from_user.id):
        await message.answer("دسترسی ادمین ندارید.")
        return False
    return True


async def require_admin_call(call: CallbackQuery, db: Database) -> bool:
    if not await db.is_admin(call.from_user.id):
        await call.answer("دسترسی ندارید.", show_alert=True)
        return False
    return True


@router.message(F.text == "🛡 پنل ادمین")
@router.message(Command("admin"))
async def admin_entry(message: Message, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_message(message, db):
            return
        await state.clear()
        await message.answer("پنل ادمین:", reply_markup=ReplyKeyboardRemove())
        await message.answer("انتخاب کنید:", reply_markup=admin_panel())
    except Exception:
        logger.exception("Admin entry failed")
        await message.answer("خطا.")


@router.message(Command("backup"))
async def backup_command(message: Message, db: Database) -> None:
    try:
        if not await require_admin_message(message, db):
            return
        path = await db.backup_copy()
        await message.answer_document(FSInputFile(path), caption="بک‌آپ دیتابیس")
        await db.log_admin(message.from_user.id, "backup")
    except Exception:
        logger.exception("Backup failed")
        await message.answer("خطا در ساخت بک‌آپ.")


@router.callback_query(F.data.startswith("admin:"))
async def admin_callback(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_call(call, db):
            return
        await state.clear()
        action = call.data.split(":", 1)[1]
        if action == 'back':
            await call.message.answer("پنل ادمین:", reply_markup=admin_panel())
        elif action == 'stats':
            s = await db.stats()
            await call.message.answer("📊 آمار کلی\n" + "\n".join(f"{k}: {v}" for k, v in s.items()))
        elif action == 'settings':
            await call.message.answer("برای ویرایش روی تنظیم کلیک کنید:", reply_markup=settings_keyboard(await db.all_settings()))
        elif action == 'user_search':
            await state.set_state(AdminFlow.waiting_user_id)
            await call.message.answer("آیدی عددی کاربر را بفرست:", reply_markup=cancel_keyboard())
        elif action in {'add_admin', 'remove_admin'}:
            await state.set_state(AdminFlow.waiting_admin_id)
            await state.update_data(admin_action=action)
            await call.message.answer("آیدی عددی ادمین را بفرست:", reply_markup=cancel_keyboard())
        elif action == 'backup':
            path = await db.backup_copy()
            await call.message.answer_document(FSInputFile(path), caption="بک‌آپ دیتابیس")
            await db.log_admin(call.from_user.id, "backup")
        elif action == 'bulk_questions':
            await state.set_state(BulkQuestionImport.waiting_json)
            await call.message.answer("JSON سوال‌ها را به‌صورت متن بفرست یا فایل .json/.txt ارسال کن.", reply_markup=cancel_keyboard())
        elif action == 'shop_manage':
            await call.message.answer("کدام بخش فروشگاه مدیریت شود؟", reply_markup=admin_shop_types_keyboard())
        elif action == 'leagues':
            await call.message.answer("مدیریت لیگ‌ها:", reply_markup=admin_leagues_keyboard(await db.all_leagues()))
        await call.answer()
    except Exception:
        logger.exception("Admin callback failed")
        await call.answer("خطا", show_alert=True)


@router.message(BulkQuestionImport.waiting_json)
async def bulk_questions_receive(message: Message, db: Database, state: FSMContext, bot: Bot) -> None:
    try:
        if not await require_admin_message(message, db):
            return
        payload = message.text or ""
        if message.document:
            name = message.document.file_name or ""
            if not (name.endswith(".json") or name.endswith(".txt")):
                await message.answer("فقط فایل .json یا .txt قابل قبول است.")
                return
            file = await bot.get_file(message.document.file_id)
            data = await bot.download_file(file.file_path)
            payload = data.read().decode("utf-8-sig")
        accepted, rejected = parse_bulk_questions(payload)
        success = 0
        if accepted:
            success = await db.bulk_admin_add_questions(message.from_user.id, accepted)
        await db.log_admin(message.from_user.id, "bulk_questions", details=f"success={success}, rejected={len(rejected)}")
        await state.clear()
        await message.answer(format_bulk_report(success, rejected), reply_markup=ReplyKeyboardRemove())
    except UnicodeDecodeError:
        logger.exception("Bulk file encoding failed")
        await message.answer("فایل باید UTF-8 باشد.")
    except Exception:
        logger.exception("Bulk import failed")
        await message.answer("خطا در افزودن Bulk سوال.")


@router.callback_query(F.data.startswith("set:"))
async def setting_pick(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_call(call, db):
            return
        await state.clear()
        key = call.data.split(":", 1)[1]
        val = await db.get_setting(key)
        await state.set_state(AdminFlow.waiting_setting_value)
        await state.update_data(setting_key=key)
        await call.message.answer(f"مقدار جدید برای <code>{key}</code> را بفرست. مقدار فعلی: <code>{val}</code>", reply_markup=cancel_keyboard())
        await call.answer()
    except Exception:
        logger.exception("Setting pick failed")
        await call.answer("خطا", show_alert=True)


@router.message(AdminFlow.waiting_setting_value, F.text)
async def setting_value(message: Message, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_message(message, db):
            return
        data = await state.get_data()
        await db.set_setting(data['setting_key'], message.text.strip())
        await db.log_admin(message.from_user.id, "setting_update", data['setting_key'], message.text.strip())
        await state.clear()
        await message.answer("تنظیم ذخیره شد.", reply_markup=main_menu(True))
    except Exception:
        logger.exception("Setting save failed")
        await message.answer("خطا در ذخیره تنظیم.")


@router.message(AdminFlow.waiting_user_id, F.text)
async def user_lookup(message: Message, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_message(message, db):
            return
        tg_id = int(message.text.strip())
        u = await db.get_user(tg_id)
        await state.clear()
        if not u:
            await message.answer("کاربر پیدا نشد.")
            return
        rank = await db.get_rank_title(u['level'])
        league = await db.get_user_league(u['cups'])
        await message.answer(
            f"👤 کاربر <code>{tg_id}</code>\nUsername: @{u['username'] or '-'}\nCoins: {u['coins']}\nXP: {u['xp']}\nLevel: {u['level']} — {rank}\nCups: {u['cups']} | League: {league['name'] if league else '-'}\nBlocked: {bool(u['is_blocked'])}\nWins/Losses/Draws: {u['wins']}/{u['losses']}/{u['draws']}",
            reply_markup=user_admin_keyboard(tg_id),
        )
    except ValueError:
        await message.answer("آیدی باید عددی باشد.")
    except Exception:
        logger.exception("User lookup failed")
        await message.answer("خطا.")


@router.callback_query(F.data.startswith(("ucoin:", "uxp:")))
async def user_delta_start(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_call(call, db):
            return
        await state.clear()
        kind, tg_s = call.data.split(":")
        await state.set_state(AdminFlow.waiting_user_delta)
        await state.update_data(delta_kind=kind, target_id=int(tg_s))
        await call.message.answer("مقدار تغییر را با علامت وارد کنید؛ مثال: +100 یا -50", reply_markup=cancel_keyboard())
        await call.answer()
    except Exception:
        logger.exception("User delta start failed")
        await call.answer("خطا", show_alert=True)


@router.message(AdminFlow.waiting_user_delta, F.text)
async def user_delta_save(message: Message, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_message(message, db):
            return
        data = await state.get_data()
        amount = int(message.text.strip())
        target = int(data['target_id'])
        if data['delta_kind'] == 'ucoin':
            await db.change_coins(target, amount, 'admin_adjust')
        else:
            await db.change_xp(target, amount, 'admin_adjust')
        await db.log_admin(message.from_user.id, "user_adjust", str(target), f"{data['delta_kind']} {amount}")
        await state.clear()
        await message.answer("انجام شد.")
    except ValueError:
        await message.answer("عدد معتبر وارد کنید؛ مثال +100")
    except Exception:
        logger.exception("User delta save failed")
        await message.answer("خطا.")


@router.callback_query(F.data.startswith("ublock:"))
async def user_block_toggle(call: CallbackQuery, db: Database) -> None:
    try:
        if not await require_admin_call(call, db):
            return
        tg_id = int(call.data.split(":")[1])
        u = await db.get_user(tg_id)
        if not u:
            await call.answer("کاربر پیدا نشد.", show_alert=True); return
        new_val = 0 if u['is_blocked'] else 1
        await db.execute_write("UPDATE users SET is_blocked=? WHERE telegram_id=?", (new_val, tg_id))
        await db.log_admin(call.from_user.id, "user_block_toggle", str(tg_id), str(new_val))
        await call.answer("انجام شد.")
    except Exception:
        logger.exception("Block toggle failed")
        await call.answer("خطا", show_alert=True)


@router.message(AdminFlow.waiting_admin_id, F.text)
async def admin_id_save(message: Message, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_message(message, db):
            return
        data = await state.get_data()
        target = int(message.text.strip())
        if data['admin_action'] == 'add_admin':
            await db.execute_write("INSERT OR REPLACE INTO admins(telegram_id,role,added_by,created_at) VALUES(?,?,?,?)", (target, 'admin', message.from_user.id, now_iso()))
            await db.log_admin(message.from_user.id, "admin_add", str(target))
            await message.answer("ادمین اضافه شد.")
        else:
            await db.execute_write("DELETE FROM admins WHERE telegram_id=? AND role<>'owner'", (target,))
            await db.log_admin(message.from_user.id, "admin_remove", str(target))
            await message.answer("ادمین حذف شد (مالک حذف نمی‌شود).")
        await state.clear()
    except ValueError:
        await message.answer("آیدی باید عددی باشد.")
    except Exception:
        logger.exception("Admin add/remove failed")
        await message.answer("خطا.")


@router.callback_query(F.data.startswith("ashop:"))
async def admin_shop_callback(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_call(call, db):
            return
        await state.clear()
        _, action, value = call.data.split(":")
        if action == "list":
            packages = await db.shop_packages(value)
            await call.message.answer("بسته‌ها:", reply_markup=admin_shop_packages_keyboard(packages, value))
        elif action == "add":
            await state.set_state(ShopPackageFlow.title)
            await state.update_data(package_type=value)
            await call.message.answer("نام بسته را وارد کنید:", reply_markup=cancel_keyboard())
        elif action == "edit":
            pkg = await db.get_package(int(value))
            if not pkg:
                await call.answer("بسته پیدا نشد.", show_alert=True); return
            await call.message.answer(f"ویرایش بسته #{pkg['id']}\n{pkg['title']} | coins={pkg['coins']} | xp={pkg['xp']} | {pkg['price_label']}", reply_markup=admin_shop_edit_keyboard(pkg['id']))
        elif action == "delete":
            await db.delete_shop_package(int(value))
            await db.log_admin(call.from_user.id, "shop_package_delete", value)
            await call.message.answer("بسته حذف/غیرفعال شد.", reply_markup=admin_shop_types_keyboard())
        await call.answer()
    except Exception:
        logger.exception("Admin shop callback failed")
        await call.answer("خطا", show_alert=True)


@router.message(ShopPackageFlow.title, F.text)
async def shop_pkg_title(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin_message(message, db): return
    await state.update_data(title=message.text.strip())
    await state.set_state(ShopPackageFlow.amount)
    await message.answer("مقدار سکه یا XP را عددی وارد کنید:", reply_markup=cancel_keyboard())


@router.message(ShopPackageFlow.amount, F.text)
async def shop_pkg_amount(message: Message, state: FSMContext, db: Database) -> None:
    try:
        if not await require_admin_message(message, db): return
        amount = int(message.text.strip())
        if amount <= 0: raise ValueError
        await state.update_data(amount=amount)
        await state.set_state(ShopPackageFlow.price)
        await message.answer("برچسب قیمت را وارد کنید؛ مثال: ۵۰٬۰۰۰ تومان", reply_markup=cancel_keyboard())
    except ValueError:
        await message.answer("مقدار باید عدد مثبت باشد.")


@router.message(ShopPackageFlow.price, F.text)
async def shop_pkg_price(message: Message, state: FSMContext, db: Database) -> None:
    try:
        if not await require_admin_message(message, db): return
        data = await state.get_data()
        pid = await db.add_shop_package(data['package_type'], data['title'], int(data['amount']), message.text.strip())
        await db.log_admin(message.from_user.id, "shop_package_add", str(pid))
        await state.clear()
        await message.answer("بسته اضافه شد.", reply_markup=ReplyKeyboardRemove())
    except Exception:
        logger.exception("Shop package add failed")
        await message.answer("خطا در افزودن بسته.")


@router.callback_query(F.data.startswith("ashop_edit:"))
async def admin_shop_edit_start(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_call(call, db): return
        await state.clear()
        _, field, pid = call.data.split(":")
        state_map = {"title": ShopPackageFlow.edit_title, "amount": ShopPackageFlow.edit_amount, "price": ShopPackageFlow.edit_price}
        await state.set_state(state_map[field])
        await state.update_data(package_id=int(pid), edit_field=field)
        prompt = {"title": "نام جدید:", "amount": "مقدار جدید عددی:", "price": "قیمت جدید:"}[field]
        await call.message.answer(prompt, reply_markup=cancel_keyboard())
        await call.answer()
    except Exception:
        logger.exception("Shop edit start failed")
        await call.answer("خطا", show_alert=True)


@router.message(ShopPackageFlow.edit_title, F.text)
@router.message(ShopPackageFlow.edit_amount, F.text)
@router.message(ShopPackageFlow.edit_price, F.text)
async def admin_shop_edit_save(message: Message, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_message(message, db): return
        data = await state.get_data()
        field = data['edit_field']
        db_field = 'price_label' if field == 'price' else field
        value = int(message.text.strip()) if field == 'amount' else message.text.strip()
        await db.update_shop_package_field(int(data['package_id']), db_field, value)
        await db.log_admin(message.from_user.id, "shop_package_edit", str(data['package_id']), f"{field}={value}")
        await state.clear()
        await message.answer("ویرایش ذخیره شد.")
    except ValueError:
        await message.answer("برای مقدار، عدد معتبر وارد کنید.")
    except Exception:
        logger.exception("Shop edit save failed")
        await message.answer("خطا در ذخیره ویرایش.")


@router.callback_query(F.data.startswith("league:"))
async def league_callback(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_call(call, db): return
        await state.clear()
        parts = call.data.split(":")
        action = parts[1]
        if action == "add":
            await state.set_state(LeagueFlow.name)
            await call.message.answer("نام لیگ را وارد کنید:", reply_markup=cancel_keyboard())
        elif action == "edit":
            lg = await db.get_league(int(parts[2]))
            if not lg:
                await call.answer("لیگ پیدا نشد.", show_alert=True); return
            await call.message.answer(f"ویرایش لیگ #{lg['id']} — {lg['name']}", reply_markup=admin_league_edit_keyboard(lg['id']))
        elif action == "delete":
            await db.delete_league(int(parts[2]))
            await db.log_admin(call.from_user.id, "league_delete", parts[2])
            await call.message.answer("لیگ حذف/غیرفعال شد.", reply_markup=admin_leagues_keyboard(await db.all_leagues()))
        await call.answer()
    except Exception:
        logger.exception("League callback failed")
        await call.answer("خطا", show_alert=True)


@router.message(LeagueFlow.name, F.text)
async def league_name(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin_message(message, db): return
    await state.update_data(name=message.text.strip())
    await state.set_state(LeagueFlow.min_cups)
    await message.answer("آستانه کاپ ورود به این لیگ را عددی وارد کنید:", reply_markup=cancel_keyboard())


@router.message(LeagueFlow.min_cups, F.text)
async def league_min(message: Message, state: FSMContext, db: Database) -> None:
    try:
        if not await require_admin_message(message, db): return
        await state.update_data(min_cups=int(message.text.strip()))
        await state.set_state(LeagueFlow.win_cups)
        await message.answer("مقدار کاپ برد در این لیگ را وارد کنید:", reply_markup=cancel_keyboard())
    except ValueError:
        await message.answer("عدد معتبر وارد کنید.")


@router.message(LeagueFlow.win_cups, F.text)
async def league_win(message: Message, state: FSMContext, db: Database) -> None:
    try:
        if not await require_admin_message(message, db): return
        await state.update_data(win_cups=int(message.text.strip()))
        await state.set_state(LeagueFlow.loss_cups)
        await message.answer("مقدار کاپ باخت را وارد کنید؛ مثال -10 یا 0:", reply_markup=cancel_keyboard())
    except ValueError:
        await message.answer("عدد معتبر وارد کنید.")


@router.message(LeagueFlow.loss_cups, F.text)
async def league_loss(message: Message, state: FSMContext, db: Database) -> None:
    try:
        if not await require_admin_message(message, db): return
        data = await state.get_data()
        lid = await db.add_league(data['name'], int(data['min_cups']), int(data['win_cups']), int(message.text.strip()))
        await db.log_admin(message.from_user.id, "league_add", str(lid))
        await state.clear()
        await message.answer("لیگ اضافه شد.", reply_markup=admin_leagues_keyboard(await db.all_leagues()))
    except ValueError:
        await message.answer("عدد معتبر وارد کنید.")
    except Exception:
        logger.exception("League add failed")
        await message.answer("خطا در افزودن لیگ. احتمالاً آستانه کاپ تکراری است.")


@router.callback_query(F.data.startswith("league_edit:"))
async def league_edit_start(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_call(call, db): return
        await state.clear()
        _, field, lid = call.data.split(":")
        map_state = {"name": LeagueFlow.edit_name, "min": LeagueFlow.edit_min_cups, "win": LeagueFlow.edit_win_cups, "loss": LeagueFlow.edit_loss_cups}
        await state.set_state(map_state[field])
        await state.update_data(league_id=int(lid), league_field=field)
        prompt = {"name": "نام جدید:", "min": "آستانه کاپ جدید:", "win": "کاپ برد جدید:", "loss": "کاپ باخت جدید:"}[field]
        await call.message.answer(prompt, reply_markup=cancel_keyboard())
        await call.answer()
    except Exception:
        logger.exception("League edit start failed")
        await call.answer("خطا", show_alert=True)


@router.message(LeagueFlow.edit_name, F.text)
@router.message(LeagueFlow.edit_min_cups, F.text)
@router.message(LeagueFlow.edit_win_cups, F.text)
@router.message(LeagueFlow.edit_loss_cups, F.text)
async def league_edit_save(message: Message, db: Database, state: FSMContext) -> None:
    try:
        if not await require_admin_message(message, db): return
        data = await state.get_data()
        field_map = {"name": "name", "min": "min_cups", "win": "win_cups", "loss": "loss_cups"}
        field = field_map[data['league_field']]
        value = message.text.strip() if field == 'name' else int(message.text.strip())
        await db.update_league_field(int(data['league_id']), field, value)
        await db.log_admin(message.from_user.id, "league_edit", str(data['league_id']), f"{field}={value}")
        await state.clear()
        await message.answer("لیگ ویرایش شد.", reply_markup=admin_leagues_keyboard(await db.all_leagues()))
    except ValueError:
        await message.answer("عدد معتبر وارد کنید.")
    except Exception:
        logger.exception("League edit save failed")
        await message.answer("خطا در ویرایش لیگ. احتمالاً آستانه کاپ تکراری است.")
