from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import Command, CommandObject
from bot.keyboards import inline
from bot.db.repositories import UserRepository, OrderRepository, HostedSiteRepository, SettingRepository
from sqlalchemy import select, func
from bot.db.models import User, Order, HostedSite
from bot.config import DEFAULT_MESSAGES
import logging

logger = logging.getLogger(__name__)
router = Router()

class AdminStates(StatesGroup):
    waiting_broadcast_msg = State()
    waiting_welcome_photo = State()
    waiting_help_photo = State()
    waiting_message_text = State()

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


@router.message(Command("cancel"))
@router.message(F.text.casefold() == "cancel")
async def cancel_handler(message: Message, state: FSMContext) -> None:
    """Allow user to cancel any FSM state"""
    current_state = await state.get_state()
    if current_state is None:
        return

    logger.info(f"Cancelling state {current_state}")
    await state.clear()
    await message.answer(
        "❌ Действие отменено.",
        reply_markup=inline.get_admin_menu()
    )


@router.callback_query(F.data == "cmd_admin_back")
async def admin_back(callback: CallbackQuery):
    await callback.answer()
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            "🛠️ **Панель управления администратора**",
            parse_mode="Markdown",
            reply_markup=inline.get_admin_menu()
        )
    else:
        await callback.message.edit_text(
            "🛠️ **Панель управления администратора**",
            parse_mode="Markdown",
            reply_markup=inline.get_admin_menu()
        )


@router.callback_query(F.data.in_({"admin_photo_welcome", "admin_photo_help"}))
async def admin_photo_settings(callback: CallbackQuery, setting_repo: SettingRepository):
    await callback.answer()
    setting_name = "welcome" if callback.data == "admin_photo_welcome" else "help"
    key = "welcome_photo" if setting_name == "welcome" else "help_photo"
    title = "приветствия" if setting_name == "welcome" else "инструкции"
    
    file_id = await setting_repo.get(key)
    
    if file_id:
        text = f"🖼️ **Настройки фото {title}:**\n\nТекущее фото установлено (ID: `{file_id}`). Вы можете обновить его или удалить."
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=file_id,
            caption=text,
            parse_mode="Markdown",
            reply_markup=inline.get_photo_settings_keyboard(setting_name)
        )
    else:
        text = f"🖼️ **Настройки фото {title}:**\n\nТекущее фото **не установлено** (сообщение отправляется в текстовом формате)."
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(
                text=text,
                parse_mode="Markdown",
                reply_markup=inline.get_photo_settings_keyboard(setting_name)
            )
        else:
            await callback.message.edit_text(
                text=text,
                parse_mode="Markdown",
                reply_markup=inline.get_photo_settings_keyboard(setting_name)
            )


@router.callback_query(F.data.startswith("admin_set_photo_"))
async def admin_set_photo_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    setting_name = callback.data.split("_")[3]
    
    if setting_name == "welcome":
        await state.set_state(AdminStates.waiting_welcome_photo)
    else:
        await state.set_state(AdminStates.waiting_help_photo)
        
    title = "приветствия" if setting_name == "welcome" else "инструкции"
    text = f"📥 **Отправьте изображение для фото {title}:**\n\nИли напишите /cancel для отмены."
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text=text, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=text, parse_mode="Markdown")


@router.callback_query(F.data.startswith("admin_del_photo_"))
async def admin_del_photo(callback: CallbackQuery, setting_repo: SettingRepository):
    await callback.answer()
    setting_name = callback.data.split("_")[3]
    key = "welcome_photo" if setting_name == "welcome" else "help_photo"
    title = "приветствия" if setting_name == "welcome" else "инструкции"
    
    await setting_repo.set(key, None)
    
    text = f"❌ Фото для {title} успешно удалено."
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            text=text,
            reply_markup=inline.get_photo_settings_keyboard(setting_name)
        )
    else:
        await callback.message.edit_text(
            text=text,
            reply_markup=inline.get_photo_settings_keyboard(setting_name)
        )


@router.message(AdminStates.waiting_welcome_photo, F.photo)
@router.message(AdminStates.waiting_help_photo, F.photo)
async def process_photo_upload(message: Message, state: FSMContext, setting_repo: SettingRepository):
    current_state = await state.get_state()
    setting_name = "welcome" if current_state == AdminStates.waiting_welcome_photo.state else "help"
    key = "welcome_photo" if setting_name == "welcome" else "help_photo"
    title = "приветствия" if setting_name == "welcome" else "инструкции"
    
    photo = message.photo[-1]
    file_id = photo.file_id
    
    await setting_repo.set(key, file_id)
    await state.clear()
    
    await message.answer(
        f"✅ **Фото для {title} успешно установлено!**",
        parse_mode="Markdown",
        reply_markup=inline.get_photo_settings_keyboard(setting_name)
    )


