import logging
from aiogram import Bot, Router, F
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from app.db import Database
from app.keyboards import shop_keyboard, review_tx_keyboard, shop_sections_keyboard, cancel_keyboard, main_menu
from app.states import ShopReceipt

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "🛒 فروشگاه")
async def shop_entry(message: Message) -> None:
    await message.answer("فروشگاه:", reply_markup=ReplyKeyboardRemove())
    await message.answer("نوع بسته را انتخاب کن:", reply_markup=shop_sections_keyboard())


@router.callback_query(F.data == "shop_back:sections")
async def shop_back_sections(call: CallbackQuery) -> None:
    await call.message.edit_text("نوع بسته را انتخاب کن:", reply_markup=shop_sections_keyboard())
    await call.answer()


@router.callback_query(F.data.startswith("shop_section:"))
async def shop_section(call: CallbackQuery, db: Database) -> None:
    try:
        package_type = call.data.split(":", 1)[1]
        packages = await db.shop_packages(package_type)
        title = "بسته‌های سکه" if package_type == "coins" else "بسته‌های سطح/XP"
        if not packages:
            await call.message.edit_text(f"{title}\nفعلاً بسته‌ای در این بخش فعال نیست.", reply_markup=shop_sections_keyboard())
            await call.answer()
            return
        await call.message.edit_text(f"{title}: یکی را انتخاب کن:", reply_markup=shop_keyboard(packages, package_type))
        await call.answer()
    except Exception:
        logger.exception("Shop section failed")
        await call.answer("خطا", show_alert=True)


@router.callback_query(F.data.startswith("shop:"))
async def package_selected(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        package_id = int(call.data.split(":")[1])
        p = await db.get_package(package_id)
        if not p or not p['is_active']:
            await call.answer("بسته پیدا نشد.", show_alert=True)
            return
        tx_id = await db.create_shop_tx(call.from_user.id, package_id)
        card = await db.get_setting('payment_card_number', 'تنظیم نشده')
        await state.set_state(ShopReceipt.waiting_receipt)
        await state.update_data(tx_id=tx_id)
        await call.message.answer(
            f"بسته: {p['title']}\nسکه: {p['coins']} | XP: {p['xp']}\nمبلغ: {p['price_label']}\n\n"
            f"شماره کارت:\n<code>{card}</code>\n\n"
            "بعد از واریز، رسید را به‌صورت عکس یا متن همین‌جا ارسال کن.",
            reply_markup=cancel_keyboard(),
        )
        await call.answer()
    except Exception:
        logger.exception("Package select failed")
        await call.answer("خطا", show_alert=True)


@router.message(ShopReceipt.waiting_receipt)
async def receive_receipt(message: Message, db: Database, state: FSMContext, bot: Bot, admin_review_channel_id: int | None) -> None:
    try:
        data = await state.get_data()
        tx_id = int(data['tx_id'])
        rtype, text, file_id = 'text', message.text or message.caption, None
        if message.photo:
            rtype = 'photo'
            file_id = message.photo[-1].file_id
        elif not text:
            await message.answer("لطفاً رسید را به‌صورت عکس یا متن بفرست.")
            return
        await db.save_receipt(tx_id, rtype, text, file_id)
        tx = await db.get_tx(tx_id)
        if admin_review_channel_id and tx:
            caption = (
                f"🧾 رسید خرید #{tx_id}\nUser: <code>{tx['user_id']}</code>\n"
                f"Package: {tx['title']}\nCoins: {tx['coins']} | XP: {tx['xp']}\nPrice: {tx['price_label']}\n"
                f"Text: {text or '-'}"
            )
            if rtype == 'photo' and file_id:
                await bot.send_photo(admin_review_channel_id, file_id, caption=caption, reply_markup=review_tx_keyboard(tx_id))
            else:
                await bot.send_message(admin_review_channel_id, caption, reply_markup=review_tx_keyboard(tx_id))
        await state.clear()
        await message.answer("رسید ثبت شد و برای ادمین‌ها ارسال شد. بعد از بررسی خبر می‌دهیم.", reply_markup=main_menu(await db.is_admin(message.from_user.id)))
    except Exception:
        logger.exception("Receipt receive failed")
        await message.answer("خطا در ثبت رسید.")


@router.callback_query(F.data.startswith("tx:"))
async def review_tx(call: CallbackQuery, db: Database, bot: Bot) -> None:
    try:
        if not await db.is_admin(call.from_user.id):
            await call.answer("دسترسی ندارید.", show_alert=True); return
        _, action, tx_s = call.data.split(":")
        approve = action == 'approve'
        tx = await db.review_tx(int(tx_s), call.from_user.id, approve)
        if not tx:
            await call.answer("قبلاً بررسی شده یا پیدا نشد.", show_alert=True); return
        await db.log_admin(call.from_user.id, f"tx_{action}", str(tx_s))
        await bot.send_message(tx['user_id'], "✅ خرید شما تایید و موجودی اضافه شد." if approve else "❌ رسید خرید شما رد شد.")
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer("ثبت شد.")
    except Exception:
        logger.exception("TX review failed")
        await call.answer("خطا", show_alert=True)
