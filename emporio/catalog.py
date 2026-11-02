import sqlite3
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from emporio.models import ProductStatus
from emporio.store import ProductPrice, build_product_price, connect, normalize_text

MAX_SEARCH_RESULTS = 15

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

SELECT_AVAILABLE_PRODUCTS = """
SELECT p.product_id, p.name, p.price_cents, p.description, c.name
FROM products AS p
JOIN categories AS c ON c.category_id = p.category_id
WHERE p.status = ? AND p.stock_quantity > 0
  AND (? IS NULL OR p.category_id = ?)
ORDER BY p.product_id
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
            CatalogProduct(category=row[4], price=build_product_price(connection, row[:3]))
            for row in connection.execute(
                SELECT_AVAILABLE_PRODUCTS,
                (ProductStatus.ACTIVE.value, category_id, category_id),
            )
            if _matches_text(row[1], row[3], text_tokens)
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
