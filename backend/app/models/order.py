from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, Text, DateTime
from typing import List, Optional, TYPE_CHECKING
from datetime import datetime
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.counter import Counter
    from app.models.user import User


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    customer_identifier: Mapped[str] = mapped_column(String(100), default="Guest", nullable=False)

    # Link to authenticated user — nullable for backward compat with existing rows
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Idempotency key to safely handle duplicate/retry checkout requests
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True, nullable=True)

    subtotal: Mapped[float] = mapped_column(Float, nullable=False)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)

    payment_status: Mapped[str] = mapped_column(String(32), default="PAID", nullable=False)
    payment_method: Mapped[str] = mapped_column(String(32), default="UPI", nullable=False)

    counter_id: Mapped[Optional[int]] = mapped_column(ForeignKey("counters.id"), nullable=True)
    assigned_counter_number: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, default="")

    is_verified_by_cashier: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # PENDING → IN_PROGRESS → CLEARED | FLAGGED
    verification_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    verification_duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)

    # Secure order reference stored in QR — only the order_number, nothing sensitive
    qr_token: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    counter: Mapped[Optional["Counter"]] = relationship("Counter", back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
    user: Mapped[Optional["User"]] = relationship("User", lazy="noload")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_barcode: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    verified_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_price: Mapped[float] = mapped_column(Float, nullable=False)

    order: Mapped["Order"] = relationship("Order", back_populates="items")
