import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool

from emporio.catalog import (
    CATEGORY_ALIASES,
    MAX_SEARCH_RESULTS,
    UnknownCategoryError,
    search_products,
)

GUITARS_BUDGET = Decimal("1000")
AVAILABLE_GUITAR_IDS_UP_TO_BUDGET = [83, 85, 89, 88, 81, 84, 87, 86, 107, 82, 91, 112]
OUT_OF_STOCK_GUITAR_ID = 96
DISCONTINUED_GUITAR_ID = 113
GUITARS_CATEGORY_NAME = "Violões"
EMPTY_CATEGORY_WORDINGS = ("sax", "flauta", "trompete", "violino")
UKULELES_CATEGORY_NAME = "Ukuleles"
PROMOTED_UKULELE_ID = 121
PROMOTED_UKULELE_ORIGINAL_PRICE = Decimal("549.00")
PROMOTED_UKULELE_FINAL_PRICE = Decimal("439.20")
UKULELE_BUDGET_BETWEEN_FINAL_AND_ORIGINAL = Decimal("500")


def test_guitars_up_to_1000_returns_the_twelve_available_ones(store_db: Path):
    result = search_products(store_db, category="violões", max_price=GUITARS_BUDGET)

    ids = [match.price.product_id for match in result.products]
    assert sorted(ids) == sorted(AVAILABLE_GUITAR_IDS_UP_TO_BUDGET)
    assert result.total_matches == len(AVAILABLE_GUITAR_IDS_UP_TO_BUDGET)
    assert OUT_OF_STOCK_GUITAR_ID not in ids
    assert DISCONTINUED_GUITAR_ID not in ids
    assert all(match.price.final_price <= GUITARS_BUDGET for match in result.products)


def test_results_are_ordered_by_final_price_then_product_id(store_db: Path):
    result = search_products(store_db, category="violões", max_price=GUITARS_BUDGET)

    keys = [(m.price.final_price, m.price.product_id) for m in result.products]
    assert keys == sorted(keys)


def test_price_filter_uses_final_price_not_list_price(store_db: Path):
    result = search_products(
        store_db,
        category="ukulele",
        max_price=UKULELE_BUDGET_BETWEEN_FINAL_AND_ORIGINAL,
    )

    [promoted] = [m for m in result.products if m.price.product_id == PROMOTED_UKULELE_ID]
    assert promoted.price.original_price == PROMOTED_UKULELE_ORIGINAL_PRICE
    assert promoted.price.original_price > UKULELE_BUDGET_BETWEEN_FINAL_AND_ORIGINAL
    assert promoted.price.final_price == PROMOTED_UKULELE_FINAL_PRICE
    assert promoted.price.active_promotion is not None


def test_price_filter_excludes_promoted_product_still_above_the_limit(store_db: Path):
    result = search_products(store_db, category="ukulele", max_price=Decimal("439.19"))

    assert PROMOTED_UKULELE_ID not in [m.price.product_id for m in result.products]


def test_price_limit_is_inclusive(store_db: Path):
    result = search_products(
        store_db, category="ukulele", max_price=PROMOTED_UKULELE_FINAL_PRICE
    )

    assert PROMOTED_UKULELE_ID in [m.price.product_id for m in result.products]


@pytest.mark.parametrize("wording", ["violão", "violões", "violao", "VIOLOES", " Violões "])
def test_guitar_wordings_resolve_to_the_guitars_category(store_db: Path, wording: str):
    result = search_products(store_db, category=wording, max_price=GUITARS_BUDGET)

    assert result.category == GUITARS_CATEGORY_NAME
    assert result.total_matches == len(AVAILABLE_GUITAR_IDS_UP_TO_BUDGET)


@pytest.mark.parametrize("wording", ["ukulele", "ukuleles", "Ukulelê", "Ukuleles"])
def test_ukulele_wordings_resolve_to_the_ukuleles_category(store_db: Path, wording: str):
    result = search_products(store_db, category=wording)

    assert result.category == UKULELES_CATEGORY_NAME
    assert result.products


