import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool

from emporio.catalog import (
    ALTERNATIVE_PRICE_TOLERANCE_PERCENT,
    MAX_ALTERNATIVES,
    UnknownCategoryError,
    list_active_promotions,
    lookup_products,
    search_products,
)
from emporio.models import Availability, ProductStatus, classify_availability
from emporio.store import connect

OUT_OF_STOCK_ID = 96
DISCONTINUED_ID = 113
COMING_SOON_WITH_STOCK_ID = 130
DISCONTINUED_WITH_STOCK_ID = 136
AVAILABLE_ID = 83
GD20_ID = 95
PROMOTED_AVAILABLE_ID = 94
ACTIVE_PROMOTION_IDS = [121, 90, 127, 94]
UNLISTED_PROMOTION_ID = 9001
BIG_LIMIT = 1000


def lookup_one(store_db: Path, product_id: int):
    [lookup] = lookup_products(store_db, product_id=product_id)
    return lookup


def all_product_rows(store_db: Path) -> list[tuple[int, str, int]]:
    with closing(connect(store_db)) as connection:
        return connection.execute(
            "SELECT product_id, status, stock_quantity FROM products ORDER BY product_id"
        ).fetchall()


def alternative_ids(store_db: Path, product_id: int) -> list[int]:
    alternatives = lookup_one(store_db, product_id).alternatives
    assert alternatives is not None
    return [a.price.product_id for a in alternatives.products]


@pytest.mark.parametrize(
    ("product_id", "expected"),
    [
        (AVAILABLE_ID, Availability.AVAILABLE),
        (OUT_OF_STOCK_ID, Availability.OUT_OF_STOCK),
        (DISCONTINUED_ID, Availability.DISCONTINUED),
        (COMING_SOON_WITH_STOCK_ID, Availability.COMING_SOON),
        (DISCONTINUED_WITH_STOCK_ID, Availability.DISCONTINUED),
    ],
)
def test_lookup_reports_the_availability_reason(
    store_db: Path, product_id: int, expected: Availability
):
    assert lookup_one(store_db, product_id).availability is expected


@pytest.mark.parametrize(
    ("status", "stock", "expected"),
    [
        (ProductStatus.ACTIVE, 5, Availability.AVAILABLE),
        (ProductStatus.ACTIVE, 0, Availability.OUT_OF_STOCK),
        (ProductStatus.DISCONTINUED, 0, Availability.DISCONTINUED),
        (ProductStatus.DISCONTINUED, 13, Availability.DISCONTINUED),
        (ProductStatus.COMING_SOON, 0, Availability.COMING_SOON),
        (ProductStatus.COMING_SOON, 2, Availability.COMING_SOON),
    ],
)
def test_status_wins_over_stock(
    status: ProductStatus, stock: int, expected: Availability
):
    assert classify_availability(status, stock) is expected


def test_search_returns_exactly_the_products_classified_as_available(store_db: Path):
    expected = {
        product_id
        for product_id, status, stock in all_product_rows(store_db)
        if classify_availability(ProductStatus(status), stock) is Availability.AVAILABLE
    }

    with closing(connect(store_db)) as connection:
        category_names = [r[0] for r in connection.execute("SELECT name FROM categories")]
    found: set[int] = set()
    for name in category_names:
        result = search_products(store_db, category=name, limit=BIG_LIMIT)
        found |= {m.price.product_id for m in result.products}

    assert found == expected
    assert COMING_SOON_WITH_STOCK_ID not in found
    assert DISCONTINUED_WITH_STOCK_ID not in found


def test_available_product_has_no_alternatives(store_db: Path):
    assert lookup_one(store_db, AVAILABLE_ID).alternatives is None


@pytest.mark.parametrize(
    ("product_id", "expected_ids"),
    [
        (OUT_OF_STOCK_ID, [107, 82, 86]),
        (DISCONTINUED_ID, [86, 87, 107]),
        (COMING_SOON_WITH_STOCK_ID, [126, 129, 125]),
    ],
)
def test_alternatives_are_the_closest_priced_in_range(
    store_db: Path, product_id: int, expected_ids: list[int]
):
    lookup = lookup_one(store_db, product_id)

    assert alternative_ids(store_db, product_id) == expected_ids
    assert lookup.alternatives is not None
    assert lookup.alternatives.in_price_range is True


