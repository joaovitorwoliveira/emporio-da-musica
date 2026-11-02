import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from emporio.data_quality import detect_anomalies, format_report
from emporio.models import Category, Customer, Order, OrderItem, Product, Promotion
from emporio.records import StoreRecords, load_store_records
from emporio.settings import DATA_DIR, STORE_DB_PATH
from emporio.store import SCHEMA, normalize_text, to_cents

TEMP_DB_SUFFIX = ".tmp"


@dataclass(frozen=True)
class SeedCounts:
    categories: int
    products: int
    promotions: int
    customers: int
    orders: int
    order_items: int


def seed_store(db_path: Path = STORE_DB_PATH, data_dir: Path = DATA_DIR) -> SeedCounts:
    records = load_store_records(data_dir)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = db_path.with_name(db_path.name + TEMP_DB_SUFFIX)
    temp_path.unlink(missing_ok=True)
    try:
        _write_database(temp_path, records)
        os.replace(temp_path, db_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return SeedCounts(
        categories=len(records.categories),
        products=len(records.products),
        promotions=len(records.promotions),
        customers=len(records.customers),
        orders=len(records.orders),
        order_items=len(records.order_items),
    )


def ensure_store_seeded(db_path: Path = STORE_DB_PATH) -> None:
    if db_path.exists():
        return
    seed_store(db_path)


def _write_database(path: Path, records: StoreRecords) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        with connection:
            _insert_categories(connection, records.categories)
            _insert_products(connection, records.products)
            _insert_promotions(connection, records.promotions)
            _insert_customers(connection, records.customers)
            _insert_orders(connection, records.orders)
            _insert_order_items(connection, records.order_items)


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


def _insert_customers(
    connection: sqlite3.Connection, customers: list[Customer]
) -> None:
    connection.executemany(
        "INSERT INTO customers (customer_id, name, phone, email, city) VALUES (?, ?, ?, ?, ?)",
        [(c.customer_id, c.name, c.phone, c.email, c.city) for c in customers],
    )


def _insert_orders(connection: sqlite3.Connection, orders: list[Order]) -> None:
    connection.executemany(
        """
        INSERT INTO orders (
            order_id, customer_id, order_date, status, total_cents,
            payment_method, tracking_code, estimated_delivery, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                o.order_id,
                o.customer_id,
                o.order_date.isoformat(),
                o.status.value,
                to_cents(o.total_brl),
                o.payment_method.value,
                o.tracking_code,
                None if o.estimated_delivery is None else o.estimated_delivery.isoformat(),
                o.notes,
            )
            for o in orders
        ],
    )


def _insert_order_items(
    connection: sqlite3.Connection, order_items: list[OrderItem]
) -> None:
    connection.executemany(
        "INSERT INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)",
        [(i.order_id, i.product_id, i.quantity) for i in order_items],
    )


def main() -> None:
    counts = seed_store()
    print(f"Seeded {STORE_DB_PATH}")
    print(f"categories: {counts.categories}")
    print(f"products: {counts.products}")
    print(f"promotions: {counts.promotions}")
    print(f"customers: {counts.customers}")
    print(f"orders: {counts.orders}")
    print(f"order_items: {counts.order_items}")
    print()
    print(format_report(detect_anomalies(load_store_records(DATA_DIR))))


if __name__ == "__main__":
    main()
