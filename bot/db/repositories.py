from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from bot.db.models import User, Order, HostedSite

class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, telegram_id: int, first_name: str, username: Optional[str] = None) -> User:
        """Retrieves an existing user or creates a new one."""
        query = select(User).where(User.telegram_id == telegram_id)
        result = await self.session.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=telegram_id,
                first_name=first_name,
                username=username
            )
            self.session.add(user)
            await self.session.flush()
        else:
            # Update user details if changed
            if user.first_name != first_name or user.username != username:
                user.first_name = first_name
                user.username = username
                await self.session.flush()

        return user

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        query = select(User).where(User.telegram_id == telegram_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_all(self) -> List[User]:
        query = select(User).order_by(User.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())


class OrderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: int, plan: str, payment_method: str) -> Order:
        order = Order(
            user_id=user_id,
            plan=plan,
            payment_method=payment_method,
            status="pending_payment"
        )
        self.session.add(order)
        await self.session.flush()
        return order

    async def get_by_id(self, order_id: int) -> Optional[Order]:
        query = select(Order).where(Order.id == order_id).options(selectinload(Order.user))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_payment_id(self, payment_id: str, payment_method: str) -> Optional[Order]:
        query = select(Order).where(
            Order.payment_id == payment_id,
            Order.payment_method == payment_method
        ).options(selectinload(Order.user))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def update_payment_details(self, order_id: int, payment_id: str, amount_stars: Optional[int] = None, amount_crypto: Optional[float] = None, crypto_currency: Optional[str] = None):
        query = update(Order).where(Order.id == order_id).values(
            payment_id=payment_id,
            amount_stars=amount_stars,
            amount_crypto=amount_crypto,
            crypto_currency=crypto_currency
        )
        await self.session.execute(query)

    async def mark_as_paid(self, order_id: int) -> Optional[Order]:
        order = await self.get_by_id(order_id)
        if order and order.status == "pending_payment":
            order.status = "paid"
            order.paid_at = datetime.utcnow()
            await self.session.flush()
        return order

    async def mark_as_generating(self, order_id: int) -> Optional[Order]:
        order = await self.get_by_id(order_id)
        if order:
            order.status = "generating"
            await self.session.flush()
        return order

    async def mark_as_ready(self, order_id: int, site_uuid: str, site_url: str, expires_at: datetime) -> Optional[Order]:
        order = await self.get_by_id(order_id)
        if order:
            order.status = "ready"
            order.site_uuid = site_uuid
            order.site_url = site_url
            order.expires_at = expires_at
            await self.session.flush()
        return order

    async def list_recent(self, limit: int = 20) -> List[Order]:
        query = select(Order).order_by(Order.created_at.desc()).limit(limit).options(selectinload(Order.user))
        result = await self.session.execute(query)
        return list(result.scalars().all())


class HostedSiteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, uuid: str, order_id: int, user_id: int, local_path: str, public_url: str, expires_at: datetime) -> HostedSite:
        site = HostedSite(
            uuid=uuid,
            order_id=order_id,
            user_id=user_id,
            local_path=local_path,
            public_url=public_url,
            expires_at=expires_at,
            is_active=True
        )
        self.session.add(site)
        await self.session.flush()
        return site

    async def get_by_uuid(self, uuid: str) -> Optional[HostedSite]:
        query = select(HostedSite).where(HostedSite.uuid == uuid).options(selectinload(HostedSite.order))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_active_by_user(self, user_id: int) -> List[HostedSite]:
        query = select(HostedSite).where(
            HostedSite.user_id == user_id,
            HostedSite.is_active == True,
            HostedSite.expires_at > datetime.utcnow()
        ).order_by(HostedSite.expires_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_expired_sites(self) -> List[HostedSite]:
        query = select(HostedSite).where(
            HostedSite.is_active == True,
            HostedSite.expires_at <= datetime.utcnow()
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def deactivate_site(self, site_id: int):
        query = update(HostedSite).where(HostedSite.id == site_id).values(is_active=False)
        await self.session.execute(query)
        
    async def extend_expiration(self, uuid: str, additional_time: timedelta) -> Optional[HostedSite]:
        site = await self.get_by_uuid(uuid)
        if site:
            if site.expires_at < datetime.utcnow():
                # If already expired, start extension from now
                site.expires_at = datetime.utcnow() + additional_time
            else:
                site.expires_at += additional_time
            site.is_active = True
            await self.session.flush()
        return site
