import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool, ToolException

from emporio.catalog import lookup_products
from emporio.payments import (
    MAX_INSTALLMENTS,
    InstallmentRefusal,
    check_installments,
    installment_value,
    is_installment_allowed,
    max_installments,
    minimum_installment_value,
    pix_price,
    to_amount,
)

GD20_ID = 95
CHEAPEST_ID = 119
PROMOTED_IDS = [121, 90, 127, 94]
PROMOTED_ID = 121
OUT_OF_STOCK_ID = 96
COMING_SOON_ID = 130


def money(text: str) -> Decimal:
    return Decimal(text)


def test_gd20_allows_twelve_installments(store_db: Path):
    [lookup] = lookup_products(store_db, product_id=GD20_ID)

    assert lookup.price.final_price == money("2199.00")
    assert max_installments(lookup.price.final_price) == MAX_INSTALLMENTS
    assert is_installment_allowed(lookup.price.final_price, 12)


def test_cheapest_product_allows_three_installments_but_not_four(store_db: Path):
    [lookup] = lookup_products(store_db, product_id=CHEAPEST_ID)
    price = lookup.price.final_price

    assert price == money("159.90")
    assert is_installment_allowed(price, 3)
    assert not is_installment_allowed(price, 4)
    assert max_installments(price) == 3


@pytest.mark.parametrize("product_id", PROMOTED_IDS)
def test_pix_price_of_a_promoted_product_equals_its_final_price(
    store_db: Path, product_id: int
):
    [lookup] = lookup_products(store_db, product_id=product_id)

    assert lookup.price.active_promotion is not None
    final_price = lookup.price.final_price
    assert pix_price(final_price, has_active_promotion=True) == final_price


def test_pix_price_takes_five_percent_off_without_a_promotion():
    assert pix_price(money("2199.00"), has_active_promotion=False) == money("2089.05")


def test_pix_price_rounds_half_up_to_the_cent():
    # 159.90 * 0.95 = 151.905
    assert pix_price(money("159.90"), has_active_promotion=False) == money("151.91")


@pytest.mark.parametrize(
    ("total", "installments"),
    [
        ("100.00", 2),
        ("150.00", 3),
        ("400.00", 4),
        ("480.00", 6),
        ("700.00", 7),
        ("1200.00", 12),
    ],
)
def test_exactly_the_minimum_per_installment_is_allowed(total: str, installments: int):
    assert is_installment_allowed(money(total), installments)


@pytest.mark.parametrize(
    ("total", "installments"),
    [
        ("99.99", 2),
        ("149.99", 3),
        ("319.99", 4),
        ("479.99", 6),
        ("699.99", 7),
        ("1199.99", 12),
    ],
)
def test_one_cent_below_the_minimum_per_installment_is_refused(
    total: str, installments: int
):
    assert not is_installment_allowed(money(total), installments)


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        ("30.00", 1),
        ("99.99", 1),
        ("100.00", 2),
        ("150.00", 3),
        ("319.99", 3),
        ("320.00", 4),
        ("479.99", 5),
        ("480.00", 6),
        ("699.99", 6),
        ("700.00", 7),
        ("1199.99", 11),
        ("1200.00", 12),
        ("99999.00", 12),
    ],
)
def test_maximum_installments_follows_the_tiers(total: str, expected: int):
    assert max_installments(money(total)) == expected


def test_minimum_installment_per_tier():
    assert minimum_installment_value(3) == money("50.00")
    assert minimum_installment_value(4) == money("80.00")
    assert minimum_installment_value(6) == money("80.00")
    assert minimum_installment_value(7) == money("100.00")
    assert minimum_installment_value(12) == money("100.00")


def test_a_single_payment_is_always_allowed():
    assert is_installment_allowed(money("0.01"), 1)


def test_more_than_twelve_installments_are_refused_even_for_a_large_total():
    check = check_installments(money("50000.00"), 13)

    assert not check.allowed
    assert check.refusal is InstallmentRefusal.ABOVE_MAXIMUM
    assert check.installment_value is None


