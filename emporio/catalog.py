import sqlite3
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from emporio.models import Availability, ProductStatus, classify_availability
from emporio.store import (
    EndedPromotion,
    ProductPrice,
    build_product_price,
    connect,
    find_products,
    normalize_text,
    select_ended_promotion,
)

MAX_SEARCH_RESULTS = 15
MAX_ALTERNATIVES = 3
# An alternative is "in a similar price range" when its Final Price is within this
# percentage, either way, of the unavailable product's list price.
ALTERNATIVE_PRICE_TOLERANCE_PERCENT = Decimal(30)
PERCENT_DENOMINATOR = Decimal(100)

# Customer wordings per store category (keyed by the category name in the database).
# Normalized text only: lowercase, no accents. The category's own name always matches too.
CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "Guitarras": ("guitarra", "guitarras"),
    "Baixos": ("baixo", "baixos"),
    "Baterias e Percussão": ("bateria", "baterias", "percussao"),
    "Teclados e Pianos": (
        "teclado",
        "teclados",
        "piano",
        "pianos",
        "sintetizador",
        "sintetizadores",
    ),
    "Violões": ("violao", "violoes"),
    "Instrumentos de Sopro (Madeiras)": (
        "flauta",
        "flautas",
        "clarinete",
        "clarinetes",
        "sax",
        "saxofone",
        "saxofones",
        "oboe",
        "oboes",
    ),
    "Instrumentos de Sopro (Metais)": (
        "trompete",
        "trompetes",
        "trombone",
        "trombones",
        "tuba",
        "tubas",
        "trompa",
        "trompas",
    ),
    "Cordas Orquestrais": (
        "violino",
        "violinos",
        "viola",
        "violas",
        "violoncelo",
        "violoncelos",
        "cello",
    ),
    "Ukuleles": ("ukulele", "ukuleles"),
}

SELECT_CATEGORIES = "SELECT category_id, name FROM categories ORDER BY category_id"

# Availability is decided in Python by classify_availability, the single definition
# shared with the product lookup, so the query returns status and stock as they are.
SELECT_PRODUCTS = """
SELECT p.product_id, p.name, p.price_cents, p.description, c.name, p.status,
       p.stock_quantity
FROM products AS p
JOIN categories AS c ON c.category_id = p.category_id
WHERE (? IS NULL OR p.category_id = ?)
ORDER BY p.product_id
"""

SELECT_PRODUCT_FACTS = """
SELECT status, stock_quantity, category_id FROM products WHERE product_id = ?
"""


class UnknownCategoryError(Exception):
    def __init__(self, wording: str, valid_categories: list[str]) -> None:
        super().__init__(f"Unknown category: {wording!r}")
        self.wording = wording
        self.valid_categories = valid_categories


@dataclass(frozen=True)
class CatalogProduct:
    category: str
    price: ProductPrice


@dataclass(frozen=True)
class CatalogSearchResult:
    category: str | None
    products: list[CatalogProduct]
    total_matches: int


@dataclass(frozen=True)
class Alternatives:
    products: list[CatalogProduct]
    in_price_range: bool


@dataclass(frozen=True)
class ProductLookup:
    price: ProductPrice
    availability: Availability
    ended_promotion: EndedPromotion | None
    # None for an Available Product, which needs no alternative.
    alternatives: Alternatives | None


def search_products(
    db_path: Path,
    category: str | None = None,
    max_price: Decimal | None = None,
    text: str | None = None,
    limit: int = MAX_SEARCH_RESULTS,
) -> CatalogSearchResult:
    category_wording = _blank_to_none(category)
    text_tokens = normalize_text(text or "").split()
    if max_price is not None and (not max_price.is_finite() or max_price <= 0):
        raise ValueError("max_price must be a positive number.")
    if category_wording is None and max_price is None and not text_tokens:
        raise ValueError("Provide at least one of category, max_price or text to search.")

    with closing(connect(db_path)) as connection:
        category_id, category_name = _resolve_category(connection, category_wording)
        # Price and text are filtered here, not in SQL: the Final Price depends on the
        # best Active Promotion (already computed by build_product_price) and the
        # description has no normalized column. The catalog is small enough for this.
        matches = [
            product
            for product, description in _available_products(connection, category_id)
            if _matches_text(product.price.name, description, text_tokens)
        ]

    within_budget = [
        match
        for match in matches
        if max_price is None or match.price.final_price <= max_price
    ]
    within_budget.sort(key=lambda m: (m.price.final_price, m.price.product_id))
    return CatalogSearchResult(
        category=category_name,
        products=within_budget[:limit],
        total_matches=len(within_budget),
    )


