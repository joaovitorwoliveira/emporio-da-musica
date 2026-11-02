from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from langchain_core.tools import BaseTool

from emporio.eligibility import (
    RIGHT_WINDOWS,
    CountsFrom,
    Right,
    calculate_rights,
    evaluate_window,
)
from emporio.models import OrderStatus
from emporio.orders import find_verified_order
from emporio.settings import DEFAULT_STORE_TIMEZONE
from emporio.tools import (
    CANCELLED_AFTER_SALES_MESSAGE,
    DEFECT_EXCHANGE_EXPIRED_NOTE,
    IDENTITY_CHECK_FAILED_MESSAGE,
    NOT_DELIVERED_AFTER_SALES_MESSAGE,
)

ORDER_7_ID = 7
ORDER_7_CONTACT = "leticia.rocha@jmail.com"
ORDER_4_ID = 4
ORDER_4_CONTACT = "lucas.mendes@jmail.com"
PENDING_ORDER_ID = 16
PENDING_ORDER_CONTACT = "(67) 99567-8901"
CANCELLED_ORDER_ID = 17
CANCELLED_ORDER_CONTACT = "matheus.correia@hayoo.com.br"
WITHDRAWAL_WINDOW = RIGHT_WINDOWS[0]
START_DATE = date(2026, 2, 17)


def reference_date_at(moment: str) -> datetime:
    return datetime.fromisoformat(moment).replace(tzinfo=ZoneInfo(DEFAULT_STORE_TIMEZONE))


def order_rights(store_db: Path, order_id: int, contact: str, moment: str):
    order = find_verified_order(store_db, order_id, contact, reference_date_at(moment))
    assert order is not None
    return {eligibility.right: eligibility for eligibility in order.rights}


def get_order(tools: dict[str, BaseTool], order_id: int, contact: str):
    return tools["get_order"].invoke({"order_id": order_id, "contact": contact})


def test_window_lengths_follow_the_policy():
    assert {(w.right, w.days, w.counts_from) for w in RIGHT_WINDOWS} == {
        (Right.WITHDRAWAL, 7, CountsFrom.RECEIPT_DATE),
        (Right.PREFERENCE_EXCHANGE, 7, CountsFrom.RECEIPT_DATE),
        (Right.DEFECT_EXCHANGE, 30, CountsFrom.ORDER_DATE),
        (Right.LEGAL_WARRANTY, 90, CountsFrom.RECEIPT_DATE),
    }


def test_day_before_the_deadline_is_open_with_one_day_remaining():
    result = evaluate_window(WITHDRAWAL_WINDOW, START_DATE, reference_date_at("2026-02-23T10:00"))

    assert result.deadline == date(2026, 2, 24)
    assert result.is_open is True
    assert result.days_remaining == 1
    assert result.days_since_deadline is None


def test_deadline_day_is_still_open_with_zero_days_remaining_until_midnight():
    result = evaluate_window(WITHDRAWAL_WINDOW, START_DATE, reference_date_at("2026-02-24T23:59"))

    assert result.is_open is True
    assert result.days_remaining == 0
    assert result.days_since_deadline is None


def test_day_after_the_deadline_is_expired_by_one_day():
    result = evaluate_window(WITHDRAWAL_WINDOW, START_DATE, reference_date_at("2026-02-25T00:00"))

    assert result.is_open is False
    assert result.days_remaining is None
    assert result.days_since_deadline == 1


def test_start_day_itself_leaves_the_full_window():
    result = evaluate_window(WITHDRAWAL_WINDOW, START_DATE, reference_date_at("2026-02-17T09:00"))

    assert result.days_remaining == WITHDRAWAL_WINDOW.days


def test_order_7_has_only_the_legal_warranty_open(store_db: Path):
    rights = order_rights(store_db, ORDER_7_ID, ORDER_7_CONTACT, "2026-03-23T10:00")

    assert not rights[Right.WITHDRAWAL].is_open
    assert rights[Right.WITHDRAWAL].deadline == date(2026, 2, 24)
    assert not rights[Right.PREFERENCE_EXCHANGE].is_open
    assert rights[Right.PREFERENCE_EXCHANGE].deadline == date(2026, 2, 24)
    assert not rights[Right.DEFECT_EXCHANGE].is_open
    assert rights[Right.DEFECT_EXCHANGE].deadline == date(2026, 3, 5)
    warranty = rights[Right.LEGAL_WARRANTY]
    assert warranty.is_open
    assert warranty.deadline == date(2026, 5, 18)
    assert warranty.days_remaining == 56


