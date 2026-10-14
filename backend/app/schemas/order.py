from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime


class OrderItemCreate(BaseModel):
    product_barcode: str
    product_name: str
    unit_price: float
    quantity: int = 1


class OrderItemRead(OrderItemCreate):
    id: int
    total_price: float
    
    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    customer_identifier: str = "Customer #A104"
    items: List[OrderItemCreate]
    payment_method: str = "UPI"  # UPI, CARD, NETBANKING, CASH
    payment_status: str = "PAID"  # PAID, CASH_AT_COUNTER
    preferred_counter: Optional[str] = None
    cart_id: Optional[str] = None


class OrderRead(BaseModel):
    id: int
    order_number: str
    customer_identifier: str
    subtotal: float
    tax_amount: float
    discount_amount: float
    total_amount: float
    payment_status: str
    payment_method: str
    assigned_counter_number: Optional[str] = None
    is_verified_by_cashier: bool = False
    verification_status: str = "PENDING"
    verification_duration_seconds: Optional[int] = None
    verified_at: Optional[datetime] = None
    qr_token: str
    created_at: datetime
    items: List[OrderItemRead]

    model_config = ConfigDict(from_attributes=True)


class QRVerificationRequest(BaseModel):
    qr_token: str
    cashier_counter_number: str


class QRVerificationResponse(BaseModel):
    valid: bool
    order: Optional[OrderRead] = None
    message: str
