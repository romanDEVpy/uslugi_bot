from aiocryptopay import AioCryptoPay, Networks
from bot.config import settings
import logging

logger = logging.getLogger(__name__)

class CryptoBotHelper:
    def __init__(self):
        self.crypto = None
        if settings.CRYPTOBOT_TOKEN:
            network_type = Networks.MAIN_NET if settings.CRYPTOBOT_NETWORK == "MAIN_NET" else Networks.TEST_NET
            self.crypto = AioCryptoPay(token=settings.CRYPTOBOT_TOKEN, network=network_type)
            logger.info(f"CryptoBot initialized on network: {settings.CRYPTOBOT_NETWORK}")
        else:
            logger.warning("CryptoBot token is missing! Crypto payments will not be available.")

    async def create_invoice(self, plan: str, order_id: int) -> tuple[str, str]:
        """
        Creates an invoice in CryptoBot.
        Returns: (invoice_url, invoice_id)
        """
        if not self.crypto:
            raise ValueError("CryptoBot is not configured (missing token).")

        price_map = {
            "day": settings.CRYPTO_PRICE_DAY,
            "week": settings.CRYPTO_PRICE_WEEK,
            "month": settings.CRYPTO_PRICE_MONTH
        }
        amount = price_map.get(plan, settings.CRYPTO_PRICE_DAY)

        plan_names = {
            "day": "1 День",
            "week": "1 Неделя",
            "month": "1 Месяц"
        }
        plan_name = plan_names.get(plan, plan)

        logger.info(f"Creating CryptoBot invoice for order {order_id} (amount: ${amount})")

        # Create fiat-based invoice in USD, letting CryptoBot handle conversion to cryptos (e.g. USDT, TON, BTC)
        invoice = await self.crypto.create_invoice(
            amount=amount,
            fiat="USD",
            currency_type="fiat",
            payload=f"crypto_order:{order_id}",
            description=f"Тариф {plan_name} — Госуслуги Офлайн"
        )
        
        return invoice.bot_invoice_url, str(invoice.invoice_id)

    async def get_invoice_status(self, invoice_id: str) -> str:
        """Retrieves current invoice status: 'active', 'paid', 'expired'"""
        if not self.crypto:
            return "inactive"
        try:
            invoices = await self.crypto.get_invoices(invoice_ids=int(invoice_id))
            if invoices:
                return invoices[0].status
            return "not_found"
        except Exception as e:
            logger.error(f"Error checking CryptoBot invoice {invoice_id}: {e}")
            return "error"

    async def close(self):
        if self.crypto:
            await self.crypto.close()

# Singleton helper
cryptobot = CryptoBotHelper()
