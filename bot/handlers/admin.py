from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import Command, CommandObject
from bot.keyboards import inline
from bot.db.repositories import UserRepository, OrderRepository, HostedSiteRepository
from sqlalchemy import select, func
from bot.db.models import User, Order, HostedSite
import logging

logger = logging.getLogger(__name__)
router = Router()

class AdminStates(StatesGroup):
    waiting_broadcast_msg = State()

@router.callback_query(F.data == "admin_stats")
async def show_admin_stats(callback: CallbackQuery, session):
    await callback.answer()
    
    # Run DB aggregate queries using the session
    try:
        # Total users
        total_users = (await session.execute(select(func.count(User.id)))).scalar_one()
        
        # Total orders
        total_orders = (await session.execute(select(func.count(Order.id)))).scalar_one()
        
        # Paid orders
        paid_orders = (await session.execute(select(func.count(Order.id)).where(Order.status != "pending_payment"))).scalar_one()
        
        # Total Stars revenue
        total_stars = (await session.execute(select(func.sum(Order.amount_stars)).where(Order.status != "pending_payment"))).scalar_one() or 0
        
        # Total USD/Crypto revenue
        total_usd = (await session.execute(select(func.sum(Order.amount_crypto)).where(Order.status != "pending_payment"))).scalar_one() or 0.0
        
        # Active sites
        active_sites = (await session.execute(select(func.count(HostedSite.id)).where(HostedSite.is_active == True))).scalar_one()

        text = (
            "📊 **Статистика бота:**\n\n"
            f"👥 **Всего пользователей:** {total_users}\n"
            f"🛒 **Всего заказов:** {total_orders}\n"
            f"✅ **Оплачено заказов:** {paid_orders}\n"
            f"⭐ **Выручка Telegram Stars:** {total_stars} ⭐\n"
            f"🪙 **Выручка CryptoBot:** ${total_usd:.2f}\n"
            f"🌐 **Активных сайтов на хосте:** {active_sites}"
        )
        
        await callback.message.edit_text(text=text, parse_mode="Markdown", reply_markup=inline.get_admin_menu())
    except Exception as e:
        logger.error(f"Error loading admin stats: {e}", exc_info=True)
        await callback.message.edit_text("❌ Не удалось загрузить статистику.", reply_markup=inline.get_admin_menu())


@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.waiting_broadcast_msg)
    await callback.message.edit_text("✉️ **Отправьте сообщение для рассылки (текст, фото и т.д.):**\nДля отмены напишите /cancel.")


@router.message(AdminStates.waiting_broadcast_msg)
async def process_broadcast_message(message: Message, state: FSMContext, bot: Bot, user_repo: UserRepository):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена.", reply_markup=inline.get_admin_menu())
        return

    users = await user_repo.list_all()
    await state.clear()
    
    await message.answer(f"🚀 Начинаю рассылку для {len(users)} пользователей...")
    
    success = 0
    failed = 0
    
    for u in users:
        try:
            # Copy message to each user
            await message.copy_to(chat_id=u.telegram_id)
            success += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast to {u.telegram_id}: {e}")
            failed += 1
            
    await message.answer(
        f"✅ **Рассылка завершена!**\n\n"
        f"Успешно доставлено: {success}\n"
        f"Не удалось отправить: {failed}",
        reply_markup=inline.get_admin_menu()
    )


@router.message(Command("refund"))
async def cmd_refund(message: Message, command: CommandObject, bot: Bot, user_repo: UserRepository, order_repo: OrderRepository, session):
    """Admin command to refund a Telegram Stars payment using its charge ID."""
    # Verify admin status
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    if not user or not user.is_admin:
        return

    charge_id = command.args
    if not charge_id:
        await message.answer("⚠️ **Использование:** `/refund <payment_charge_id>`", parse_mode="Markdown")
        return

    try:
        # Find order in DB by payment_id and method "stars"
        order = await order_repo.get_by_payment_id(payment_id=charge_id, payment_method="stars")

        if not order:
            await message.answer(f"❌ Заказ с ID платежа `{charge_id}` не найден в базе данных.", parse_mode="Markdown")
            return

        if order.status == "refunded":
            await message.answer("ℹ️ Этот платеж уже был возвращен ранее.")
            return

        if not order.user:
            await message.answer("❌ Не удалось найти пользователя для этого заказа.", parse_mode="Markdown")
            return

        # Refund via Bot API
        success = await bot.refund_star_payment(
            user_id=order.user.telegram_id,
            telegram_payment_charge_id=charge_id
        )

        if success:
            # Update order status
            order.status = "refunded"
            await session.commit()

            await message.answer(
                f"✅ **Возврат средств успешно выполнен!**\n\n"
                f"👤 Пользователь: `{order.user.telegram_id}`\n"
                f"Сумма: `{order.amount_stars}` ⭐\n"
                f"ID транзакции: `{charge_id}`",
                parse_mode="Markdown"
            )

            # Notify user
            try:
                refund_notice = (
                    f"💸 **Вам оформлен возврат средств!**\n\n"
                    f"Администратор вернул вам `{order.amount_stars}` ⭐ за заказ `#{order.id}`.\n"
                    f"Звезды зачислены обратно на ваш баланс Telegram."
                )
                await bot.send_message(chat_id=order.user.telegram_id, text=refund_notice, parse_mode="Markdown")
            except Exception as notify_err:
                logger.warning(f"Failed to notify user about refund: {notify_err}")
        else:
            await message.answer("❌ Telegram API вернул `False` при попытке возврата.")

    except Exception as e:
        logger.error(f"Error performing refund: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка выполнения возврата: {e}")
