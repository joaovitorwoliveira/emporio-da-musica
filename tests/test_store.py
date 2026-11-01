from decimal import Decimal
from pathlib import Path

import pytest

from emporio.store import (
    ActivePromotion,
    calculate_final_price,
    find_products,
    normalize_text,
)
from emporio.tools import build_tools, format_brl

GD20_ID = 95
GD20_NAME = "Takamine GD20 Dreadnought Natural"
GD20_PRICE = Decimal("2199.00")
PROMOTED_PRODUCT_ID = 94
PROMOTED_DISCOUNT_PERCENT = 8
PROMOTED_ORIGINAL_PRICE = Decimal("5999.00")
PROMOTED_FINAL_PRICE = Decimal("5519.08")


def test_lookup_by_exact_id(store_db: Path):
    [product] = find_products(store_db, product_id=GD20_ID)

    assert product.name == GD20_NAME
    assert product.original_price == GD20_PRICE


def test_lookup_by_partial_name_ignores_case(store_db: Path):
    [product] = find_products(store_db, name="takamine GD20")

    assert product.product_id == GD20_ID


def test_lookup_by_name_matches_accented_names_without_accents(store_db: Path):
    [product] = find_products(store_db, name="yamaha f310 aco")

    assert product.name == "Yamaha F310 Aço Natural"


def test_lookup_by_name_matches_unaccented_names_with_accents(store_db: Path):
    [product] = find_products(store_db, name="TAKAMINE GD20 Dreadnought NATURAL")

    assert product.product_id == GD20_ID


def test_normalize_text_strips_accents_case_and_extra_spaces():
    assert normalize_text("  Violão   CLÁSSICO ") == "violao classico"


def test_lookup_with_no_match_returns_empty_list(store_db: Path):
    assert find_products(store_db, name="saxofone tenor") == []
    assert find_products(store_db, product_id=99999) == []


def test_lookup_treats_like_wildcards_literally(store_db: Path):
    assert find_products(store_db, name="%") == []
    assert find_products(store_db, name="_") == []


def test_lookup_without_criteria_fails_loudly(store_db: Path):
    with pytest.raises(ValueError, match="product_id or a non-empty name"):
        find_products(store_db)
    with pytest.raises(ValueError, match="product_id or a non-empty name"):
        find_products(store_db, name="   ")


def test_broad_name_returns_a_capped_list(store_db: Path):
    products = find_products(store_db, name="yamaha")

    assert 1 < len(products) <= 5


def test_final_price_without_active_promotion_is_the_original_price(store_db: Path):
    [product] = find_products(store_db, product_id=GD20_ID)

    assert product.active_promotion is None
    assert product.final_price == GD20_PRICE


def test_final_price_applies_the_active_promotion(store_db: Path):
    [product] = find_products(store_db, product_id=PROMOTED_PRODUCT_ID)

    assert product.active_promotion is not None
    assert product.active_promotion.discount_percent == PROMOTED_DISCOUNT_PERCENT
    assert product.original_price == PROMOTED_ORIGINAL_PRICE
    assert product.final_price == PROMOTED_FINAL_PRICE


def test_final_price_rounds_half_up_to_two_places():
    promotion = ActivePromotion(description="test", discount_percent=15)

    assert calculate_final_price(Decimal("10.10"), promotion) == Decimal("8.59")


def test_format_brl_uses_brazilian_separators():
    assert format_brl(Decimal("2199.00")) == "R$ 2.199,00"
    assert format_brl(Decimal("599.90")) == "R$ 599,90"


def test_find_product_tool_returns_formatted_prices(store_db: Path):
    [find_product] = build_tools(store_db)

    result = find_product.invoke({"name": "takamine gd20"})

    assert result == {
        "products": [
            {
                "product_id": GD20_ID,
                "name": GD20_NAME,
                "original_price": "R$ 2.199,00",
                "active_promotion": None,
                "final_price": "R$ 2.199,00",
            }
        ]
    }


def test_find_product_tool_reports_missing_criteria_to_the_model(store_db: Path):
    [find_product] = build_tools(store_db)

    result = find_product.invoke({})

    assert "product_id or a non-empty name" in result
