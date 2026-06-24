from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards import inline
from bot.db.repositories import UserRepository, HostedSiteRepository, OrderRepository
from bot.config import settings
from bot.handlers.generate import handle_successful_payment
from bot.payments.stars import send_stars_invoice
from bot.payments.cryptobot import cryptobot
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()

@router.callback_query(F.data == "btn_my_sites")
async def my_sites_list(callback: CallbackQuery, user_repo: UserRepository, site_repo: HostedSiteRepository):
    await callback.answer()
    
    user = await user_repo.get_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ Пользователь не найден в базе данных.", reply_markup=inline.get_main_menu())
        return

    active_sites = await site_repo.get_active_by_user(user.id)
    if not active_sites:
        text = (
            "📭 У вас пока нет активных офлайн-копий профиля Госуслуг.\n\n"
            "Вы можете сгенерировать новую копию прямо сейчас!"
        )
        await callback.message.edit_text(text=text, reply_markup=inline.get_main_menu())
        return

    text = "🌐 **Ваши активные офлайн-копии:**"
    await callback.message.edit_text(
        text=text,
        reply_markup=inline.get_sites_list_keyboard(active_sites)
    )


@router.callback_query(F.data.startswith("view_site_"))
async def view_site_detail(callback: CallbackQuery, site_repo: HostedSiteRepository):
    await callback.answer()
    site_uuid = callback.data.split("_")[2]
    
    site = await site_repo.get_by_uuid(site_uuid)
    if not site or not site.is_active:
        await callback.message.edit_text("❌ Сайт не найден или уже удален.", reply_markup=inline.get_main_menu())
        return

    expires_str = site.expires_at.strftime('%d.%m.%Y %H:%M UTC')
    text = (
        "🌐 **Детали сайта:**\n\n"
        f"🔗 **Ссылка:** {site.public_url}\n"
        f"📅 **Активен до:** {expires_str}\n"
        f"🆔 **ID:** `{site.uuid}`\n\n"
        "Вы можете продлить время работы хостинга, выбрав соответствующую опцию."
    )
    
    await callback.message.edit_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=inline.get_site_keyboard(site.uuid, site.public_url)
    )


@router.callback_query(F.data.startswith("extend_"))
async def extend_site_choose_plan(callback: CallbackQuery):
    await callback.answer()
    site_uuid = callback.data.split("_")[1]
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 +1 День", callback_data=f"extplan_day_{site_uuid}")
    builder.button(text="📅 +1 Неделя", callback_data=f"extplan_week_{site_uuid}")
    builder.button(text="📅 +1 Месяц", callback_data=f"extplan_month_{site_uuid}")
    builder.button(text="↩️ Назад", callback_data=f"view_site_{site_uuid}")
    builder.adjust(1, 1, 1, 1)

    await callback.message.edit_text(
        text="💳 **Выберите срок продления хостинга:**",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("extplan_"))
async def extend_site_choose_payment(
    callback: CallbackQuery,
    bot: Bot,
    user_repo: UserRepository,
    order_repo: OrderRepository
):
    await callback.answer()
    parts = callback.data.split("_")
    plan = parts[1]
    site_uuid = parts[2]
    
    user = await user_repo.get_or_create(
        telegram_id=callback.from_user.id,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username
    )
    
    # Check if admin
    is_admin = callback.from_user.id in settings.ADMIN_IDS or user.is_admin
    
    if is_admin:
        order = await order_repo.create(
            user_id=user.id,
            plan=f"extend_{plan}_{site_uuid}",
            payment_method="admin_free"
        )
        await order_repo.mark_as_paid(order.id)
        
        await callback.message.edit_text(
            text="⏳ **Вы являетесь администратором.** Продлеваем хостинг бесплатно...",
            parse_mode="Markdown"
        )
        await handle_successful_payment(bot, callback.message.chat.id, order, order_repo)
        return
        
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Telegram Stars", callback_data=f"extpay_stars_{plan}_{site_uuid}")
    builder.button(text="🪙 CryptoBot", callback_data=f"extpay_crypto_{plan}_{site_uuid}")
    builder.button(text="↩️ Назад", callback_data=f"extend_{site_uuid}")
    builder.adjust(1, 1, 1)

    await callback.message.edit_text(
        text=f"🛒 Выберите способ оплаты продления на тариф **{plan}**:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("extpay_stars_"))
async def pay_extension_stars(callback: CallbackQuery, bot: Bot, user_repo: UserRepository, order_repo: OrderRepository):
    await callback.answer()
    parts = callback.data.split("_")
    plan = parts[2]
    site_uuid = parts[3]
    
    user = await user_repo.get_or_create(
        telegram_id=callback.from_user.id,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username
    )
    
    # Create order specifically marked for extension
    # We append the site uuid to the plan field or custom flag, e.g., plan = "extend_day_uuid"
    order = await order_repo.create(
        user_id=user.id,
        plan=f"extend_{plan}_{site_uuid}",
        payment_method="stars"
    )
    
    try:
        await send_stars_invoice(bot, callback.message.chat.id, plan, order.id)
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Failed to send Stars extension invoice: {e}", exc_info=True)
        await callback.message.answer("❌ Ошибка отправки счета. Пожалуйста, попробуйте позже.")


@router.callback_query(F.data.startswith("extpay_crypto_"))
async def pay_extension_crypto(callback: CallbackQuery, user_repo: UserRepository, order_repo: OrderRepository):
    await callback.answer()
    parts = callback.data.split("_")
    plan = parts[2]
    site_uuid = parts[3]
    
    user = await user_repo.get_or_create(
        telegram_id=callback.from_user.id,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username
    )
    
    order = await order_repo.create(
        user_id=user.id,
        plan=f"extend_{plan}_{site_uuid}",
        payment_method="cryptobot"
    )
    
    try:
        invoice_url, invoice_id = await cryptobot.create_invoice(plan, order.id)
        price_map = {"day": settings.CRYPTO_PRICE_DAY, "week": settings.CRYPTO_PRICE_WEEK, "month": settings.CRYPTO_PRICE_MONTH}
        
        await order_repo.update_payment_details(
            order_id=order.id,
            payment_id=invoice_id,
            amount_crypto=price_map.get(plan)
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔗 Оплатить через CryptoBot", url=invoice_url)
        builder.button(text="🔄 Проверить оплату", callback_data=f"check_crypto_{order.id}")
        builder.button(text="↩️ В меню", callback_data="back_to_menu")
        builder.adjust(1, 1, 1)
        
        await callback.message.edit_text(
            text=f"🪙 **Счет на продление выставлен!**\n\nСумма: **${price_map.get(plan)}**.\nПосле оплаты нажмите кнопку проверки.",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Failed to create CryptoBot extension invoice: {e}", exc_info=True)
        await callback.message.answer("❌ Ошибка выставления счета. Пожалуйста, попробуйте позже.")
