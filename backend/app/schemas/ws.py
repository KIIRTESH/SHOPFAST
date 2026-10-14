from pydantic import BaseModel
from typing import Any, Optional


class WebSocketMessage(BaseModel):
    event: str  # "QUEUE_UPDATED", "CUSTOMER_ARRIVED", "ORDER_VERIFIED", "COUNTER_STATUS"
    counter_number: Optional[str] = None
    data: Any
