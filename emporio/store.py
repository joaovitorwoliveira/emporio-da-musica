import re
import sqlite3
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

CENTS_PER_REAL = 100
PERCENT_DENOMINATOR = Decimal(100)
MONEY_QUANTUM = Decimal("0.01")
MAX_LOOKUP_RESULTS = 5
LIKE_ESCAPE_CHAR = "\\"
NON_DIGITS = re.compile(r"\D")
BRAZIL_COUNTRY_CODE = "55"
BRAZILIAN_NATIONAL_NUMBER_LENGTHS = (10, 11)

SCHEMA = """
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories (category_id),
    description TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    stock_quantity INTEGER NOT NULL,
    status TEXT NOT NULL,
    specs_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE promotions (
    promotion_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products (product_id),
    discount_percent INTEGER NOT NULL,
    description TEXT NOT NULL,
    is_active INTEGER NOT NULL
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    city TEXT NOT NULL
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers (customer_id),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL,
    total_cents INTEGER NOT NULL,
    payment_method TEXT NOT NULL,
    tracking_code TEXT,
    estimated_delivery TEXT,
    notes TEXT
);

CREATE TABLE order_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders (order_id),
    product_id INTEGER NOT NULL REFERENCES products (product_id),
    quantity INTEGER NOT NULL
);
"""

SELECT_PRODUCT_BY_ID = """
SELECT product_id, name, price_cents FROM products WHERE product_id = ?
"""

SELECT_PRODUCTS_BY_NAME = f"""
SELECT product_id, name, price_cents FROM products
WHERE name_normalized LIKE ? ESCAPE '{LIKE_ESCAPE_CHAR}'
ORDER BY name_normalized, product_id
LIMIT ?
"""

SELECT_ACTIVE_PROMOTION = """
SELECT description, discount_percent FROM promotions
WHERE product_id = ? AND is_active = 1
ORDER BY discount_percent DESC, promotion_id
LIMIT 1
"""


@dataclass(frozen=True)
class ActivePromotion:
    description: str
    discount_percent: int


@dataclass(frozen=True)
class ProductPrice:
    product_id: int
    name: str
    original_price: Decimal
    active_promotion: ActivePromotion | None
    final_price: Decimal


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(without_accents.casefold().split())


def digits_only(text: str) -> str:
    return NON_DIGITS.sub("", text)


def normalize_email(text: str) -> str:
    return text.strip().lower()


def strip_country_code(digits: str) -> str:
    has_country_code = (
        digits.startswith(BRAZIL_COUNTRY_CODE)
        and len(digits) - len(BRAZIL_COUNTRY_CODE) in BRAZILIAN_NATIONAL_NUMBER_LENGTHS
    )
    return digits[len(BRAZIL_COUNTRY_CODE) :] if has_country_code else digits


def to_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def to_cents(price: Decimal) -> int:
    return int(to_money(price) * CENTS_PER_REAL)


def from_cents(cents: int) -> Decimal:
    return to_money(Decimal(cents) / CENTS_PER_REAL)


def calculate_final_price(
    original_price: Decimal, active_promotion: ActivePromotion | None
) -> Decimal:
    if active_promotion is None:
        return to_money(original_price)
    discount_factor = (
        PERCENT_DENOMINATOR - active_promotion.discount_percent
    ) / PERCENT_DENOMINATOR
    return to_money(original_price * discount_factor)


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Store database not found at {db_path}. "
            "Run `uv run python -m emporio.seed` to create it."
        )
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def find_products(
    db_path: Path, product_id: int | None = None, name: str | None = None
) -> list[ProductPrice]:
    has_name = name is not None and bool(name.strip())
    if product_id is None and not has_name:
        raise ValueError("Provide a product_id or a non-empty name to look up a product.")
    with closing(connect(db_path)) as connection:
        rows = _select_product_rows(connection, product_id, name)
        return [build_product_price(connection, row) for row in rows]


def _select_product_rows(
    connection: sqlite3.Connection, product_id: int | None, name: str | None
) -> list[tuple[int, str, int]]:
    if product_id is not None:
        return connection.execute(SELECT_PRODUCT_BY_ID, (product_id,)).fetchall()
    pattern = f"%{_escape_like(normalize_text(name or ''))}%"
    return connection.execute(
        SELECT_PRODUCTS_BY_NAME, (pattern, MAX_LOOKUP_RESULTS)
    ).fetchall()


def _escape_like(text: str) -> str:
    escaped = text.replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR * 2)
    return escaped.replace("%", f"{LIKE_ESCAPE_CHAR}%").replace("_", f"{LIKE_ESCAPE_CHAR}_")


def build_product_price(
    connection: sqlite3.Connection, row: tuple[int, str, int]
) -> ProductPrice:
    product_id, name, price_cents = row
    original_price = from_cents(price_cents)
    active_promotion = _select_active_promotion(connection, product_id)
    return ProductPrice(
        product_id=product_id,
        name=name,
        original_price=original_price,
        active_promotion=active_promotion,
        final_price=calculate_final_price(original_price, active_promotion),
    )


def _select_active_promotion(
    connection: sqlite3.Connection, product_id: int
) -> ActivePromotion | None:
    row = connection.execute(SELECT_ACTIVE_PROMOTION, (product_id,)).fetchone()
    if row is None:
        return None
    return ActivePromotion(description=row[0], discount_percent=row[1])
