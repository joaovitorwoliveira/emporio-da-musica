import csv
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from emporio.models import Customer, OrderStatus, PaymentMethod, ProductStatus
from emporio.records import SeedError
from emporio.seed import ensure_store_seeded, seed_store
from emporio.settings import DATA_DIR

ACTIVE_PROMOTIONS_IN_DATA = 4


def count_csv_rows(filename: str) -> int:
    with (DATA_DIR / filename).open(newline="", encoding="utf-8") as file:
        return sum(1 for _ in csv.DictReader(file))


def fetch_all(db_path: Path, query: str) -> list[tuple]:
    with closing(sqlite3.connect(db_path)) as connection:
        return connection.execute(query).fetchall()


def test_seed_row_counts_match_csvs(tmp_path: Path):
    counts = seed_store(tmp_path / "store.db")

    assert counts.categories == count_csv_rows("categories.csv")
    assert counts.products == count_csv_rows("products.csv")
    assert counts.promotions == count_csv_rows("promotions.csv")
    assert counts.customers == count_csv_rows("customers.csv")
    assert counts.orders == count_csv_rows("orders.csv")
    assert counts.order_items == count_csv_rows("order_items.csv")


def test_seeded_tables_hold_the_counted_rows(store_db: Path):
    assert fetch_all(store_db, "SELECT COUNT(*) FROM categories")[0][0] == count_csv_rows("categories.csv")
    assert fetch_all(store_db, "SELECT COUNT(*) FROM products")[0][0] == count_csv_rows("products.csv")
    assert fetch_all(store_db, "SELECT COUNT(*) FROM promotions")[0][0] == count_csv_rows("promotions.csv")
    assert fetch_all(store_db, "SELECT COUNT(*) FROM customers")[0][0] == count_csv_rows("customers.csv")
    assert fetch_all(store_db, "SELECT COUNT(*) FROM orders")[0][0] == count_csv_rows("orders.csv")
    assert fetch_all(store_db, "SELECT COUNT(*) FROM order_items")[0][0] == count_csv_rows("order_items.csv")


def test_product_statuses_are_parsed_as_enum_values(store_db: Path):
    statuses = {row[0] for row in fetch_all(store_db, "SELECT DISTINCT status FROM products")}

    assert statuses == {status.value for status in ProductStatus}


def test_only_active_promotions_are_flagged_active(store_db: Path):
    active = fetch_all(store_db, "SELECT COUNT(*) FROM promotions WHERE is_active = 1")

    assert active[0][0] == ACTIVE_PROMOTIONS_IN_DATA


def test_specs_are_stored_as_parsed_json(store_db: Path):
    specs = fetch_all(store_db, "SELECT specs_json FROM products WHERE product_id = 95")[0][0]

    assert '"strings": "steel"' in specs


def test_rebuild_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "store.db"
    first = seed_store(db_path)
    second = seed_store(db_path)

    assert first == second
    assert fetch_all(db_path, "SELECT COUNT(*) FROM products")[0][0] == first.products
    assert not db_path.with_name("store.db.tmp").exists()


def test_rebuild_discards_rows_that_are_not_in_the_csvs(store_db: Path):
    with closing(sqlite3.connect(store_db)) as connection:
        with connection:
            connection.execute("DELETE FROM promotions")

    seed_store(store_db)

    assert fetch_all(store_db, "SELECT COUNT(*) FROM promotions")[0][0] == count_csv_rows("promotions.csv")


def test_ensure_store_seeded_creates_a_missing_database(tmp_path: Path):
    db_path = tmp_path / "runtime" / "store.db"

    ensure_store_seeded(db_path)

    assert db_path.exists()


def test_ensure_store_seeded_keeps_an_existing_database(store_db: Path):
    with closing(sqlite3.connect(store_db)) as connection:
        with connection:
            connection.execute("DELETE FROM promotions")

    ensure_store_seeded(store_db)

    assert fetch_all(store_db, "SELECT COUNT(*) FROM promotions")[0][0] == 0


def test_invalid_row_fails_with_file_and_line_and_keeps_the_previous_database(
    store_db: Path, tmp_path: Path
):
    broken_data = tmp_path / "data"
    shutil.copytree(DATA_DIR, broken_data)
    products_csv = broken_data / "products.csv"
    products_csv.write_text(
        products_csv.read_text(encoding="utf-8").replace(",active,", ",on_sale,", 1),
        encoding="utf-8",
    )

    with pytest.raises(SeedError, match=r"products\.csv:2"):
        seed_store(store_db, data_dir=broken_data)

    assert fetch_all(store_db, "SELECT COUNT(*) FROM products")[0][0] == count_csv_rows("products.csv")


def test_order_statuses_and_payment_methods_are_parsed_as_enum_values(store_db: Path):
    statuses = {row[0] for row in fetch_all(store_db, "SELECT DISTINCT status FROM orders")}
    methods = {row[0] for row in fetch_all(store_db, "SELECT DISTINCT payment_method FROM orders")}

    assert statuses == {status.value for status in OrderStatus}
    assert methods == {method.value for method in PaymentMethod}


def test_customer_phones_are_digits_and_emails_are_lowercase(store_db: Path):
    phone, email = fetch_all(
        store_db, "SELECT phone, email FROM customers WHERE customer_id = 1"
    )[0]

    assert phone == "67998123456"
    assert email == "lucas.mendes@jmail.com"


def test_customer_model_cleans_phone_and_email():
    customer = Customer.model_validate(
        {
            "customer_id": "1",
            "name": "Test",
            "phone": "+55 (67) 99812-3456",
            "email": "  Test.User@JMail.com ",
            "city": "Campo Grande",
        }
    )

    assert customer.phone == "5567998123456"
    assert customer.email == "test.user@jmail.com"


def test_historical_order_anomalies_load_without_changes(store_db: Path):
    order_3_total = fetch_all(store_db, "SELECT total_cents FROM orders WHERE order_id = 3")[0][0]
    order_20_total = fetch_all(store_db, "SELECT total_cents FROM orders WHERE order_id = 20")[0][0]
    orders_with_coming_soon = fetch_all(
        store_db,
        """
        SELECT DISTINCT i.order_id FROM order_items i
        JOIN products p ON p.product_id = i.product_id
        WHERE p.status = 'coming_soon' ORDER BY i.order_id
        """,
    )

    assert order_3_total == 345000
    assert order_20_total == 140000
    assert [row[0] for row in orders_with_coming_soon] == [3, 14]


def test_unshipped_orders_keep_missing_tracking_and_delivery_as_null(store_db: Path):
    row = fetch_all(
        store_db,
        "SELECT tracking_code, estimated_delivery, notes FROM orders WHERE order_id = 10",
    )[0]

    assert row == (None, None, None)


def test_invalid_order_row_fails_with_file_and_line(store_db: Path, tmp_path: Path):
    broken_data = tmp_path / "data"
    shutil.copytree(DATA_DIR, broken_data)
    orders_csv = broken_data / "orders.csv"
    orders_csv.write_text(
        orders_csv.read_text(encoding="utf-8").replace(",pix,", ",bitcoin,", 1),
        encoding="utf-8",
    )

    with pytest.raises(SeedError, match=r"orders\.csv:2"):
        seed_store(store_db, data_dir=broken_data)
