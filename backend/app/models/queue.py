from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, ForeignKey, Float
from typing import Optional, TYPE_CHECKING
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.counter import Counter


class QueueTicket(Base, TimestampMixin):
    __tablename__ = "queue_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False) # e.g. "Q-104"
    customer_name: Mapped[str] = mapped_column(String(100), default="Walk-In Customer", nullable=False)
    
    counter_id: Mapped[int] = mapped_column(ForeignKey("counters.id"), nullable=False)
    items_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    estimated_wait_seconds: Mapped[float] = mapped_column(Float, default=60.0, nullable=False)
    
    status: Mapped[str] = mapped_column(String(32), default="WAITING", nullable=False) # WAITING, PROCESSING, COMPLETED, CANCELLED
    
    counter: Mapped["Counter"] = relationship("Counter", back_populates="queue_tickets")
