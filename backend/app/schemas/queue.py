from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class QueueTicketCreate(BaseModel):
    customer_name: str = "Walk-In Customer"
    items_count: int = 1


class QueueAllocationResponse(BaseModel):
    ticket_number: str
    assigned_counter_number: str
    counter_name: str
    queue_position: int
    estimated_wait_seconds: float
    estimated_wait_minutes: float
    is_express: bool
    instructions: str


class QueueTicketRead(BaseModel):
    id: int
    ticket_number: str
    customer_name: str
    counter_id: int
    items_count: int
    estimated_wait_seconds: float
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
