from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from emporio.models import OrderStatus

WITHDRAWAL_DAYS = 7
PREFERENCE_EXCHANGE_DAYS = 7
DEFECT_EXCHANGE_DAYS = 30
LEGAL_WARRANTY_DAYS = 90


class Right(StrEnum):
    WITHDRAWAL = "withdrawal"
    PREFERENCE_EXCHANGE = "preference_exchange"
    DEFECT_EXCHANGE = "defect_exchange"
    LEGAL_WARRANTY = "legal_warranty"


class CountsFrom(StrEnum):
    RECEIPT_DATE = "receipt_date"
    ORDER_DATE = "order_date"


@dataclass(frozen=True)
class RightWindow:
    right: Right
    days: int
    counts_from: CountsFrom


RIGHT_WINDOWS = (
    RightWindow(Right.WITHDRAWAL, WITHDRAWAL_DAYS, CountsFrom.RECEIPT_DATE),
    RightWindow(Right.PREFERENCE_EXCHANGE, PREFERENCE_EXCHANGE_DAYS, CountsFrom.RECEIPT_DATE),
    RightWindow(Right.DEFECT_EXCHANGE, DEFECT_EXCHANGE_DAYS, CountsFrom.ORDER_DATE),
    RightWindow(Right.LEGAL_WARRANTY, LEGAL_WARRANTY_DAYS, CountsFrom.RECEIPT_DATE),
)


@dataclass(frozen=True)
class RightEligibility:
    right: Right
    counts_from: CountsFrom
    deadline: date
    days_until_deadline: int

    @property
    def is_open(self) -> bool:
        return self.days_until_deadline >= 0

    @property
    def days_remaining(self) -> int | None:
        return self.days_until_deadline if self.is_open else None

    @property
    def days_since_deadline(self) -> int | None:
        return None if self.is_open else -self.days_until_deadline


def evaluate_window(
    window: RightWindow, start_date: date, reference_date: datetime
) -> RightEligibility:
    """Single definition of the day counting rule.

    The deadline is the start date plus the window length in calendar days, and
    the deadline day itself is still open.
    """
    deadline = start_date + timedelta(days=window.days)
    return RightEligibility(
        right=window.right,
        counts_from=window.counts_from,
        deadline=deadline,
        days_until_deadline=(deadline - reference_date.date()).days,
    )


def calculate_rights(
    status: OrderStatus,
    order_date: date,
    receipt_date: date | None,
    reference_date: datetime,
) -> tuple[RightEligibility, ...]:
    """Per-right eligibility; only delivered orders have rights to evaluate.

    The receipt date is the order's estimated delivery, since the records do not
    hold the actual receipt.
    """
    if status is not OrderStatus.DELIVERED:
        return ()
    if receipt_date is None:
        raise ValueError(
            "A delivered order has no estimated delivery date, so the receipt date "
            "and the right windows that count from it cannot be determined."
        )
    start_dates = {
        CountsFrom.RECEIPT_DATE: receipt_date,
        CountsFrom.ORDER_DATE: order_date,
    }
    return tuple(
        evaluate_window(window, start_dates[window.counts_from], reference_date)
        for window in RIGHT_WINDOWS
    )
