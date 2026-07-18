from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message, CallbackQuery
from bot.keyboards import inline
from bot.db.repositories import UserRepository, SettingRepository, ReferralRepository
from bot.db.models import User
from sqlalchemy import select
from bot.config import settings, DEFAULT_MESSAGES
import logging

logger = logging.getLogger(__name__)
router = Router()

HELP_TEXT = (
    "ℹ️ **Как работает бот:**\n\n"
    "1️⃣ Выберите тариф и оплатите услугу удобным способом (Stars или CryptoBot).\n"
    "2️⃣ После оплаты бот отправит вам уникальную одноразовую ссылку на форму авторизации.\n"
    "3️⃣ Перейдите по ссылке, введите ваши данные (tip: вводите данные которые хотите, например укажите 2008 год и меньше для покупки энергетиков или других 18+ товаров) и дождитесь завершения генерации.\n"
    "4️⃣ Бот пришлет ссылку на ваш личный хостинг, где вы сможете просматривать скачанный профиль в офлайн-стиле.\n\n"
    "🛡️ **Безопасность:** мы не сохраняем ваши учетные данные. Авторизация происходит напрямую через автоматизированный сеанс Playwright. Сессионные куки уничтожаются сразу после загрузки сайта."
)

@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    user_repo: UserRepository,
    setting_repo: SettingRepository,
    referral_repo: ReferralRepository
):
    telegram_id = message.from_user.id
    first_name = message.from_user.first_name
    username = message.from_user.username

    # Check start payload for referral code
    referred_by_id = None
    referred_by_link_id = None

    if command.args and command.args.startswith("ref_"):
        ref_code = command.args[4:]
        link = await referral_repo.get_link_by_code(ref_code)
        if link:
            # Prevent self-referral (if referrer exists and matches this user)
            is_self = False
            if link.referrer_id:
                query = select(User.telegram_id).where(User.id == link.referrer_id)
                res = await referral_repo.session.execute(query)
                referrer_tg_id = res.scalar_one_or_none()
                if referrer_tg_id == telegram_id:
                    is_self = True
            
            if not is_self:
                existing_user = await user_repo.get_by_telegram_id(telegram_id)
                if not existing_user:
                    referred_by_id = link.referrer_id
                    referred_by_link_id = link.id
                    logger.info(f"User {telegram_id} referred by link {link.code} (referrer_id: {referred_by_id})")

    # Register user in DB
    user = await user_repo.get_or_create(
        telegram_id=telegram_id,
        first_name=first_name,
        username=username,
        referred_by_id=referred_by_id,
        referred_by_link_id=referred_by_link_id
    )

    # Check if user is in admin list and update in DB
    if telegram_id in settings.ADMIN_IDS and not user.is_admin:
        user.is_admin = True
        logger.info(f"User {telegram_id} marked as Admin.")

    welcome_tpl = await setting_repo.get("msg_welcome", DEFAULT_MESSAGES["msg_welcome"])
    welcome_msg = welcome_tpl.format(first_name=first_name)

    welcome_photo = await setting_repo.get("welcome_photo")
    if welcome_photo:
        await message.answer_photo(
            photo=welcome_photo,
            caption=welcome_msg,
            parse_mode="Markdown",
            reply_markup=inline.get_main_menu()
        )
    else:
        await message.answer(welcome_msg, parse_mode="Markdown", reply_markup=inline.get_main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message, setting_repo: SettingRepository):
    help_msg = await setting_repo.get("msg_help", DEFAULT_MESSAGES["msg_help"])
    help_photo = await setting_repo.get("help_photo")
    if help_photo:
        await message.answer_photo(
            photo=help_photo,
            caption=help_msg,
            parse_mode="Markdown",
            reply_markup=inline.get_main_menu()
        )
    else:
        await message.answer(help_msg, parse_mode="Markdown", reply_markup=inline.get_main_menu())


@router.message(Command("admin"))
async def cmd_admin(message: Message, user_repo: UserRepository):
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    if not user or not user.is_admin:
        return  # Ignore non-admins silently

    await message.answer("🛠️ **Панель управления администратора**", parse_mode="Markdown", reply_markup=inline.get_admin_menu())


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, setting_repo: SettingRepository):
    await callback.answer()
    welcome_msg = await setting_repo.get("msg_back_to_menu", DEFAULT_MESSAGES["msg_back_to_menu"])
    welcome_photo = await setting_repo.get("welcome_photo")
    
    if welcome_photo:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=welcome_photo,
            caption=welcome_msg,
            parse_mode="Markdown",
            reply_markup=inline.get_main_menu()
        )
    else:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(
                text=welcome_msg,
                parse_mode="Markdown",
                reply_markup=inline.get_main_menu()
            )
        else:
            await callback.message.edit_text(
                text=welcome_msg,
                reply_markup=inline.get_main_menu()
            )


@router.callback_query(F.data == "btn_help")
async def callback_help(callback: CallbackQuery, setting_repo: SettingRepository):
    await callback.answer()
    
    help_msg = await setting_repo.get("msg_help", DEFAULT_MESSAGES["msg_help"])
    help_photo = await setting_repo.get("help_photo")
    
    if help_photo:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=help_photo,
            caption=help_msg,
            parse_mode="Markdown",
            reply_markup=inline.get_main_menu()
        )
    else:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(
                text=help_msg,
                parse_mode="Markdown",
                reply_markup=inline.get_main_menu()
            )
        else:
            await callback.message.edit_text(
                text=help_msg,
                parse_mode="Markdown",
                reply_markup=inline.get_main_menu()
            )


@router.callback_query(F.data == "btn_referrals")
async def callback_referrals(
    callback: CallbackQuery,
    bot: Bot,
    user_repo: UserRepository,
    referral_repo: ReferralRepository
):
    await callback.answer()
    
    # Get user from DB
    user = await user_repo.get_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.message.answer("❌ Пользователь не найден в базе данных.")
        return
        
    # Get or create their referral link
    ref_link = await referral_repo.get_or_create_user_link(user.id)
    bot_info = await bot.get_me()
    
    # Obfuscated link using the random code
    link_url = f"https://t.me/{bot_info.username}?start=ref_{ref_link.code}"
    
    # Get statistics
    stats = await referral_repo.get_referral_stats(user.id)
    
    text = (
        "👥 **Реферальная программа**\n\n"
        "Приглашайте друзей и получайте прибыль с их оплат!\n\n"
        f"🔗 Ваша реферальная ссылка (владельца невозможно определить по ссылке):\n`{link_url}`\n\n"
        f"📊 **Ваша статистика:**\n"
        f"• Приглашено пользователей: `{stats['total_referees']}`\n"
        f"• Заработано Telegram Stars: `{stats['total_earned_stars']:.1f} ⭐`\n"
        f"• Заработано Crypto: `{stats['total_earned_crypto']:.4f} USD`"
    )
    
    builder = inline.InlineKeyboardBuilder()
    builder.button(text="↩️ Назад", callback_data="back_to_menu")
    builder.adjust(1)
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            text=text,
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )
    else:
        await callback.message.edit_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )
