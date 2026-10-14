from typing import List, Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Float, Integer, ForeignKey, UniqueConstraint
from app.models.base import Base, TimestampMixin


class Cart(Base, TimestampMixin):
    __tablename__ = "carts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    customer_identifier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)

    items: Mapped[List["CartItem"]] = relationship(
        "CartItem", 
        back_populates="cart", 
        cascade="all, delete-orphan",
        lazy="selectin"
    )


class CartItem(Base, TimestampMixin):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "product_barcode", name="uq_cart_item_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cart_id: Mapped[str] = mapped_column(
        String(64), 
        ForeignKey("carts.id", ondelete="CASCADE"), 
        index=True, 
        nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("products.id"), 
        nullable=False
    )
    product_barcode: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="General", nullable=False)
    icon: Mapped[str] = mapped_column(String(32), default="📦", nullable=False)

    cart: Mapped["Cart"] = relationship("Cart", back_populates="items")
