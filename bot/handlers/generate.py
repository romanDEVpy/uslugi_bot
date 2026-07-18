from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards import inline
from bot.db.repositories import UserRepository, OrderRepository, SettingRepository, ReferralRepository
from bot.payments.stars import send_stars_invoice
from bot.payments.cryptobot import cryptobot
from bot.config import settings, DEFAULT_MESSAGES
import aiohttp
import logging

logger = logging.getLogger(__name__)
router = Router()

@router.callback_query(F.data == "btn_generate")
async def choose_plan(callback: CallbackQuery, setting_repo: SettingRepository):
    await callback.answer()
    text = await setting_repo.get("msg_choose_plan", DEFAULT_MESSAGES["msg_choose_plan"])
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            text=text,
            parse_mode="Markdown",
            reply_markup=inline.get_plans_keyboard()
        )
    else:
        await callback.message.edit_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=inline.get_plans_keyboard()
        )


@router.callback_query(F.data.startswith("plan_"))
async def choose_payment_method(callback: CallbackQuery, bot: Bot, user_repo: UserRepository, order_repo: OrderRepository):
    await callback.answer()
    plan = callback.data.split("_")[1]
    
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
            plan=plan,
            payment_method="admin_free"
        )
        await order_repo.mark_as_paid(order.id)
        
        await callback.message.edit_text(
            text="⏳ **Вы являетесь администратором.** Создаем бесплатный заказ и запускаем генерацию...",
            parse_mode="Markdown"
        )
        await handle_successful_payment(bot, callback.message.chat.id, order, order_repo)
        return
        
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
    
    # Process referral rewards
    try:
        from bot.db.models import User, ReferralTransaction
        from sqlalchemy import select
        
        user_repo = UserRepository(order_repo.session)
        user = await user_repo.get_by_telegram_id(chat_id)
        if user and user.referred_by_link_id:
            referral_repo = ReferralRepository(order_repo.session)
            link = await referral_repo.get_link_by_id(user.referred_by_link_id)
            if link:
                # Check if a transaction for this order already exists
                query = select(ReferralTransaction).where(ReferralTransaction.order_id == order.id)
                res = await order_repo.session.execute(query)
                existing_tx = res.scalar_one_or_none()
                
                if not existing_tx:
                    commission_stars = None
                    commission_crypto = None
                    
                    if order.amount_stars is not None:
                        commission_stars = float(order.amount_stars) * (link.reward_percent / 100.0)
                    if order.amount_crypto is not None:
                        commission_crypto = float(order.amount_crypto) * (link.reward_percent / 100.0)
                    
                    tx = await referral_repo.create_transaction(
                        referrer_id=link.referrer_id,
                        referee_id=user.id,
                        referral_link_id=link.id,
                        order_id=order.id,
                        amount_stars=commission_stars,
                        amount_crypto=commission_crypto,
                        crypto_currency=order.crypto_currency
                    )
                    logger.info(f"Referral transaction created: {tx.id} for order {order.id} via link {link.code}")
                    
                    # Notify referrer if it is a user
                    if link.referrer_id:
                        referrer_user = await user_repo.session.get(User, link.referrer_id)
                        if referrer_user:
                            referee_name = user.first_name
                            bonus_text = ""
                            if commission_stars:
                                bonus_text += f"{commission_stars:.1f} ⭐"
                            if commission_crypto:
                                if bonus_text:
                                    bonus_text += " / "
                                bonus_text += f"{commission_crypto:.4f} {order.crypto_currency or 'USD'}"
                            
                            notify_text = (
                                f"🎁 **Вам начислен реферальный бонус!**\n\n"
                                f"Пользователь {referee_name} оплатил тариф.\n"
                                f"Ваше вознаграждение: `{bonus_text}`"
                            )
                            try:
                                await bot.send_message(chat_id=referrer_user.telegram_id, text=notify_text, parse_mode="Markdown")
                            except Exception as ex:
                                logger.warning(f"Could not notify referrer {referrer_user.telegram_id}: {ex}")
    except Exception as e:
        logger.error(f"Error processing referral reward: {e}", exc_info=True)
    
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
                    
                    setting_repo = SettingRepository(order_repo.session)
                    text = await setting_repo.get("msg_successful_payment", DEFAULT_MESSAGES["msg_successful_payment"])
                    help_photo = await setting_repo.get("help_photo")
                    
                    builder = InlineKeyboardBuilder()
                    builder.button(text="🚀 Генерация сайта", url=auth_url)
                    builder.adjust(1)
                    
                    if help_photo:
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=help_photo,
                            caption=text,
                            parse_mode="Markdown",
                            reply_markup=builder.as_markup()
                        )
                    else:
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