@pytest.mark.parametrize(
    ("wording", "expected_name"),
    [
        ("guitarras", "Guitarras"),
        ("baixo", "Baixos"),
        ("bateria", "Baterias e Percussão"),
        ("percussão", "Baterias e Percussão"),
        ("teclado", "Teclados e Pianos"),
        ("piano", "Teclados e Pianos"),
        ("sax", "Instrumentos de Sopro (Madeiras)"),
        ("saxofone", "Instrumentos de Sopro (Madeiras)"),
        ("flauta", "Instrumentos de Sopro (Madeiras)"),
        ("trompete", "Instrumentos de Sopro (Metais)"),
        ("violino", "Cordas Orquestrais"),
        ("Teclados e Pianos", "Teclados e Pianos"),
    ],
)
def test_other_wordings_resolve_to_their_categories(
    store_db: Path, wording: str, expected_name: str
):
    result = search_products(store_db, category=wording)

    assert result.category == expected_name


def test_every_alias_key_is_a_real_category(store_db: Path):
    with closing(sqlite3.connect(store_db)) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM categories")}

    assert set(CATEGORY_ALIASES) <= names


@pytest.mark.parametrize("wording", EMPTY_CATEGORY_WORDINGS)
def test_category_without_products_returns_an_empty_result(store_db: Path, wording: str):
    result = search_products(store_db, category=wording)

    assert result.category is not None
    assert result.products == []
    assert result.total_matches == 0


def test_unknown_category_raises_with_the_valid_names(store_db: Path):
    with pytest.raises(UnknownCategoryError) as error:
        search_products(store_db, category="cavaquinho")

    assert error.value.wording == "cavaquinho"
    assert GUITARS_CATEGORY_NAME in error.value.valid_categories
    assert len(error.value.valid_categories) == len(CATEGORY_ALIASES)


def test_result_is_capped_and_reports_the_total(store_db: Path):
    result = search_products(store_db, category="violões")

    assert len(result.products) == MAX_SEARCH_RESULTS
    assert result.total_matches > MAX_SEARCH_RESULTS


def test_explicit_limit_caps_results_and_keeps_the_cheapest(store_db: Path):
    capped = search_products(store_db, category="violões", limit=3)
    everything = search_products(store_db, category="violões", limit=1000)

    assert [m.price.product_id for m in capped.products] == [
        m.price.product_id for m in everything.products[:3]
    ]
    assert capped.total_matches == everything.total_matches


def test_only_available_products_are_ever_returned(store_db: Path):
    everything = search_products(store_db, max_price=Decimal("100000"), limit=1000)

    ids = {m.price.product_id for m in everything.products}
    assert OUT_OF_STOCK_GUITAR_ID not in ids
    assert DISCONTINUED_GUITAR_ID not in ids
    assert everything.total_matches == len(ids)


def test_text_filter_matches_name_ignoring_case(store_db: Path):
    result = search_products(store_db, category="violões", text="CRAFTER")

    assert result.products
    assert all("crafter" in m.price.name.casefold() for m in result.products)


def test_text_filter_ignores_accents_on_either_side(store_db: Path):
    with_accent = search_products(store_db, category="violões", text="aço")
    without_accent = search_products(store_db, category="violões", text="aco")

    assert with_accent.total_matches > 0
    assert [m.price.product_id for m in with_accent.products] == [
        m.price.product_id for m in without_accent.products
    ]


def test_text_filter_also_searches_the_description(store_db: Path):
    result = search_products(store_db, category="violões", text="Engelmann")

    names = [m.price.name for m in result.products]
    assert "Crafter HT-100 Folk Aço Natural" in names
    assert not any("engelmann" in name.casefold() for name in names)


def test_text_filter_requires_every_word(store_db: Path):
    both = search_products(store_db, category="violões", text="yamaha nylon")
    only_yamaha = search_products(store_db, category="violões", text="yamaha")

    assert both.products
    assert both.total_matches < only_yamaha.total_matches
    assert all("yamaha" in m.price.name.casefold() for m in both.products)


