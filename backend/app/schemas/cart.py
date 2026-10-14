from typing import List, Optional
from pydantic import BaseModel, ConfigDict, computed_field


class CartItemCreate(BaseModel):
    barcode: str
    quantity: int = 1


class CartItemUpdate(BaseModel):
    quantity: int


class CartItemRead(BaseModel):
    id: int
    product_id: int
    product_barcode: str
    product_name: str
    unit_price: float
    quantity: int
    category: str = "General"
    icon: str = "📦"
    stock_qty: Optional[int] = None

    @computed_field
    @property
    def total_price(self) -> float:
        return round(self.unit_price * self.quantity, 2)

    model_config = ConfigDict(from_attributes=True)


class CartRead(BaseModel):
    id: str
    customer_identifier: Optional[str] = None
    status: str = "ACTIVE"
    items: List[CartItemRead] = []

    @computed_field
    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    @computed_field
    @property
    def subtotal(self) -> float:
        return round(sum(item.unit_price * item.quantity for item in self.items), 2)

    @computed_field
    @property
    def tax_amount(self) -> float:
        return round(self.subtotal * 0.05, 2)

    @computed_field
    @property
    def discount_amount(self) -> float:
        return 15.0 if self.item_count > 0 and self.subtotal > 50 else 0.0

    @computed_field
    @property
    def total_amount(self) -> float:
        return max(0.0, round(self.subtotal + self.tax_amount - self.discount_amount, 2))

    model_config = ConfigDict(from_attributes=True)