def test_check_below_the_minimum_reports_the_minimum():
    check = check_installments(money("159.90"), 4)

    assert not check.allowed
    assert check.refusal is InstallmentRefusal.BELOW_MINIMUM
    assert check.minimum_installment == money("80.00")


def test_check_allowed_reports_the_installment_value():
    check = check_installments(money("2199.00"), 10)

    assert check.allowed
    assert check.installment_value == money("219.90")
    assert check.refusal is None


def test_installment_value_rounds_half_up_to_the_cent():
    assert installment_value(money("2199.00"), 7) == money("314.14")
    assert installment_value(money("0.05"), 2) == money("0.03")


@pytest.mark.parametrize("installments", [0, -1])
def test_fewer_than_one_installment_is_invalid(installments: int):
    with pytest.raises(ValueError):
        check_installments(money("100.00"), installments)
    with pytest.raises(ValueError):
        is_installment_allowed(money("100.00"), installments)


@pytest.mark.parametrize("value", [0, -5, 0.001, float("inf"), float("nan")])
def test_amount_must_be_a_positive_number(value: float):
    with pytest.raises(ValueError):
        to_amount(value)


def test_amount_is_rounded_to_the_cent():
    assert to_amount(159.9) == money("159.90")


def test_tool_gd20_in_ten_installments(tools: dict[str, BaseTool]):
    [product] = tools["get_payment_options"].invoke(
        {"name": "takamine gd20", "installments": 10}
    )["products"]

    assert product == {
        "product_id": GD20_ID,
        "name": product["name"],
        "original_price": "R$ 2.199,00",
        "active_promotion": None,
        "final_price": "R$ 2.199,00",
        "availability": "available",
        "availability_label": "disponível",
        "payment_options_available": True,
        "pix_price": "R$ 2.089,05",
        "pix_discount_applied": True,
        "pix_discount_percent": 5,
        "max_installments": 12,
        "max_installment_value": "R$ 183,25",
        "requested_installments": {
            "installments": 10,
            "allowed": True,
            "installment_value": "R$ 219,90",
        },
    }


def test_tool_without_requested_installments_omits_that_block(tools: dict[str, BaseTool]):
    [product] = tools["get_payment_options"].invoke({"product_id": GD20_ID})["products"]

    assert "requested_installments" not in product


def test_tool_refuses_four_installments_of_the_cheapest_product(
    tools: dict[str, BaseTool],
):
    [product] = tools["get_payment_options"].invoke(
        {"product_id": CHEAPEST_ID, "installments": 4}
    )["products"]

    assert product["max_installments"] == 3
    assert product["max_installment_value"] == "R$ 53,30"
    assert product["requested_installments"] == {
        "installments": 4,
        "allowed": False,
        "reason": "below_minimum_installment",
        "minimum_installment": "R$ 80,00",
        "message": "Em 4x a parcela ficaria abaixo do mínimo de R$ 80,00 por parcela.",
    }


def test_tool_refuses_more_than_twelve_installments(tools: dict[str, BaseTool]):
    [product] = tools["get_payment_options"].invoke(
        {"product_id": GD20_ID, "installments": 18}
    )["products"]

    assert product["max_installments"] == 12
    assert product["requested_installments"] == {
        "installments": 18,
        "allowed": False,
        "reason": "above_maximum_installments",
        "message": "O máximo é 12x sem juros.",
    }


def test_tool_pix_of_a_promoted_product_is_the_final_price(tools: dict[str, BaseTool]):
    [product] = tools["get_payment_options"].invoke({"product_id": PROMOTED_ID})["products"]

    assert product["active_promotion"]["discount_percent"] == 20
    assert product["final_price"] == "R$ 439,20"
    assert product["pix_price"] == product["final_price"]
    assert product["pix_discount_applied"] is False
    assert "pix_discount_percent" not in product
    assert "6.2" in product["pix_note"]


def test_tool_pix_ignores_an_ended_promotion(tools: dict[str, BaseTool]):
    [product] = tools["get_payment_options"].invoke({"product_id": GD20_ID})["products"]

    assert product["pix_discount_applied"] is True
    assert "pix_note" not in product


