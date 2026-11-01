import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from emporio.models import OrderStatus, PaymentMethod
from emporio.store import (
    connect,
    digits_only,
    from_cents,
    normalize_email,
    strip_country_code,
)

EMAIL_MARKER = "@"

SELECT_ORDER_CONTACT = """
SELECT c.phone, c.email
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_id = ?
"""

SELECT_ORDER = """
SELECT
    o.order_date, o.status, o.total_cents, o.payment_method,
    o.tracking_code, o.estimated_delivery, c.name
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_id = ?
"""

SELECT_ORDER_ITEMS = """
SELECT p.name, i.quantity
FROM order_items i
JOIN products p ON p.product_id = i.product_id
WHERE i.order_id = ?
ORDER BY i.item_id
"""


OrderRow = tuple[str, str, int, str, str | None, str | None, str]


@dataclass(frozen=True)
class OrderLine:
    product_name: str
    quantity: int


@dataclass(frozen=True)
class OrderDetails:
    order_id: int
    customer_first_name: str
    order_date: date
    status: OrderStatus
    items: tuple[OrderLine, ...]
    total: Decimal
    payment_method: PaymentMethod
    tracking_code: str | None
    estimated_delivery: date | None
    days_late: int

    @property
    def is_late(self) -> bool:
        return self.days_late > 0


def find_verified_order(
    db_path: Path,
    order_id: int | None,
    contact: str | None,
    reference_date: datetime,
) -> OrderDetails | None:
    """Return the order only when contact matches the customer of that order.

    None covers an unknown order, a mismatch and missing input alike, so callers
    cannot tell the cases apart.
    """
    if order_id is None or contact is None:
        return None
    with closing(connect(db_path)) as connection:
        stored_contact = connection.execute(
            SELECT_ORDER_CONTACT, (order_id,)
        ).fetchone()
        if stored_contact is None:
            return None
        customer_phone, customer_email = stored_contact
        if not contact_matches(contact, customer_phone, customer_email):
            return None
        row = connection.execute(SELECT_ORDER, (order_id,)).fetchone()
        return _build_order_details(connection, order_id, row, reference_date)


def contact_matches(contact: str, customer_phone: str, customer_email: str) -> bool:
    if EMAIL_MARKER in contact:
        return normalize_email(contact) == customer_email
    typed_phone = strip_country_code(digits_only(contact))
    return bool(typed_phone) and typed_phone == customer_phone


def calculate_days_late(
    status: OrderStatus, estimated_delivery: date | None, reference_date: datetime
) -> int:
    if status is not OrderStatus.SHIPPED or estimated_delivery is None:
        return 0
    return max((reference_date.date() - estimated_delivery).days, 0)


def _build_order_details(
    connection: sqlite3.Connection,
    order_id: int,
    row: OrderRow,
    reference_date: datetime,
) -> OrderDetails:
    (
        order_date,
        status,
        total_cents,
        payment_method,
        tracking_code,
        estimated_delivery,
        customer_name,
    ) = row
    delivery_date = (
        None if estimated_delivery is None else date.fromisoformat(estimated_delivery)
    )
    order_status = OrderStatus(status)
    return OrderDetails(
        order_id=order_id,
        customer_first_name=customer_name.split()[0],
        order_date=date.fromisoformat(order_date),
        status=order_status,
        items=_select_order_lines(connection, order_id),
        total=from_cents(total_cents),
        payment_method=PaymentMethod(payment_method),
        tracking_code=tracking_code,
        estimated_delivery=delivery_date,
        days_late=calculate_days_late(order_status, delivery_date, reference_date),
    )


def _select_order_lines(
    connection: sqlite3.Connection, order_id: int
) -> tuple[OrderLine, ...]:
    rows = connection.execute(SELECT_ORDER_ITEMS, (order_id,)).fetchall()
    return tuple(OrderLine(product_name=name, quantity=quantity) for name, quantity in rows)
