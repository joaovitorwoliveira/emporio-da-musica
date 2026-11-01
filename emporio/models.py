import json
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from emporio.store import digits_only, normalize_email

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+$"


class ProductStatus(StrEnum):
    ACTIVE = "active"
    DISCONTINUED = "discontinued"
    COMING_SOON = "coming_soon"


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PaymentMethod(StrEnum):
    PIX = "pix"
    BOLETO = "boleto"
    DEBIT = "debit"
    CREDIT_3X = "credit_3x"
    CREDIT_6X = "credit_6x"
    CREDIT_12X = "credit_12x"


class Category(BaseModel):
    model_config = ConfigDict(frozen=True)

    category_id: int
    name: str
    description: str


class Product(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    price_brl: Decimal = Field(gt=0, decimal_places=2)
    name: str = Field(min_length=1)
    category_id: int
    description: str
    stock_quantity: int = Field(ge=0)
    status: ProductStatus
    specs: dict[str, str]
    created_at: date

    @field_validator("specs", mode="before")
    @classmethod
    def parse_specs_json(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return json.loads(value)


class Promotion(BaseModel):
    model_config = ConfigDict(frozen=True)

    promotion_id: int
    product_id: int
    discount_percent: int = Field(ge=1, le=100)
    description: str
    is_active: bool


class Customer(BaseModel):
    model_config = ConfigDict(frozen=True)

    customer_id: int
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    email: str = Field(pattern=EMAIL_PATTERN)
    city: str

    @field_validator("phone", mode="before")
    @classmethod
    def reduce_phone_to_digits(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return digits_only(value)

    @field_validator("email", mode="before")
    @classmethod
    def lowercase_email(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return normalize_email(value)


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: int
    customer_id: int
    order_date: date
    status: OrderStatus
    total_brl: Decimal = Field(gt=0, decimal_places=2)
    payment_method: PaymentMethod
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None

    @field_validator("tracking_code", "estimated_delivery", "notes", mode="before")
    @classmethod
    def empty_text_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class OrderItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: int
    product_id: int
    quantity: int = Field(ge=1)