@pytest.mark.parametrize("product_id", [OUT_OF_STOCK_ID, COMING_SOON_ID])
def test_tool_returns_no_payment_options_for_an_unavailable_product(
    tools: dict[str, BaseTool], product_id: int
):
    [product] = tools["get_payment_options"].invoke(
        {"product_id": product_id, "installments": 3}
    )["products"]

    assert product["payment_options_available"] is False
    assert product["availability"] != "available"
    assert "message" in product
    assert not {"pix_price", "max_installments", "requested_installments"} & product.keys()


def test_tool_with_an_amount_has_no_pix_price(tools: dict[str, BaseTool]):
    payload = tools["get_payment_options"].invoke({"amount": 1500, "installments": 12})

    assert payload["amount"] == "R$ 1.500,00"
    assert payload["pix_price"] is None
    assert "promoção" in payload["pix_note"]
    assert payload["max_installments"] == 12
    assert payload["max_installment_value"] == "R$ 125,00"
    assert payload["requested_installments"]["allowed"] is True
    assert "products" not in payload


def test_tool_amount_below_the_minimum_for_the_requested_installments(
    tools: dict[str, BaseTool],
):
    payload = tools["get_payment_options"].invoke({"amount": 600, "installments": 10})

    assert payload["max_installments"] == 6
    assert payload["requested_installments"]["allowed"] is False
    assert payload["requested_installments"]["minimum_installment"] == "R$ 100,00"


def call_raw(tools: dict[str, BaseTool], **arguments: object) -> object:
    # Calls the function behind the tool, bypassing handle_tool_error, which would
    # turn the ToolException into a plain error message.
    function = tools["get_payment_options"].func  # type: ignore[attr-defined]
    return function(**arguments)


@pytest.mark.parametrize("installments", [0, -3])
def test_tool_rejects_fewer_than_one_installment(
    tools: dict[str, BaseTool], installments: int
):
    with pytest.raises(ToolException, match="at least 1"):
        call_raw(tools, product_id=GD20_ID, installments=installments)


def test_tool_rejects_a_missing_product_reference(tools: dict[str, BaseTool]):
    with pytest.raises(ToolException, match="product_id"):
        call_raw(tools, installments=3)


def test_tool_rejects_a_product_together_with_an_amount(tools: dict[str, BaseTool]):
    with pytest.raises(ToolException, match="não os dois"):
        call_raw(tools, product_id=GD20_ID, amount=100)


def test_tool_rejects_a_non_positive_amount(tools: dict[str, BaseTool]):
    with pytest.raises(ToolException, match="positive"):
        call_raw(tools, amount=0)


def test_tool_errors_reach_the_model_as_a_message(tools: dict[str, BaseTool]):
    message = tools["get_payment_options"].invoke({"product_id": GD20_ID, "installments": 0})

    assert isinstance(message, str)
    assert "at least 1" in message


def test_tool_ignores_a_blank_name_when_an_amount_is_given(tools: dict[str, BaseTool]):
    payload = tools["get_payment_options"].invoke({"name": "  ", "amount": 100})

    assert payload["amount"] == "R$ 100,00"


def test_tool_returns_an_empty_list_when_no_product_matches(tools: dict[str, BaseTool]):
    assert tools["get_payment_options"].invoke({"name": "zzz inexistente"}) == {"products": []}


def test_tool_lists_every_ambiguous_match(tools: dict[str, BaseTool]):
    products = tools["get_payment_options"].invoke({"name": "takamine"})["products"]

    assert len(products) > 1
    assert all("payment_options_available" in product for product in products)


def test_tool_uses_the_promotion_of_the_database(store_db: Path, tools: dict[str, BaseTool]):
    with closing(sqlite3.connect(store_db)) as connection:
        connection.execute("UPDATE promotions SET is_active = 1 WHERE product_id = ?", (GD20_ID,))
        connection.commit()

    [product] = tools["get_payment_options"].invoke({"product_id": GD20_ID})["products"]

    assert product["pix_discount_applied"] is False
    assert product["pix_price"] == product["final_price"]
