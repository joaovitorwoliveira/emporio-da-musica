import csv
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

EXPECTED_CSV_COLUMNS = {
    "categories.csv": ["category_id", "name", "description"],
    "customers.csv": ["customer_id", "name", "phone", "email", "city"],
    "order_items.csv": ["order_id", "quantity", "product_id"],
    "orders.csv": [
        "order_id",
        "customer_id",
        "order_date",
        "status",
        "total_brl",
        "payment_method",
        "tracking_code",
        "estimated_delivery",
        "notes",
    ],
    "products.csv": [
        "product_id",
        "price_brl",
        "name",
        "category_id",
        "description",
        "stock_quantity",
        "status",
        "specs",
        "created_at",
    ],
    "promotions.csv": [
        "promotion_id",
        "product_id",
        "discount_percent",
        "description",
        "is_active",
    ],
}

POLICY_PDF = "politicas_da_loja.pdf"
PDF_MAGIC_BYTES = b"%PDF-"


@pytest.mark.parametrize("filename, expected_columns", EXPECTED_CSV_COLUMNS.items())
def test_csv_has_expected_header_and_rows(filename: str, expected_columns: list[str]):
    with (DATA_DIR / filename).open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    assert reader.fieldnames == expected_columns
    assert rows, f"{filename} has a header but no data rows"


def test_policy_pdf_is_present_and_is_a_pdf():
    assert (DATA_DIR / POLICY_PDF).read_bytes().startswith(PDF_MAGIC_BYTES)
