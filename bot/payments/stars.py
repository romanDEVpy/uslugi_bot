from aiogram import Bot
from aiogram.types import LabeledPrice
from bot.config import settings
import logging

logger = logging.getLogger(__name__)

async def send_stars_invoice(bot: Bot, chat_id: int, plan: str, order_id: int):
    """Sends a Telegram Stars invoice to the user."""
    price_map = {
        "day": settings.STARS_PRICE_DAY,
        "week": settings.STARS_PRICE_WEEK,
        "month": settings.STARS_PRICE_MONTH
    }
    
    amount = price_map.get(plan, settings.STARS_PRICE_DAY)
    
    plan_names = {
        "day": "1 День",
        "week": "1 Неделя",
        "month": "1 Месяц"
    }
    
    plan_name = plan_names.get(plan, plan)
    
    title = f"Госуслуги Офлайн — {plan_name}"
    description = f"Оплата генерации и хостинга сайта на {plan_name}."
    payload = f"stars_order:{order_id}"
    
    logger.info(f"Sending Stars invoice for order {order_id} to chat {chat_id} (amount: {amount} stars)")
    
    return await bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",  # Must be empty for Telegram Stars
        currency="XTR",
        prices=[
            LabeledPrice(label=f"Тариф {plan_name}", amount=amount)
        ],
        start_parameter=f"pay_stars_{order_id}"
    )