@pytest.mark.parametrize(
    "product_id",
    [
        OUT_OF_STOCK_ID,
        DISCONTINUED_ID,
        COMING_SOON_WITH_STOCK_ID,
        DISCONTINUED_WITH_STOCK_ID,
    ],
)
def test_alternatives_are_available_distinct_and_capped(store_db: Path, product_id: int):
    lookup = lookup_one(store_db, product_id)
    rows = {pid: (status, stock) for pid, status, stock in all_product_rows(store_db)}
    assert lookup.alternatives is not None

    ids = [a.price.product_id for a in lookup.alternatives.products]

    assert product_id not in ids
    assert 0 < len(ids) <= MAX_ALTERNATIVES
    assert len(set(ids)) == len(ids)
    for alternative_id in ids:
        status, stock = rows[alternative_id]
        assert (
            classify_availability(ProductStatus(status), stock) is Availability.AVAILABLE
        )


def test_alternatives_exclude_other_unavailable_products(store_db: Path):
    discontinued_ids = alternative_ids(store_db, DISCONTINUED_ID)
    out_of_stock_ids = alternative_ids(store_db, OUT_OF_STOCK_ID)

    assert OUT_OF_STOCK_ID not in discontinued_ids
    assert DISCONTINUED_ID not in out_of_stock_ids


def test_alternatives_stay_in_the_same_category(store_db: Path):
    lookup = lookup_one(store_db, COMING_SOON_WITH_STOCK_ID)
    assert lookup.alternatives is not None

    assert {a.category for a in lookup.alternatives.products} == {"Ukuleles"}


def test_alternatives_respect_the_price_range_and_order(store_db: Path):
    lookup = lookup_one(store_db, OUT_OF_STOCK_ID)
    assert lookup.alternatives is not None
    reference = lookup.price.original_price
    tolerance = ALTERNATIVE_PRICE_TOLERANCE_PERCENT / 100

    finals = [a.price.final_price for a in lookup.alternatives.products]

    assert all(
        reference * (1 - tolerance) <= price <= reference * (1 + tolerance)
        for price in finals
    )
    distances = [abs(price - reference) for price in finals]
    assert distances == sorted(distances)


def test_alternatives_compare_the_final_price_not_the_list_price(store_db: Path):
    # Reference 440,00: promoted ukulele 121 (list 549,00, final 439,20) is the closest
    # by Final Price but would rank last by list price.
    with closing(sqlite3.connect(store_db)) as connection:
        connection.execute(
            "UPDATE products SET price_cents = ? WHERE product_id = ?",
            (44000, COMING_SOON_WITH_STOCK_ID),
        )
        connection.commit()

    assert alternative_ids(store_db, COMING_SOON_WITH_STOCK_ID) == [121, 124, 122]


def test_alternatives_fall_back_to_closest_priced_when_none_is_in_range(
    store_db: Path,
):
    lookup = lookup_one(store_db, DISCONTINUED_WITH_STOCK_ID)

    assert lookup.alternatives is not None
    assert lookup.alternatives.in_price_range is False
    assert [a.price.product_id for a in lookup.alternatives.products] == [138, 135, 137]
    assert all(
        a.price.final_price > lookup.price.original_price * 2
        for a in lookup.alternatives.products
    )


def test_alternatives_are_empty_when_the_category_has_nothing_available(
    store_db: Path,
):
    with closing(sqlite3.connect(store_db)) as connection:
        connection.execute("UPDATE products SET stock_quantity = 0 WHERE category_id = 2")
        connection.commit()

    lookup = lookup_one(store_db, DISCONTINUED_WITH_STOCK_ID)

    assert lookup.alternatives is not None
    assert lookup.alternatives.products == []
    assert lookup.alternatives.in_price_range is False


def test_ended_promotion_is_exposed_when_there_is_no_active_one(store_db: Path):
    lookup = lookup_one(store_db, GD20_ID)

    assert lookup.price.active_promotion is None
    assert lookup.price.final_price == lookup.price.original_price == Decimal("2199.00")
    assert lookup.ended_promotion is not None
    assert lookup.ended_promotion.discount_percent == 12
    assert lookup.ended_promotion.description == "Oferta Especial"


