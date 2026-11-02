import csv
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from emporio.models import Category, Customer, Order, OrderItem, Product, Promotion

CATEGORIES_CSV = "categories.csv"
PRODUCTS_CSV = "products.csv"
PROMOTIONS_CSV = "promotions.csv"
CUSTOMERS_CSV = "customers.csv"
ORDERS_CSV = "orders.csv"
ORDER_ITEMS_CSV = "order_items.csv"
CSV_FIRST_DATA_LINE = 2

RowModel = TypeVar("RowModel", bound=BaseModel)


class SeedError(Exception):
    pass


@dataclass(frozen=True)
class StoreRecords:
    categories: list[Category]
    products: list[Product]
    promotions: list[Promotion]
    customers: list[Customer]
    orders: list[Order]
    order_items: list[OrderItem]


def load_store_records(data_dir: Path) -> StoreRecords:
    return StoreRecords(
        categories=_read_csv(data_dir / CATEGORIES_CSV, Category),
        products=_read_csv(data_dir / PRODUCTS_CSV, Product),
        promotions=_read_csv(data_dir / PROMOTIONS_CSV, Promotion),
        customers=_read_csv(data_dir / CUSTOMERS_CSV, Customer),
        orders=_read_csv(data_dir / ORDERS_CSV, Order),
        order_items=_read_csv(data_dir / ORDER_ITEMS_CSV, OrderItem),
    )


def _read_csv(path: Path, model: type[RowModel]) -> list[RowModel]:
    if not path.exists():
        raise SeedError(f"Source data file not found: {path}")
    with path.open(newline="", encoding="utf-8") as file:
        rows = enumerate(csv.DictReader(file), start=CSV_FIRST_DATA_LINE)
        return [_validate_row(path, line, row, model) for line, row in rows]


def _validate_row(
    path: Path, line: int, row: dict[str, str], model: type[RowModel]
) -> RowModel:
    try:
        return model.model_validate(row)
    except ValidationError as error:
        raise SeedError(f"Invalid row at {path.name}:{line}: {error}") from error