def list_active_promotions(
    db_path: Path, category: str | None = None
) -> CatalogSearchResult:
    category_wording = _blank_to_none(category)
    with closing(connect(db_path)) as connection:
        category_id, category_name = _resolve_category(connection, category_wording)
        promoted = [
            product
            for product, _ in _available_products(connection, category_id)
            if product.price.active_promotion is not None
        ]
    promoted.sort(key=lambda p: (-_discount_percent(p), p.price.product_id))
    return CatalogSearchResult(
        category=category_name, products=promoted, total_matches=len(promoted)
    )


def lookup_products(
    db_path: Path, product_id: int | None = None, name: str | None = None
) -> list[ProductLookup]:
    prices = find_products(db_path, product_id=product_id, name=name)
    with closing(connect(db_path)) as connection:
        return [_build_lookup(connection, price) for price in prices]


def _build_lookup(connection: sqlite3.Connection, price: ProductPrice) -> ProductLookup:
    status, stock_quantity, category_id = connection.execute(
        SELECT_PRODUCT_FACTS, (price.product_id,)
    ).fetchone()
    availability = classify_availability(ProductStatus(status), stock_quantity)
    ended_promotion = (
        select_ended_promotion(connection, price.product_id)
        if price.active_promotion is None
        else None
    )
    alternatives = (
        None
        if availability is Availability.AVAILABLE
        else _find_alternatives(connection, category_id, price.original_price)
    )
    return ProductLookup(
        price=price,
        availability=availability,
        ended_promotion=ended_promotion,
        alternatives=alternatives,
    )


def _find_alternatives(
    connection: sqlite3.Connection, category_id: int, reference_price: Decimal
) -> Alternatives:
    candidates = [p for p, _ in _available_products(connection, category_id)]
    closest_first = sorted(
        candidates,
        key=lambda p: (abs(p.price.final_price - reference_price), p.price.product_id),
    )
    tolerance = ALTERNATIVE_PRICE_TOLERANCE_PERCENT / PERCENT_DENOMINATOR
    lowest = reference_price * (1 - tolerance)
    highest = reference_price * (1 + tolerance)
    in_range = [p for p in closest_first if lowest <= p.price.final_price <= highest]
    if in_range:
        return Alternatives(products=in_range[:MAX_ALTERNATIVES], in_price_range=True)
    # Nothing is priced alike: still show the closest options of the category, flagged
    # so the assistant says plainly that they are in a different price range.
    return Alternatives(products=closest_first[:MAX_ALTERNATIVES], in_price_range=False)


def _available_products(
    connection: sqlite3.Connection, category_id: int | None
) -> list[tuple[CatalogProduct, str]]:
    """Available Products with their description, in product_id order."""
    rows = connection.execute(SELECT_PRODUCTS, (category_id, category_id)).fetchall()
    return [
        (
            CatalogProduct(
                category=category,
                price=build_product_price(connection, (product_id, name, price_cents)),
            ),
            description,
        )
        for product_id, name, price_cents, description, category, status, stock in rows
        if classify_availability(ProductStatus(status), stock) is Availability.AVAILABLE
    ]


def _discount_percent(product: CatalogProduct) -> int:
    promotion = product.price.active_promotion
    return 0 if promotion is None else promotion.discount_percent


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value


def _matches_text(name: str, description: str, tokens: list[str]) -> bool:
    searchable = normalize_text(f"{name} {description}")
    return all(token in searchable for token in tokens)


def _resolve_category(
    connection: sqlite3.Connection, wording: str | None
) -> tuple[int | None, str | None]:
    if wording is None:
        return None, None
    categories = connection.execute(SELECT_CATEGORIES).fetchall()
    normalized_wording = normalize_text(wording)
    for category_id, name in categories:
        accepted = (normalize_text(name), *CATEGORY_ALIASES.get(name, ()))
        if normalized_wording in accepted:
            return category_id, name
    raise UnknownCategoryError(wording, [name for _, name in categories])
