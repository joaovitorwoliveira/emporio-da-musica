import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from langchain_core.tools import BaseTool

from emporio.orders import find_verified_order
from emporio.settings import DATA_DIR, DEFAULT_STORE_TIMEZONE
from emporio.tools import IDENTITY_CHECK_FAILED_MESSAGE


ORDER_8_ID = 8
ORDER_8_EMAIL = "anacarol.ferreira@coldmail.com"
ORDER_8_PHONE = "(67) 99654-7821"
ORDER_8_DAYS_LATE = 23
SHARED_EMAIL = "bruno.martins@jmail.com"
SHARED_EMAIL_ORDER_ID = 10
SHARED_EMAIL_CUSTOMER_ID = 11
SHARED_EMAIL_OTHER_CUSTOMER_ID = 43
OTHER_CUSTOMER_ORDER_ID = 1
OTHER_CUSTOMER_EMAIL = "pedro.oliveira@jmail.com"
UNKNOWN_ORDER_ID = 9999
GENERIC_FAILURE = {"verified": False, "message": IDENTITY_CHECK_FAILED_MESSAGE}


def get_order(tools: dict[str, BaseTool], order_id: int | None, contact: str | None):
    return tools["get_order"].invoke({"order_id": order_id, "contact": contact})


def read_orders_csv() -> list[dict[str, str]]:
    with (DATA_DIR / "orders.csv").open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_identity_check_passes_by_email_ignoring_case_and_spaces(tools: dict[str, BaseTool]):
    result = get_order(tools, ORDER_8_ID, "  AnaCarol.Ferreira@ColdMail.com ")

    assert result["verified"] is True
    assert result["order"]["order_id"] == ORDER_8_ID


@pytest.mark.parametrize(
    "typed_phone",
    [
        ORDER_8_PHONE,
        "67996547821",
        "(67)99654-7821",
        "67 99654 7821",
        "+55 (67) 99654-7821",
        "5567996547821",
    ],
)
def test_identity_check_passes_by_phone_in_any_format(
    tools: dict[str, BaseTool], typed_phone: str
):
    result = get_order(tools, ORDER_8_ID, typed_phone)

    assert result["verified"] is True


@pytest.mark.parametrize("partial_phone", ["99654-7821", "7821", "996547821"])
def test_partial_phone_does_not_pass(tools: dict[str, BaseTool], partial_phone: str):
    assert get_order(tools, ORDER_8_ID, partial_phone) == GENERIC_FAILURE


def test_order_details_are_formatted_for_the_model(tools: dict[str, BaseTool]):
    result = get_order(tools, ORDER_8_ID, ORDER_8_EMAIL)

    assert result["order"]["status"] == "enviado"
    assert result["order"]["order_date"] == "15/02/2026"
    assert result["order"]["order_total"] == "R$ 349,90"
    assert result["order"]["payment_method"] == "cartão de débito"
    assert result["order"]["tracking_code"] == "BRJL5544332BR"
    assert result["order"]["estimated_delivery"] == "28/02/2026"
    [item] = result["order"]["items"]
    assert item["quantity"] == 1
    assert item["product_name"]


def test_order_total_is_authoritative_even_when_it_differs_from_item_prices(
    tools: dict[str, BaseTool],
):
    result = get_order(tools, 3, "isabela.moreira@jmail.com")

    assert result["order"]["order_total"] == "R$ 3.450,00"
    assert result["order"]["items"][0]["quantity"] == 2


def test_unshipped_order_has_no_tracking_or_delivery_estimate(tools: dict[str, BaseTool]):
    result = get_order(tools, SHARED_EMAIL_ORDER_ID, SHARED_EMAIL)

    assert result["order"]["tracking_code"] is None
    assert result["order"]["estimated_delivery"] is None
    assert result["order"]["is_late"] is False


@pytest.mark.parametrize(
    "order_id, contact",
    [
        (ORDER_8_ID, "someone.else@jmail.com"),
        (ORDER_8_ID, "67999999999"),
        (ORDER_8_ID, OTHER_CUSTOMER_EMAIL),
        (UNKNOWN_ORDER_ID, ORDER_8_EMAIL),
        (UNKNOWN_ORDER_ID, ORDER_8_PHONE),
        (ORDER_8_ID, ""),
        (ORDER_8_ID, "   "),
        (ORDER_8_ID, None),
        (None, ORDER_8_EMAIL),
        (None, None),
    ],
)
def test_every_failed_check_returns_the_same_generic_result(
    tools: dict[str, BaseTool], order_id: int | None, contact: str | None
):
    assert get_order(tools, order_id, contact) == GENERIC_FAILURE