def test_text_filter_with_no_match_returns_empty(store_db: Path):
    result = search_products(store_db, text="zzzz inexistente")

    assert result.products == []
    assert result.total_matches == 0


def test_text_filter_treats_like_wildcards_literally(store_db: Path):
    assert search_products(store_db, text="v%o").total_matches == 0
    assert search_products(store_db, text="v_o").total_matches == 0


def test_blank_category_is_ignored(store_db: Path):
    result = search_products(store_db, category="   ", max_price=GUITARS_BUDGET)

    assert result.category is None
    assert result.total_matches > 0


def test_search_without_any_filter_is_rejected(store_db: Path):
    with pytest.raises(ValueError, match="at least one"):
        search_products(store_db)
    with pytest.raises(ValueError, match="at least one"):
        search_products(store_db, category=" ", text=" ")


@pytest.mark.parametrize("bad_price", [Decimal("0"), Decimal("-5"), Decimal("NaN")])
def test_non_positive_or_non_finite_max_price_is_rejected(store_db: Path, bad_price: Decimal):
    with pytest.raises(ValueError, match="max_price"):
        search_products(store_db, category="violões", max_price=bad_price)


def test_tool_payload_shape_for_the_guitars_case(tools: dict[str, BaseTool]):
    payload = tools["search_catalog"].invoke({"category": "violões", "max_price": 1000})

    assert payload["category"] == GUITARS_CATEGORY_NAME
    assert payload["total_matches"] == 12
    assert payload["returned"] == 12
    assert payload["has_more"] is False
    assert sorted(p["product_id"] for p in payload["products"]) == sorted(
        AVAILABLE_GUITAR_IDS_UP_TO_BUDGET
    )
    [first] = [p for p in payload["products"] if p["product_id"] == 83]
    assert first == {
        "product_id": 83,
        "name": "Tagima Memphis AC-39 Nylon Natural",
        "category": GUITARS_CATEGORY_NAME,
        "original_price": "R$ 429,90",
        "active_promotion": None,
        "final_price": "R$ 429,90",
    }
    assert all("stock" not in key for p in payload["products"] for key in p)


def test_tool_payload_shows_promotion_with_original_and_final_price(
    tools: dict[str, BaseTool],
):
    payload = tools["search_catalog"].invoke({"category": "ukulele", "max_price": 500})

    [promoted] = [p for p in payload["products"] if p["product_id"] == PROMOTED_UKULELE_ID]
    assert promoted["original_price"] == "R$ 549,00"
    assert promoted["final_price"] == "R$ 439,20"
    assert promoted["active_promotion"]["discount_percent"] == 20


def test_tool_reports_when_more_matched(tools: dict[str, BaseTool]):
    payload = tools["search_catalog"].invoke({"category": "violões"})

    assert payload["returned"] == MAX_SEARCH_RESULTS
    assert payload["total_matches"] > MAX_SEARCH_RESULTS
    assert payload["has_more"] is True


def test_tool_reports_unknown_category_with_valid_names(tools: dict[str, BaseTool]):
    payload = tools["search_catalog"].invoke({"category": "cavaquinho"})

    assert payload["category_recognized"] is False
    assert "cavaquinho" in payload["message"]
    assert GUITARS_CATEGORY_NAME in payload["valid_categories"]
    assert "products" not in payload


def test_tool_empty_category_returns_empty_products(tools: dict[str, BaseTool]):
    payload = tools["search_catalog"].invoke({"category": "saxofone"})

    assert payload["products"] == []
    assert payload["total_matches"] == 0
    assert payload["has_more"] is False


@pytest.mark.parametrize("bad_price", [0, -10])
def test_tool_rejects_invalid_max_price_to_the_model(
    tools: dict[str, BaseTool], bad_price: int
):
    result = tools["search_catalog"].invoke({"category": "violões", "max_price": bad_price})

    assert "max_price must be a positive number" in result


def test_tool_rejects_search_without_filters_to_the_model(tools: dict[str, BaseTool]):
    result = tools["search_catalog"].invoke({})

    assert "at least one" in result
