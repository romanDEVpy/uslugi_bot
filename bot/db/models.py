from datetime import datetime
from typing import List, Optional
from sqlalchemy import BigInteger, ForeignKey, String, Integer, Float, DateTime, Boolean, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    orders: Mapped[List["Order"]] = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    hosted_sites: Mapped[List["HostedSite"]] = relationship("HostedSite", back_populates="user", cascade="all, delete-orphan")

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan: Mapped[str] = mapped_column(String(50), nullable=False)  # "day", "week", "month"
    status: Mapped[str] = mapped_column(String(50), default="pending_payment", nullable=False)  # "pending_payment", "paid", "generating", "ready", "expired"
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)  # "stars", "cryptobot"
    payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # CryptoBot invoice_id or Stars charge ID
    amount_stars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amount_crypto: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    crypto_currency: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    site_uuid: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    site_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="orders")
    hosted_site: Mapped[Optional["HostedSite"]] = relationship("HostedSite", back_populates="order", uselist=False, cascade="all, delete-orphan")

class HostedSite(Base):
    __tablename__ = "hosted_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    public_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="hosted_sites")
    order: Mapped["Order"] = relationship("Order", back_populates="hosted_site")


class BotSettings(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