def test_mismatch_and_nonexistent_order_are_indistinguishable(tools: dict[str, BaseTool]):
    mismatch = get_order(tools, ORDER_8_ID, "someone.else@jmail.com")
    nonexistent = get_order(tools, UNKNOWN_ORDER_ID, "someone.else@jmail.com")

    assert json.dumps(mismatch, sort_keys=True) == json.dumps(nonexistent, sort_keys=True)


def test_shared_email_unlocks_the_order_of_customer_11(tools: dict[str, BaseTool]):
    result = get_order(tools, SHARED_EMAIL_ORDER_ID, SHARED_EMAIL)

    assert result["verified"] is True
    assert result["order"]["customer_first_name"] == "Bruno"


def test_shared_email_is_refused_for_every_order_of_other_customers(
    tools: dict[str, BaseTool],
):
    other_orders = [
        row for row in read_orders_csv()
        if row["customer_id"] != str(SHARED_EMAIL_CUSTOMER_ID)
    ]

    assert other_orders
    for row in other_orders:
        assert get_order(tools, int(row["order_id"]), SHARED_EMAIL) == GENERIC_FAILURE


def test_customer_43_has_no_orders_so_the_shared_email_only_reaches_customer_11():
    customers_with_orders = {row["customer_id"] for row in read_orders_csv()}

    assert str(SHARED_EMAIL_OTHER_CUSTOMER_ID) not in customers_with_orders


def test_phone_of_customer_43_does_not_unlock_the_order_of_customer_11(
    tools: dict[str, BaseTool],
):
    assert get_order(tools, SHARED_EMAIL_ORDER_ID, "(67) 99456-3456") == GENERIC_FAILURE


def test_shipped_order_8_is_late_by_23_days_at_the_default_reference_date(
    tools: dict[str, BaseTool],
):
    result = get_order(tools, ORDER_8_ID, ORDER_8_EMAIL)

    assert result["order"]["is_late"] is True
    assert result["order"]["days_late"] == ORDER_8_DAYS_LATE


def reference_date_at(moment: str) -> datetime:
    return datetime.fromisoformat(moment).replace(tzinfo=ZoneInfo(DEFAULT_STORE_TIMEZONE))


def test_order_is_not_late_on_the_estimated_delivery_day(store_db: Path):
    order = find_verified_order(
        store_db, ORDER_8_ID, ORDER_8_EMAIL, reference_date_at("2026-02-28T23:59")
    )

    assert order is not None
    assert order.is_late is False
    assert order.days_late == 0


def test_order_is_late_by_one_day_the_day_after(store_db: Path):
    order = find_verified_order(
        store_db, ORDER_8_ID, ORDER_8_EMAIL, reference_date_at("2026-03-01T00:00")
    )

    assert order is not None
    assert order.days_late == 1


def test_only_shipped_orders_are_flagged_late(tools: dict[str, BaseTool]):
    delivered = get_order(tools, 4, "lucas.mendes@jmail.com")
    pending = get_order(tools, 16, "(67) 99567-8901")
    cancelled = get_order(tools, 17, "matheus.correia@hayoo.com.br")

    for result in (delivered, pending, cancelled):
        assert result["verified"] is True
        assert result["order"]["is_late"] is False


def test_payload_carries_no_customer_data_beyond_the_first_name(tools: dict[str, BaseTool]):
    result = get_order(tools, ORDER_8_ID, ORDER_8_EMAIL)
    serialized = json.dumps(result, ensure_ascii=False).lower()

    assert result["order"]["customer_first_name"] == "Ana"
    for private_value in (
        "carolina",
        "ferreira",
        ORDER_8_EMAIL,
        "996547821",
        "99654",
        "campo grande",
    ):
        assert private_value not in serialized


def test_order_payload_has_only_the_expected_fields(tools: dict[str, BaseTool]):
    result = get_order(tools, ORDER_8_ID, ORDER_8_EMAIL)

    assert set(result["order"]) == {
        "order_id",
        "customer_first_name",
        "status",
        "order_date",
        "items",
        "order_total",
        "payment_method",
        "tracking_code",
        "estimated_delivery",
        "is_late",
        "days_late",
    }
