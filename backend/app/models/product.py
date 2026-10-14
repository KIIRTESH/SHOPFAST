from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Float, Integer, Boolean
from app.models.base import Base, TimestampMixin


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barcode: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="General", nullable=False)
    icon: Mapped[str] = mapped_column(String(32), default="📦", nullable=False)
    stock_qty: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    initial_stock_qty: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def stock(self) -> int:
        return self.stock_qty

    @property
    def stock_change(self) -> int:
        return self.stock_qty - self.initial_stock_qty
