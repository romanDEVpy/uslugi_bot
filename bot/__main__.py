import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from bot.config import settings
from bot.db.engine import init_db, async_session_maker
from bot.middlewares.db_session import DbSessionMiddleware
from bot.handlers import start, generate, payment, my_sites, admin
from bot.utils.scheduler import start_scheduler
from bot.payments.cryptobot import cryptobot

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

async def main():
    setup_logging()
    logger = logging.getLogger("bot")
    
    logger.info("Initializing database...")
    await init_db()

    # Initialize bot and dispatcher
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()

    # Register Middlewares
    dp.update.outer_middleware(DbSessionMiddleware(async_session_maker))

    # Register Routers
    dp.include_router(start.router)
    dp.include_router(generate.router)
    dp.include_router(payment.router)
    dp.include_router(my_sites.router)
    dp.include_router(admin.router)

    # Start cleanup scheduler
    start_scheduler(bot)

    logger.info("Bot is starting polling...")
    try:
        await dp.start_polling(bot)
    finally:
        logger.info("Closing sessions...")
        await cryptobot.close()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
