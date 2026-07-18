from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker
from bot.db.repositories import UserRepository, OrderRepository, HostedSiteRepository, SettingRepository, ReferralRepository

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_maker: async_sessionmaker):
        self.session_maker = session_maker
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        async with self.session_maker() as session:
            # Inject session
            data["session"] = session
            
            # Inject repositories
            data["user_repo"] = UserRepository(session)
            data["order_repo"] = OrderRepository(session)
            data["site_repo"] = HostedSiteRepository(session)
            data["setting_repo"] = SettingRepository(session)
            data["referral_repo"] = ReferralRepository(session)
            
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
