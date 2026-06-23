from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
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
