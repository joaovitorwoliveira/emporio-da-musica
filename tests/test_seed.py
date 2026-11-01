import csv
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from emporio.models import ProductStatus
from emporio.seed import SeedError, ensure_store_seeded, seed_store
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


def test_seeded_tables_hold_the_counted_rows(store_db: Path):
    assert fetch_all(store_db, "SELECT COUNT(*) FROM categories")[0][0] == count_csv_rows("categories.csv")
    assert fetch_all(store_db, "SELECT COUNT(*) FROM products")[0][0] == count_csv_rows("products.csv")
    assert fetch_all(store_db, "SELECT COUNT(*) FROM promotions")[0][0] == count_csv_rows("promotions.csv")


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
