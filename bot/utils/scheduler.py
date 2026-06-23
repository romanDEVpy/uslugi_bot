import os
import shutil
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncioScheduler
from aiogram import Bot
from bot.db.engine import async_session_maker
from bot.db.repositories import HostedSiteRepository, OrderRepository

logger = logging.getLogger(__name__)

# Base directory where hosted sites are stored
GENERATED_SITES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "generated_sites")
)

async def cleanup_expired_sites(bot: Bot):
    """Checks database for expired hosted sites, deletes their folders, and notifies users."""
    logger.info("Scheduler: checking for expired hosted sites...")
    
    async with async_session_maker() as session:
        site_repo = HostedSiteRepository(session)
        order_repo = OrderRepository(session)
        
        expired_sites = await site_repo.get_expired_sites()
        if not expired_sites:
            logger.info("Scheduler: no expired sites found.")
            return
            
        logger.info(f"Scheduler: found {len(expired_sites)} expired sites.")
        
        for site in expired_sites:
            try:
                # 1. Delete files locally
                dir_path = os.path.join(GENERATED_SITES_DIR, site.uuid)
                if os.path.exists(dir_path):
                    shutil.rmtree(dir_path)
                    logger.info(f"Deleted folder: {dir_path}")
                else:
                    logger.warning(f"Folder not found for deletion: {dir_path}")
                    
                # 2. Deactivate in database
                await site_repo.deactivate_site(site.id)
                
                # 3. Update Order status
                order = await order_repo.get_by_id(site.order_id)
                if order:
                    order.status = "expired"
                    
                # Commit changes for this site
                await session.commit()
                
                # 4. Notify user
                if order and order.user:
                    user_tg_id = order.user.telegram_id
                    try:
                        expire_notice = (
                            f"⏰ **Срок действия хостинга истёк!**\n\n"
                            f"Ваш сайт `{site.uuid}` был удален с наших серверов.\n"
                            f"Если вам снова понадобится копия, вы можете запустить новую генерацию в меню."
                        )
                        await bot.send_message(chat_id=user_tg_id, text=expire_notice, parse_mode="Markdown")
                        logger.info(f"Notification sent to user {user_tg_id} regarding site expiration.")
                    except Exception as e:
                        logger.warning(f"Could not notify user {user_tg_id} about expiration: {e}")
                        
            except Exception as e:
                await session.rollback()
                logger.error(f"Error cleaning up site {site.uuid}: {e}", exc_info=True)


def start_scheduler(bot: Bot):
    """Starts the asyncio scheduler for cleanup task."""
    scheduler = AsyncioScheduler()
    # Run cleanup every 10 minutes
    scheduler.add_job(
        cleanup_expired_sites,
        "interval",
        minutes=10,
        args=[bot],
        next_run_time=datetime.now()
    )
    scheduler.start()
    logger.info("Asyncio scheduler started (cleanup every 10 mins).")