def test_product_with_an_active_promotion_has_no_ended_promotion(store_db: Path):
    with closing(sqlite3.connect(store_db)) as connection:
        connection.execute(
            "INSERT INTO promotions VALUES (?, ?, ?, ?, 0)",
            (UNLISTED_PROMOTION_ID, PROMOTED_AVAILABLE_ID, 30, "Antiga"),
        )
        connection.commit()

    lookup = lookup_one(store_db, PROMOTED_AVAILABLE_ID)

    assert lookup.price.active_promotion is not None
    assert lookup.ended_promotion is None


def test_ended_promotion_picks_the_highest_percent_then_lowest_id(store_db: Path):
    with closing(sqlite3.connect(store_db)) as connection:
        connection.execute("DELETE FROM promotions WHERE product_id = ?", (GD20_ID,))
        connection.executemany(
            "INSERT INTO promotions VALUES (?, ?, ?, ?, 0)",
            [
                (9001, GD20_ID, 10, "Dez"),
                (9003, GD20_ID, 25, "Vinte e cinco B"),
                (9002, GD20_ID, 25, "Vinte e cinco A"),
            ],
        )
        connection.commit()

    lookup = lookup_one(store_db, GD20_ID)

    assert lookup.ended_promotion is not None
    assert lookup.ended_promotion.description == "Vinte e cinco A"


def test_promotions_list_has_exactly_the_four_active_ones(store_db: Path):
    result = list_active_promotions(store_db)

    assert [p.price.product_id for p in result.products] == ACTIVE_PROMOTION_IDS
    assert result.total_matches == 4
    assert result.category is None


def test_promotions_are_ordered_by_discount_then_product_id(store_db: Path):
    result = list_active_promotions(store_db)

    percents = [p.price.active_promotion.discount_percent for p in result.products]
    assert percents == [20, 18, 10, 8]


def test_promotions_list_only_includes_available_products(store_db: Path):
    with closing(sqlite3.connect(store_db)) as connection:
        connection.executemany(
            "INSERT INTO promotions VALUES (?, ?, ?, ?, 1)",
            [
                (9001, OUT_OF_STOCK_ID, 15, "Esgotado"),
                (9002, DISCONTINUED_ID, 15, "Fora de linha"),
                (9003, COMING_SOON_WITH_STOCK_ID, 15, "Em breve"),
                (9004, DISCONTINUED_WITH_STOCK_ID, 15, "Descontinuado com estoque"),
            ],
        )
        connection.commit()

    result = list_active_promotions(store_db)

    assert [p.price.product_id for p in result.products] == ACTIVE_PROMOTION_IDS


def test_promotions_list_can_be_filtered_by_category(store_db: Path):
    result = list_active_promotions(store_db, category="ukulele")

    assert result.category == "Ukuleles"
    assert [p.price.product_id for p in result.products] == [121, 127]
    assert {p.category for p in result.products} == {"Ukuleles"}


def test_promotions_list_is_empty_for_a_category_without_promotions(store_db: Path):
    assert list_active_promotions(store_db, category="sax").products == []
    assert list_active_promotions(store_db, category="guitarra").total_matches == 0


def test_promotions_list_rejects_an_unknown_category(store_db: Path):
    with pytest.raises(UnknownCategoryError):
        list_active_promotions(store_db, category="cavaquinho")


def test_blank_promotion_category_means_no_filter(store_db: Path):
    assert list_active_promotions(store_db, category="  ").total_matches == 4


@pytest.mark.parametrize(
    ("product_id", "reason", "label"),
    [
        (OUT_OF_STOCK_ID, "out_of_stock", "esgotado no momento"),
        (DISCONTINUED_ID, "discontinued", "fora de linha (descontinuado)"),
        (COMING_SOON_WITH_STOCK_ID, "coming_soon", "em breve (sem data de lançamento)"),
        (DISCONTINUED_WITH_STOCK_ID, "discontinued", "fora de linha (descontinuado)"),
    ],
)
def test_tool_reports_the_reason_and_alternatives(
    tools: dict[str, BaseTool], product_id: int, reason: str, label: str
):
    [product] = tools["find_product"].invoke({"product_id": product_id})["products"]

    assert product["availability"] == reason
    assert product["availability_label"] == label
    assert 0 < len(product["alternatives"]) <= MAX_ALTERNATIVES
    assert product["alternatives"][0].keys() == {
        "product_id",
        "name",
        "category",
        "original_price",
        "active_promotion",
        "final_price",
    }