@router.callback_query(F.data == "admin_edit_texts")
async def admin_edit_texts_menu(callback: CallbackQuery):
    await callback.answer()
    text = "📝 **Управление текстами сообщений бота:**\n\nВыберите из списка ниже сообщение, которое вы хотите отредактировать:"
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            text=text,
            parse_mode="Markdown",
            reply_markup=inline.get_messages_editor_keyboard()
        )
    else:
        await callback.message.edit_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=inline.get_messages_editor_keyboard()
        )


@router.callback_query(F.data.startswith("msg_view_"))
async def admin_view_msg_details(callback: CallbackQuery, setting_repo: SettingRepository):
    await callback.answer()
    msg_key = callback.data[9:]
    
    current_val = await setting_repo.get(msg_key)
    default_val = DEFAULT_MESSAGES.get(msg_key, "")
    
    desc_map = {
        "msg_welcome": "Приветственное сообщение при отправке команды /start. Поддерживает плейсхолдер `{first_name}`.",
        "msg_back_to_menu": "Приветственное сообщение при возвращении в главное меню по инлайн-кнопкам.",
        "msg_help": "Информационный текст инструкции, отправляемый по команде /help или кнопке «Помощь».",
        "msg_choose_plan": "Сообщение выбора тарифа (Day, Week, Month).",
        "msg_successful_payment": "Инструкция по генерации, отправляемая сразу после успешной оплаты.",
        "msg_my_sites_empty": "Текст, когда у пользователя нет активных сайтов.",
        "msg_my_sites_list": "Заголовок списка активных копий пользователя."
    }
    
    desc = desc_map.get(msg_key, "Дополнительное сообщение бота.")
    status = "⚠️ Используется стандартный текст" if current_val is None else "✅ Установлен измененный текст"
    display_text = current_val if current_val is not None else default_val
    
    text = (
        f"📝 **Сообщение:** `{msg_key}`\n"
        f"ℹ️ **Назначение:** {desc}\n"
        f"📊 **Статус:** {status}\n\n"
        f"--- **Текущий текст:** ---\n"
        f"{display_text}\n"
        f"---------------------------\n\n"
        f"Выберите действие:"
    )
    
    await callback.message.edit_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=inline.get_message_options_keyboard(msg_key)
    )


@router.callback_query(F.data.startswith("msg_reset_"))
async def admin_reset_msg(callback: CallbackQuery, setting_repo: SettingRepository):
    await callback.answer()
    msg_key = callback.data[10:]
    await setting_repo.set(msg_key, None)
    
    await callback.message.edit_text(
        text=f"🔄 Текст сообщения `{msg_key}` сброшен к стандартному.",
        reply_markup=inline.get_message_options_keyboard(msg_key)
    )


@router.callback_query(F.data.startswith("msg_edit_"))
async def admin_edit_msg_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    msg_key = callback.data[9:]
    
    await state.set_state(AdminStates.waiting_message_text)
    await state.update_data(edit_msg_key=msg_key)
    
    text = (
        f"✍️ **Редактирование сообщения `{msg_key}`**\n\n"
        f"Отправьте новый текст сообщения в ответ на это сообщение.\n"
        f"Вы можете использовать Markdown-разметку.\n\n"
        f"Для отмены отправьте /cancel."
    )
    
    await callback.message.edit_text(
        text=text,
        parse_mode="Markdown"
    )


@router.message(AdminStates.waiting_message_text, F.text)
async def process_msg_text_save(message: Message, state: FSMContext, setting_repo: SettingRepository):
    state_data = await state.get_data()
    msg_key = state_data.get("edit_msg_key")
    
    if not msg_key:
        await state.clear()
        await message.answer("❌ Произошла ошибка. Ключ редактирования не найден.", reply_markup=inline.get_admin_menu())
        return
        
    new_text = message.text.strip()
    await setting_repo.set(msg_key, new_text)
    await state.clear()
    
    await message.answer(
        text=f"✅ **Текст сообщения `{msg_key}` успешно обновлен!**",
        parse_mode="Markdown",
        reply_markup=inline.get_message_options_keyboard(msg_key)
    )
