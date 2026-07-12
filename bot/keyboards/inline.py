from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.config import settings

def get_main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Генерировать сайт", callback_data="btn_generate")
    builder.button(text="📋 Мои сайты", callback_data="btn_my_sites")
    builder.button(text="❓ Помощь", callback_data="btn_help")
    builder.adjust(1, 2)
    return builder.as_markup()

def get_plans_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"📅 1 День — {settings.STARS_PRICE_DAY} ⭐ / ${settings.CRYPTO_PRICE_DAY} 🪙",
        callback_data="plan_day"
    )
    builder.button(
        text=f"📅 1 Неделя — {settings.STARS_PRICE_WEEK} ⭐ / ${settings.CRYPTO_PRICE_WEEK} 🪙",
        callback_data="plan_week"
    )
    builder.button(
        text=f"📅 1 Месяц — {settings.STARS_PRICE_MONTH} ⭐ / ${settings.CRYPTO_PRICE_MONTH} 🪙",
        callback_data="plan_month"
    )
    builder.button(text="↩️ Назад", callback_data="back_to_menu")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()

def get_payment_methods(plan: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Telegram Stars", callback_data=f"pay_stars_{plan}")
    builder.button(text="🪙 CryptoBot", callback_data=f"pay_crypto_{plan}")
    builder.button(text="↩️ Назад", callback_data="btn_generate")
    builder.adjust(1, 1, 1)
    return builder.as_markup()

def get_site_keyboard(site_uuid: str, public_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Открыть сайт", url=public_url)
    builder.button(text="➕ Продлить хостинг", callback_data=f"extend_{site_uuid}")
    builder.button(text="↩️ В меню", callback_data="back_to_menu")
    builder.adjust(1, 1, 1)
    return builder.as_markup()

def get_sites_list_keyboard(sites) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in sites:
        expires_str = s.expires_at.strftime('%d.%m.%Y')
        builder.button(
            text=f"🌐 До {expires_str} (Подробнее)",
            callback_data=f"view_site_{s.uuid}"
        )
    builder.button(text="↩️ В меню", callback_data="back_to_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="✉️ Рассылка", callback_data="admin_broadcast")
    builder.button(text="🖼️ Фото приветствия", callback_data="admin_photo_welcome")
    builder.button(text="🖼️ Фото инструкции", callback_data="admin_photo_help")
    builder.button(text="📝 Изменить тексты", callback_data="admin_edit_texts")
    builder.button(text="↩️ В меню", callback_data="back_to_menu")
    builder.adjust(1, 1, 1, 1, 1, 1)
    return builder.as_markup()

def get_photo_settings_keyboard(setting_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Загрузить новое фото", callback_data=f"admin_set_photo_{setting_name}")
    builder.button(text="❌ Удалить фото", callback_data=f"admin_del_photo_{setting_name}")
    builder.button(text="↩️ Назад", callback_data="cmd_admin_back")
    builder.adjust(1, 1, 1)
    return builder.as_markup()

def get_messages_editor_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Приветствие (/start)", callback_data="msg_view_msg_welcome")
    builder.button(text="Приветствие (Меню)", callback_data="msg_view_msg_back_to_menu")
    builder.button(text="Инструкция (/help)", callback_data="msg_view_msg_help")
    builder.button(text="Выбор тарифа", callback_data="msg_view_msg_choose_plan")
    builder.button(text="Успешная оплата", callback_data="msg_view_msg_successful_payment")
    builder.button(text="Мои сайты (Пусто)", callback_data="msg_view_msg_my_sites_empty")
    builder.button(text="Мои сайты (Список)", callback_data="msg_view_msg_my_sites_list")
    builder.button(text="↩️ Назад", callback_data="cmd_admin_back")
    builder.adjust(1)
    return builder.as_markup()

def get_message_options_keyboard(msg_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Редактировать текст", callback_data=f"msg_edit_{msg_key}")
    builder.button(text="🔄 Сбросить на стандартный", callback_data=f"msg_reset_{msg_key}")
    builder.button(text="↩️ Назад", callback_data="admin_edit_texts")
    builder.adjust(1, 1, 1)
    return builder.as_markup()
