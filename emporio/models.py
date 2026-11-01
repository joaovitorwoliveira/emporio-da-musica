import json
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductStatus(StrEnum):
    ACTIVE = "active"
    DISCONTINUED = "discontinued"
    COMING_SOON = "coming_soon"


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
