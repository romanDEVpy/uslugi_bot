import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: List[int] | str = []

    # Database
    DATABASE_URL: str  # e.g. postgresql+asyncpg://bot:secret@localhost:5432/gosuslugi_bot

    # CryptoBot
    CRYPTOBOT_TOKEN: str = ""
    CRYPTOBOT_NETWORK: str = "TEST_NET"  # TEST_NET or MAIN_NET

    # Auth Server & Web Site Hosting
    AUTH_SERVER_URL: str = "http://localhost:8081"
    SITE_BASE_URL: str = "http://localhost:8081/view"

    # Prices in Stars (XTR)
    STARS_PRICE_DAY: int = 50
    STARS_PRICE_WEEK: int = 200
    STARS_PRICE_MONTH: int = 500

    # Prices in USD/fiat for CryptoBot (which supports fiat conversion)
    CRYPTO_PRICE_DAY: float = 1.0
    CRYPTO_PRICE_WEEK: float = 3.0
    CRYPTO_PRICE_MONTH: float = 8.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            if not v.strip():
                return []
            res = []
            for x in v.split(","):
                cleaned = x.strip().strip("[]()'\" ")
                if cleaned:
                    res.append(int(cleaned))
            return res
        if isinstance(v, int):
            return [v]
        return v

settings = Settings()

DEFAULT_MESSAGES = {
    "msg_welcome": (
        "👋 Привет, {first_name}!\n\n"
        "Добро пожаловать в бот **Г@суслуги Офлайн**.\n"
        "Я помогу вам скачать полную копию вашего профиля Г@суслуг "
        "и разместить ее на защищенном временном хостинге.\n\n"
        "Выберите нужное действие на панели ниже:"
    ),
    "msg_back_to_menu": (
        "Добро пожаловать в бот **Г@суслуги Офлайн**.\n"
        "Выберите нужное действие на панели ниже:"
    ),
    "msg_help": (
        "ℹ️ **Как работает бот:**\n\n"
        "1️⃣ Выберите тариф и оплатите услугу удобным способом (Stars или CryptoBot).\n"
        "2️⃣ После оплаты бот отправит вам уникальную одноразовую ссылку на форму авторизации.\n"
        "3️⃣ Перейдите по ссылке, введите ваши данные (tip: вводите данные которые хотите, например укажите 2008 год и меньше для покупки энергетиков или других 18+ товаров) и дождитесь завершения генерации.\n"
        "4️⃣ Бот пришлет ссылку на ваш личный хостинг, где вы сможете просматривать скачанный профиль в офлайн-стиле.\n\n"
        "🛡️ **Безопасность:** мы не сохраняем ваши учетные данные. Авторизация происходит напрямую через автоматизированный сеанс Playwright. Сессионные куки уничтожаются сразу после загрузки сайта."
    ),
    "msg_choose_plan": (
        "💳 **Выберите тарифный план:**\n\n"
        "Каждый тариф включает в себя **1 генерацию** актуального профиля Госуслуг "
        "и размещение сайта на хостинге на указанный период:\n\n"
        "• **1 День** — для быстрой сверки или демонстрации.\n"
        "• **1 Неделя** — оптимально для большинства задач.\n"
        "• **1 Месяц** — долгосрочный доступ к вашим данным."
    ),
    "msg_successful_payment": (
        "🎉 **Оплата успешно получена!**\n\n"
        "Мы готовы сгенерировать вашу копию профиля Госуслуг.\n\n"
        "👇 **Инструкция:**\n"
        "1. Нажмите кнопку **«Генерация сайта»** ниже.\n"
        "2. Введите **ФИО** и **дату рождения**.\n"
        "3. Дождитесь завершения генерации (обычно несколько секунд).\n\n"
        "Когда всё будет готово, я пришлю ссылку на ваш сайт прямо сюда!"
    ),
    "msg_my_sites_empty": (
        "📭 У вас пока нет активных офлайн-копий профиля Госуслуг.\n\n"
        "Вы можете сгенерировать новую копию прямо сейчас!"
    ),
    "msg_my_sites_list": (
        "🌐 **Ваши активные офлайн-копии:**"
    ),
}