def test_order_4_legal_warranty_expired_by_one_day(store_db: Path):
    rights = order_rights(store_db, ORDER_4_ID, ORDER_4_CONTACT, "2026-03-23T10:00")

    warranty = rights[Right.LEGAL_WARRANTY]
    assert warranty.deadline == date(2026, 3, 22)
    assert not warranty.is_open
    assert warranty.days_since_deadline == 1


def test_order_on_the_exact_deadline_day_is_still_open(store_db: Path):
    on_deadline = order_rights(store_db, ORDER_7_ID, ORDER_7_CONTACT, "2026-05-18T10:00")
    day_after = order_rights(store_db, ORDER_7_ID, ORDER_7_CONTACT, "2026-05-19T10:00")

    assert on_deadline[Right.LEGAL_WARRANTY].is_open
    assert on_deadline[Right.LEGAL_WARRANTY].days_remaining == 0
    assert not day_after[Right.LEGAL_WARRANTY].is_open
    assert day_after[Right.LEGAL_WARRANTY].days_since_deadline == 1


def test_defect_exchange_counts_from_the_order_date_not_the_receipt_date(store_db: Path):
    on_deadline = order_rights(store_db, ORDER_7_ID, ORDER_7_CONTACT, "2026-03-05T10:00")

    assert on_deadline[Right.DEFECT_EXCHANGE].is_open
    assert on_deadline[Right.DEFECT_EXCHANGE].counts_from is CountsFrom.ORDER_DATE


@pytest.mark.parametrize(
    "status", [OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.SHIPPED, OrderStatus.CANCELLED]
)
def test_orders_that_were_not_delivered_have_no_rights(status: OrderStatus):
    assert calculate_rights(status, date(2026, 3, 1), None, reference_date_at("2026-03-23T10:00")) == ()


def test_delivered_order_without_estimated_delivery_fails_loudly():
    with pytest.raises(ValueError, match="no estimated delivery date"):
        calculate_rights(
            OrderStatus.DELIVERED, date(2026, 3, 1), None, reference_date_at("2026-03-23T10:00")
        )


def test_payload_lists_each_right_of_a_delivered_order(tools: dict[str, BaseTool]):
    after_sales = get_order(tools, ORDER_7_ID, ORDER_7_CONTACT)["order"]["after_sales"]

    assert after_sales["receipt_date"] == "17/02/2026"
    withdrawal, preference, defect, warranty = after_sales["rights"]
    assert withdrawal == {
        "right": "Direito de arrependimento (devolução)",
        "counts_from": "data de recebimento (data estimada de entrega)",
        "deadline": "24/02/2026",
        "is_open": False,
        "days_since_deadline": 27,
    }
    assert preference["is_open"] is False
    assert preference["deadline"] == "24/02/2026"
    assert defect["is_open"] is False
    assert defect["deadline"] == "05/03/2026"
    assert defect["counts_from"] == "data do pedido"
    assert defect["note"] == DEFECT_EXCHANGE_EXPIRED_NOTE
    assert all("note" not in right for right in (withdrawal, preference, warranty))
    assert warranty == {
        "right": "Garantia legal (90 dias)",
        "counts_from": "data de recebimento (data estimada de entrega)",
        "deadline": "18/05/2026",
        "is_open": True,
        "days_remaining": 56,
    }


def test_payload_reports_that_windows_start_on_receipt_for_undelivered_orders(
    tools: dict[str, BaseTool],
):
    after_sales = get_order(tools, PENDING_ORDER_ID, PENDING_ORDER_CONTACT)["order"]["after_sales"]

    assert after_sales == {"message": NOT_DELIVERED_AFTER_SALES_MESSAGE}


def test_payload_reports_no_rights_for_cancelled_orders(tools: dict[str, BaseTool]):
    after_sales = get_order(tools, CANCELLED_ORDER_ID, CANCELLED_ORDER_CONTACT)["order"]["after_sales"]

    assert after_sales == {"message": CANCELLED_AFTER_SALES_MESSAGE}


def test_failed_identity_check_exposes_no_eligibility(tools: dict[str, BaseTool]):
    result = get_order(tools, ORDER_7_ID, "someone.else@jmail.com")

    assert result == {"verified": False, "message": IDENTITY_CHECK_FAILED_MESSAGE}
