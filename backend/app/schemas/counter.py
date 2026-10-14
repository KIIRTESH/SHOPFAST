from pydantic import BaseModel, ConfigDict
from typing import List, Optional


class CounterBase(BaseModel):
    counter_number: str
    name: str
    is_active: bool = True
    is_express: bool = False
    max_queue_capacity: int = 15
    avg_scan_speed_factor: float = 1.0


class CounterCreate(CounterBase):
    pass


class CounterRead(CounterBase):
    id: int
    current_queue_length: int = 0
    estimated_wait_seconds: float = 0.0
    counter_revenue: float = 0.0
    
    model_config = ConfigDict(from_attributes=True)


class CounterMetrics(BaseModel):
    counter_number: str
    active_customers_in_line: int
    items_in_queue: int
    avg_throughput_items_per_min: float
    verified_today_count: int
