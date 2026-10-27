from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class AdminItemVerificationState(BaseModel):
    product_barcode: str
    product_name: str
    expected_quantity: int
    verified_quantity: int
    is_matched: bool
    unit_price: float
    total_price: float
    icon: Optional[str] = "📦"

    model_config = ConfigDict(from_attributes=True)


class AdminOrderVerificationDetail(BaseModel):
    order_number: str
    customer_identifier: str
    total_amount: float
    subtotal: float
    tax_amount: float
    discount_amount: float
    payment_status: str
    payment_method: str
    assigned_counter_number: Optional[str] = None
    is_verified_by_cashier: bool
    verification_status: str  # PENDING, IN_PROGRESS, CLEARED, FLAGGED
    verification_duration_seconds: Optional[int] = None
    items_expected_count: int
    items_verified_count: int
    items_remaining_count: int
    is_all_matched: bool
    items: List[AdminItemVerificationState]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminLookupRequest(BaseModel):
    token_or_order_number: str
    counter_number: Optional[str] = None


class AdminScanItemRequest(BaseModel):
    order_number: str
    scanned_barcode: str
    counter_number: Optional[str] = None


class AdminScanItemResponse(BaseModel):
    status: str  # "MATCHED", "ALL_CLEARED", "OVER_SCANNED", "UNEXPECTED_ITEM"
    scanned_barcode: str
    product_name: Optional[str] = None
    expected_qty: Optional[int] = None
    scanned_qty: Optional[int] = None
    message: str
    is_all_matched: bool
    order: AdminOrderVerificationDetail


class AdminCompleteVerificationRequest(BaseModel):
    order_number: str
    counter_number: Optional[str] = None
    duration_seconds: Optional[int] = None


class AdminDiscrepancyActionRequest(BaseModel):
    order_number: str
    scanned_barcode: str
    action: str  # "REMOVE_AND_CONTINUE", "SEND_TO_REGULAR_CHECKOUT"
    counter_number: Optional[str] = None
    notes: Optional[str] = None


class AdminAnalyticsResponse(BaseModel):
    today_sales_total: float
    total_revenue: float = 0.0
    today_orders_count: int
    today_verified_count: int
    avg_verification_seconds: float
    flagged_discrepancies_count: int
    active_queue_length: int
    open_counters_count: int = 0
    closed_counters_count: int = 0
    active_staff_count: int = 0
    pending_verifications_count: int = 0
    counters_overview: List[Dict[str, Any]]
    recent_activity: Optional[List["AdminTransactionSummary"]] = None


class AdminTransactionSummary(BaseModel):
    order_number: str
    customer_identifier: str
    total_amount: float
    items_count: int
    payment_method: str
    payment_status: str
    verification_status: str
    assigned_counter_number: Optional[str] = None
    verification_duration_seconds: Optional[int] = None
    created_at: datetime
    items: Optional[List[AdminItemVerificationState]] = None

    model_config = ConfigDict(from_attributes=True)


class AdminProductUpdateRequest(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0.0)
    stock_qty: Optional[int] = Field(default=None, ge=0)
    initial_stock_qty: Optional[int] = Field(default=None, ge=0)
    category: Optional[str] = None
    icon: Optional[str] = None
    is_active: Optional[bool] = None


class AdminProductCreateRequest(BaseModel):
    barcode: str
    name: str
    price: float = Field(..., ge=0.0)
    stock_qty: int = Field(default=100, ge=0)
    category: Optional[str] = "General"
    icon: Optional[str] = "📦"
    description: Optional[str] = ""
    is_active: bool = True


class StaffAccountRead(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    counter_number: Optional[str] = None
    is_active: bool
    is_online: bool = False
    last_active: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class StaffCreateRequest(BaseModel):
    username: str
    display_name: str
    pin: str
    counter_number: str
    role: Optional[str] = "staff"


class StaffUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    counter_number: Optional[str] = None
    is_active: Optional[bool] = None


class StaffResetPinRequest(BaseModel):
    new_pin: str


class CounterStatusUpdateRequest(BaseModel):
    is_active: bool


class CounterMonitorDetail(BaseModel):
    id: int
    counter_number: str
    name: str
    is_active: bool
    is_express: bool
    avg_scan_speed_factor: float
    assigned_staff: Optional[StaffAccountRead] = None
    active_queue_length: int = 0
    waiting_orders_count: int = 0
    verified_today_count: int = 0
    counter_revenue: float = 0.0

