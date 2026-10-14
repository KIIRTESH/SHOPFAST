from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Boolean, ForeignKey
from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """Authenticated user — either a customer or admin/counter staff."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    pin_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    # "customer" or "admin"
    role: Mapped[str] = mapped_column(String(16), default="customer", nullable=False)
    # For admin users only — which counter they operate
    counter_number: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sessions: Mapped[list["UserSession"]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan", lazy="noload"
    )
