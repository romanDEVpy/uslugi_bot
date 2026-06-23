from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from bot.keyboards import inline
from bot.db.repositories import UserRepository
from bot.config import settings
import logging

logger = logging.getLogger(__name__)
router = Router()

HELP_TEXT = (
    "ℹ️ **Как работает бот:**\n\n"
    "1️⃣ Выберите тариф и оплатите услугу удобным способом (Stars или CryptoBot).\n"
    "2️⃣ После оплаты бот отправит вам уникальную одноразовую ссылку на форму авторизации.\n"
    "3️⃣ Перейдите по ссылке, введите ваши учетные данные Госуслуг и дождитесь завершения генерации.\n"
    "4️⃣ Бот пришлет ссылку на ваш личный хостинг, где вы сможете просматривать скачанный профиль в офлайн-стиле.\n\n"
    "🛡️ **Безопасность:** мы не сохраняем ваши учетные данные. Авторизация происходит напрямую через автоматизированный сеанс Playwright. Сессионные куки уничтожаются сразу после загрузки сайта."
)

@router.message(CommandStart())
async def cmd_start(message: Message, user_repo: UserRepository):
    telegram_id = message.from_user.id
    first_name = message.from_user.first_name
    username = message.from_user.username

    # Register user in DB
    user = await user_repo.get_or_create(
        telegram_id=telegram_id,
        first_name=first_name,
        username=username
    )

    # Check if user is in admin list and update in DB
    if telegram_id in settings.ADMIN_IDS and not user.is_admin:
        user.is_admin = True
        logger.info(f"User {telegram_id} marked as Admin.")

    welcome_msg = (
        f"👋 Привет, {first_name}!\n\n"
        "Добро пожаловать в бот **Госуслуги Офлайн**.\n"
        "Я помогу вам скачать полную копию вашего профиля Госуслуг (Личные данные + Паспорт РФ) "
        "и разместить ее на защищенном временном хостинге.\n\n"
        "Выберите нужное действие на панели ниже:"
    )

    await message.answer(welcome_msg, parse_mode="Markdown", reply_markup=inline.get_main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="Markdown", reply_markup=inline.get_main_menu())


@router.message(Command("admin"))
async def cmd_admin(message: Message, user_repo: UserRepository):
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    if not user or not user.is_admin:
        return  # Ignore non-admins silently

    await message.answer("🛠️ **Панель управления администратора**", parse_mode="Markdown", reply_markup=inline.get_admin_menu())


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.answer()
    welcome_msg = (
        "Добро пожаловать в бот **Госуслуги Офлайн**.\n"
        "Выберите нужное действие на панели ниже:"
    )
    await callback.message.edit_text(
        text=welcome_msg,
        reply_markup=inline.get_main_menu()
    )


@router.callback_query(F.data == "btn_help")
async def callback_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        text=HELP_TEXT,
        parse_mode="Markdown",
        reply_markup=inline.get_main_menu()
    )
