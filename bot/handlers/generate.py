from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards import inline
from bot.db.repositories import UserRepository, OrderRepository
from bot.payments.stars import send_stars_invoice
from bot.payments.cryptobot import cryptobot
from bot.config import settings
import aiohttp
import logging

logger = logging.getLogger(__name__)
router = Router()

@router.callback_query(F.data == "btn_generate")
async def choose_plan(callback: CallbackQuery):
    await callback.answer()
    text = (
        "💳 **Выберите тарифный план:**\n\n"
        "Каждый тариф включает в себя **1 генерацию** актуального профиля Госуслуг "
        "и размещение сайта на хостинге на указанный период:\n\n"
        "• **1 День** — для быстрой сверки или демонстрации.\n"
        "• **1 Неделя** — оптимально для большинства задач.\n"
        "• **1 Месяц** — долгосрочный доступ к вашим данным."
    )
    await callback.message.edit_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=inline.get_plans_keyboard()
    )


@router.callback_query(F.data.startswith("plan_"))
async def choose_payment_method(callback: CallbackQuery):
    await callback.answer()
    plan = callback.data.split("_")[1]
    
    plan_names = {"day": "1 День", "week": "1 Неделя", "month": "1 Месяц"}
    text = (
        f"🛒 Выбран тариф: **{plan_names.get(plan, plan)}**\n\n"
        "Выберите удобный способ оплаты:"
    )
    await callback.message.edit_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=inline.get_payment_methods(plan)
    )


@router.callback_query(F.data.startswith("pay_stars_"))
async def pay_with_stars(callback: CallbackQuery, bot: Bot, user_repo: UserRepository, order_repo: OrderRepository):
    await callback.answer()
    plan = callback.data.split("_")[2]
    
    user = await user_repo.get_or_create(
        telegram_id=callback.from_user.id,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username
    )
    
    # Create order in database
    order = await order_repo.create(
        user_id=user.id,
        plan=plan,
        payment_method="stars"
    )
    
    # Send invoice
    try:
        await send_stars_invoice(bot, callback.message.chat.id, plan, order.id)
        # Delete selection message to clean chat
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Failed to send Stars invoice: {e}", exc_info=True)
        await callback.message.answer(
            "❌ Не удалось создать счет для оплаты в Telegram Stars. Пожалуйста, попробуйте позже или выберите другой способ оплаты."
        )


@router.callback_query(F.data.startswith("pay_crypto_"))
async def pay_with_crypto(callback: CallbackQuery, user_repo: UserRepository, order_repo: OrderRepository):
    await callback.answer()
    plan = callback.data.split("_")[2]
    
    user = await user_repo.get_or_create(
        telegram_id=callback.from_user.id,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username
    )
    
    # Create order in database
    order = await order_repo.create(
        user_id=user.id,
        plan=plan,
        payment_method="cryptobot"
    )
    
    try:
        invoice_url, invoice_id = await cryptobot.create_invoice(plan, order.id)
        
        # Update order with payment ID
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
        
        text = (
            "🪙 **Счет успешно выставлен!**\n\n"
            f"Сумма к оплате: **${price_map.get(plan)}** (в любой доступной криптовалюте)\n"
            "Нажмите кнопку ниже для перехода к оплате в CryptoBot.\n\n"
            "После проведения транзакции нажмите кнопку **«Проверить оплату»**."
        )
        
        await callback.message.edit_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Failed to create CryptoBot invoice: {e}", exc_info=True)
        await callback.message.answer(
            "❌ Не удалось создать счет в CryptoBot. Пожалуйста, попробуйте позже."
        )


@router.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto_payment(callback: CallbackQuery, bot: Bot, order_repo: OrderRepository):
    order_id = int(callback.data.split("_")[2])
    order = await order_repo.get_by_id(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден.", show_alert=True)
        return
        
    if order.status != "pending_payment":
        await callback.answer("ℹ️ Этот заказ уже обработан.", show_alert=True)
        return
        
    status = await cryptobot.get_invoice_status(order.payment_id)
    
    if status == "paid":
        await callback.answer("✅ Оплата успешно подтверждена!", show_alert=True)
        await order_repo.mark_as_paid(order_id)
        await handle_successful_payment(bot, callback.message.chat.id, order, order_repo)
    elif status == "expired":
        await callback.answer("❌ Время действия счета истекло.", show_alert=True)
        await callback.message.edit_text("❌ Оплата не была получена вовремя. Счет аннулирован.")
    else:
        await callback.answer("⏳ Оплата еще не поступила. Попробуйте через пару секунд.", show_alert=True)


async def handle_successful_payment(bot: Bot, chat_id: int, order, order_repo: OrderRepository):
    """Initiates authentication session and sends user the login form link."""
    # Update order state to paid (if not done)
    await order_repo.mark_as_paid(order.id)
    
    # Request auth server to create session
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "order_id": order.id,
                "user_id": order.user_id,
                "telegram_id": chat_id,
                "plan": order.plan
            }
            async with session.post(f"{settings.AUTH_SERVER_URL}/api/generate", json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    session_id = data["session_id"]
                    auth_url = settings.SITE_BASE_URL.replace("/view", f"/auth/{session_id}")
                    
                    text = (
                        "🎉 **Оплата успешно получена!**\n\n"
                        "Мы готовы начать процесс скачивания вашего профиля.\n"
                        "Для этого вам нужно авторизоваться в системе Госуслуг через защищенную веб-форму.\n\n"
                        "👇 **Инструкция:**\n"
                        "1. Нажмите кнопку **«Вход на Госуслуги»** ниже.\n"
                        "2. Введите свои учетные данные и пройдите двухфакторную аутентификацию (СМС/ТОТР).\n"
                        "3. Держите веб-страницу открытой до завершения генерации.\n\n"
                        "Когда всё будет готово, я пришлю ссылку на ваш сайт прямо сюда!"
                    )
                    
                    builder = InlineKeyboardBuilder()
                    builder.button(text="🔑 Вход на Госуслуги", url=auth_url)
                    builder.adjust(1)
                    
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="Markdown",
                        reply_markup=builder.as_markup()
                    )
                else:
                    logger.error(f"Auth server returned error {resp.status}: {await resp.text()}")
                    await bot.send_message(
                        chat_id=chat_id,
                        text="❌ Возникла ошибка на сервере авторизации. Пожалуйста, обратитесь в поддержку."
                    )
    except Exception as e:
        logger.error(f"Error calling auth server: {e}", exc_info=True)
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Не удалось связаться с сервером генерации. Попробуйте еще раз позже."
        )
