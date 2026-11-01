import csv
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from emporio.models import Category, Product, Promotion
from emporio.settings import DATA_DIR, STORE_DB_PATH
from emporio.store import SCHEMA, normalize_text, to_cents

CATEGORIES_CSV = "categories.csv"
PRODUCTS_CSV = "products.csv"
PROMOTIONS_CSV = "promotions.csv"
CSV_FIRST_DATA_LINE = 2
TEMP_DB_SUFFIX = ".tmp"

RowModel = TypeVar("RowModel", bound=BaseModel)


class SeedError(Exception):
    pass


@dataclass(frozen=True)
class SeedCounts:
    categories: int
    products: int
    promotions: int


def seed_store(db_path: Path = STORE_DB_PATH, data_dir: Path = DATA_DIR) -> SeedCounts:
    categories = _read_csv(data_dir / CATEGORIES_CSV, Category)
    products = _read_csv(data_dir / PRODUCTS_CSV, Product)
    promotions = _read_csv(data_dir / PROMOTIONS_CSV, Promotion)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = db_path.with_name(db_path.name + TEMP_DB_SUFFIX)
    temp_path.unlink(missing_ok=True)
    try:
        _write_database(temp_path, categories, products, promotions)
        os.replace(temp_path, db_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return SeedCounts(len(categories), len(products), len(promotions))


def ensure_store_seeded(db_path: Path = STORE_DB_PATH) -> None:
    if db_path.exists():
        return
    seed_store(db_path)


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


def _write_database(
    path: Path,
    categories: list[Category],
    products: list[Product],
    promotions: list[Promotion],
) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        with connection:
            _insert_categories(connection, categories)
            _insert_products(connection, products)
            _insert_promotions(connection, promotions)


def _insert_categories(
    connection: sqlite3.Connection, categories: list[Category]
) -> None:
    connection.executemany(
        "INSERT INTO categories (category_id, name, description) VALUES (?, ?, ?)",
        [(c.category_id, c.name, c.description) for c in categories],
    )


def _insert_products(connection: sqlite3.Connection, products: list[Product]) -> None:
    connection.executemany(
        """
        INSERT INTO products (
            product_id, name, name_normalized, category_id, description,
            price_cents, stock_quantity, status, specs_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                p.product_id,
                p.name,
                normalize_text(p.name),
                p.category_id,
                p.description,
                to_cents(p.price_brl),
                p.stock_quantity,
                p.status.value,
                json.dumps(p.specs, ensure_ascii=False),
                p.created_at.isoformat(),
            )
            for p in products
        ],
    )


def _insert_promotions(
    connection: sqlite3.Connection, promotions: list[Promotion]
) -> None:
    connection.executemany(
        """
        INSERT INTO promotions (
            promotion_id, product_id, discount_percent, description, is_active
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                p.promotion_id,
                p.product_id,
                p.discount_percent,
                p.description,
                int(p.is_active),
            )
            for p in promotions
        ],
    )


def main() -> None:
    counts = seed_store()
    print(f"Seeded {STORE_DB_PATH}")
    print(f"categories: {counts.categories}")
    print(f"products: {counts.products}")
    print(f"promotions: {counts.promotions}")


if __name__ == "__main__":
    main()
