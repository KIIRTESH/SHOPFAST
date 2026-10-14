from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Boolean, Float
from typing import List, TYPE_CHECKING
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.queue import QueueTicket
    from app.models.order import Order


class Counter(Base, TimestampMixin):
    __tablename__ = "counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    counter_number: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False) # e.g. "01", "03"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_express: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_queue_capacity: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    avg_scan_speed_factor: Mapped[float] = mapped_column(Float, default=1.0, nullable=False) # Cashier speed efficiency
    
    # Relationships
    queue_tickets: Mapped[List["QueueTicket"]] = relationship("QueueTicket", back_populates="counter", lazy="selectin")
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="counter", lazy="noload")
