from aiogram import Router, F, Bot
from aiogram.types import PreCheckoutQuery, Message
from bot.db.repositories import OrderRepository
from bot.handlers.generate import handle_successful_payment
import logging

logger = logging.getLogger(__name__)
router = Router()

@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    """Answers pre-checkout query to approve Telegram Stars payment."""
    logger.info(f"Received PreCheckoutQuery from user {pre_checkout_query.from_user.id}")
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot, order_repo: OrderRepository):
    """Processes successful payment for Telegram Stars."""
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload
    
    logger.info(f"Successful payment received: {payload} from user {message.from_user.id}")
    
    if not payload or not payload.startswith("stars_order:"):
        logger.warning(f"Invalid invoice payload: {payload}")
        return

    try:
        order_id = int(payload.split(":")[1])
    except ValueError:
        logger.error(f"Cannot parse order_id from payload: {payload}")
        return

    order = await order_repo.get_by_id(order_id)
    if not order:
        logger.error(f"Order {order_id} not found after payment.")
        return

    # Update order with Telegram Charge ID
    await order_repo.update_payment_details(
        order_id=order_id,
        payment_id=payment_info.telegram_payment_charge_id,
        amount_stars=payment_info.total_amount
    )

    # Transition status to paid, trigger generation initiation
    await handle_successful_payment(bot, message.chat.id, order, order_repo)