def test_tool_payload_for_the_out_of_stock_guitar(tools: dict[str, BaseTool]):
    [product] = tools["find_product"].invoke({"product_id": OUT_OF_STOCK_ID})["products"]

    assert product == {
        "product_id": 96,
        "name": "Giannini GF-3D Dreadnought Sunburst",
        "original_price": "R$ 799,90",
        "active_promotion": None,
        "final_price": "R$ 799,90",
        "availability": "out_of_stock",
        "availability_label": "esgotado no momento",
        "ended_promotion": product["ended_promotion"],
        "alternatives": product["alternatives"],
        "alternatives_in_price_range": True,
    }
    assert [a["product_id"] for a in product["alternatives"]] == [107, 82, 86]


def test_tool_payload_for_an_available_product_has_no_alternatives(
    tools: dict[str, BaseTool],
):
    [product] = tools["find_product"].invoke({"product_id": AVAILABLE_ID})["products"]

    assert product["availability"] == "available"
    assert "alternatives" not in product
    assert "alternatives_in_price_range" not in product


def test_tool_flags_alternatives_outside_the_price_range(tools: dict[str, BaseTool]):
    [product] = tools["find_product"].invoke({"product_id": DISCONTINUED_WITH_STOCK_ID})[
        "products"
    ]

    assert product["alternatives_in_price_range"] is False
    assert [a["product_id"] for a in product["alternatives"]] == [138, 135, 137]


def test_tool_never_exposes_stock_or_a_release_date(tools: dict[str, BaseTool]):
    products = [
        tools["find_product"].invoke({"product_id": pid})["products"][0]
        for pid in (COMING_SOON_WITH_STOCK_ID, DISCONTINUED_WITH_STOCK_ID, AVAILABLE_ID)
    ]

    def keys(payload: object) -> list[str]:
        if isinstance(payload, dict):
            return [*payload, *(k for v in payload.values() for k in keys(v))]
        if isinstance(payload, list):
            return [k for item in payload for k in keys(item)]
        return []

    assert all(
        "stock" not in key and "date" not in key
        for product in products
        for key in keys(product)
    )


def test_tool_shows_the_ended_promotion_with_the_current_price(
    tools: dict[str, BaseTool],
):
    [product] = tools["find_product"].invoke({"name": "takamine gd20"})["products"]

    assert product["active_promotion"] is None
    assert product["final_price"] == "R$ 2.199,00"
    assert product["ended_promotion"] == {
        "description": "Oferta Especial",
        "discount_percent": 12,
    }


def test_tool_has_no_ended_promotion_for_a_promoted_product(tools: dict[str, BaseTool]):
    [product] = tools["find_product"].invoke({"product_id": PROMOTED_AVAILABLE_ID})[
        "products"
    ]

    assert product["active_promotion"]["discount_percent"] == 8
    assert product["ended_promotion"] is None


def test_list_promotions_tool_payload(tools: dict[str, BaseTool]):
    payload = tools["list_promotions"].invoke({})

    assert payload["category"] is None
    assert payload["total"] == 4
    assert [p["product_id"] for p in payload["promotions"]] == ACTIVE_PROMOTION_IDS
    [ukulele] = [p for p in payload["promotions"] if p["product_id"] == 121]
    assert ukulele == {
        "product_id": 121,
        "name": "Ohana CK-20 Concert Natural",
        "category": "Ukuleles",
        "original_price": "R$ 549,00",
        "active_promotion": {"description": "Desconto Exclusivo", "discount_percent": 20},
        "final_price": "R$ 439,20",
    }


def test_list_promotions_tool_filters_by_category(tools: dict[str, BaseTool]):
    payload = tools["list_promotions"].invoke({"category": "violões"})

    assert payload["category"] == "Violões"
    assert [p["product_id"] for p in payload["promotions"]] == [90, 94]


def test_list_promotions_tool_reports_unknown_category(tools: dict[str, BaseTool]):
    payload = tools["list_promotions"].invoke({"category": "cavaquinho"})

    assert payload["category_recognized"] is False
    assert "Violões" in payload["valid_categories"]
    assert "promotions" not in payload
