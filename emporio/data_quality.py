import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from emporio.models import Order, OrderItem, PaymentMethod, Product, ProductStatus
from emporio.payments import (
    PIX_DISCOUNT_PERCENT,
    installment_value,
    is_installment_allowed,
    minimum_installment_value,
    pix_price,
)
from emporio.records import StoreRecords, load_store_records
from emporio.settings import DATA_DIR
from emporio.store import normalize_email, to_money

CREDIT_PAYMENT_PATTERN = re.compile(r"^credit_(\d+)x$")
NO_ANOMALIES_LINE = "  none"


@dataclass(frozen=True)
class OrderTotalMismatch:
    order_id: int
    recorded_total: Decimal
    list_price_total: Decimal


@dataclass(frozen=True)
class ComingSoonProductInOrder:
    order_id: int
    product_id: int
    product_name: str


@dataclass(frozen=True)
class PixWithoutDiscount:
    order_id: int
    recorded_total: Decimal
    list_price_total: Decimal
    expected_pix_total: Decimal


@dataclass(frozen=True)
class InstallmentBelowMinimum:
    order_id: int
    installments: int
    recorded_total: Decimal
    installment_value: Decimal
    minimum_installment: Decimal


@dataclass(frozen=True)
class SharedEmail:
    email: str
    customer_ids: tuple[int, ...]


@dataclass(frozen=True)
class EmptyCategory:
    category_id: int
    name: str


@dataclass(frozen=True)
class DataQualityReport:
    total_mismatches: tuple[OrderTotalMismatch, ...]
    coming_soon_in_orders: tuple[ComingSoonProductInOrder, ...]
    pix_without_discount: tuple[PixWithoutDiscount, ...]
    installments_below_minimum: tuple[InstallmentBelowMinimum, ...]
    shared_emails: tuple[SharedEmail, ...]
    empty_categories: tuple[EmptyCategory, ...]


def detect_anomalies(records: StoreRecords) -> DataQualityReport:
    return DataQualityReport(
        total_mismatches=find_total_mismatches(records),
        coming_soon_in_orders=find_coming_soon_in_orders(records),
        pix_without_discount=find_pix_without_discount(records),
        installments_below_minimum=find_installments_below_minimum(records),
        shared_emails=find_shared_emails(records),
        empty_categories=find_empty_categories(records),
    )


def find_total_mismatches(records: StoreRecords) -> tuple[OrderTotalMismatch, ...]:
    list_totals = _list_price_totals(records)
    return tuple(
        OrderTotalMismatch(order.order_id, order.total_brl, list_totals[order.order_id])
        for order in _sorted_orders(records)
        if order.total_brl != list_totals[order.order_id]
    )


def find_coming_soon_in_orders(
    records: StoreRecords,
) -> tuple[ComingSoonProductInOrder, ...]:
    products = _products_by_id(records)
    found = {
        (item.order_id, item.product_id)
        for item in records.order_items
        if _product_of(products, item).status is ProductStatus.COMING_SOON
    }
    return tuple(
        ComingSoonProductInOrder(order_id, product_id, products[product_id].name)
        for order_id, product_id in sorted(found)
    )


def find_pix_without_discount(records: StoreRecords) -> tuple[PixWithoutDiscount, ...]:
    """A PIX order is flagged when its recorded total is above the list-price total
    minus the PIX discount, whatever the reason (no discount, or only part of it).
    An order whose total also mismatches the items is reported by both detectors."""
    list_totals = _list_price_totals(records)
    flagged = []
    for order in _sorted_orders(records):
        if order.payment_method is not PaymentMethod.PIX:
            continue
        list_total = list_totals[order.order_id]
        expected = pix_price(list_total, has_active_promotion=False)
        if order.total_brl > expected:
            flagged.append(
                PixWithoutDiscount(order.order_id, order.total_brl, list_total, expected)
            )
    return tuple(flagged)


def find_installments_below_minimum(
    records: StoreRecords,
) -> tuple[InstallmentBelowMinimum, ...]:
    flagged = []
    for order in _sorted_orders(records):
        installments = _credit_installments(order.payment_method)
        if installments is None or is_installment_allowed(order.total_brl, installments):
            continue
        flagged.append(
            InstallmentBelowMinimum(
                order_id=order.order_id,
                installments=installments,
                recorded_total=order.total_brl,
                installment_value=installment_value(order.total_brl, installments),
                minimum_installment=minimum_installment_value(installments),
            )
        )
    return tuple(flagged)


def find_shared_emails(records: StoreRecords) -> tuple[SharedEmail, ...]:
    customers_by_email: defaultdict[str, list[int]] = defaultdict(list)
    for customer in records.customers:
        customers_by_email[normalize_email(customer.email)].append(customer.customer_id)
    return tuple(
        SharedEmail(email, tuple(sorted(customer_ids)))
        for email, customer_ids in sorted(customers_by_email.items())
        if len(customer_ids) > 1
    )


def find_empty_categories(records: StoreRecords) -> tuple[EmptyCategory, ...]:
    used_category_ids = {product.category_id for product in records.products}
    return tuple(
        EmptyCategory(category.category_id, category.name)
        for category in sorted(records.categories, key=lambda c: c.category_id)
        if category.category_id not in used_category_ids
    )


def format_report(report: DataQualityReport) -> str:
    sections = [
        _section(
            "Order totals that differ from the sum of item list prices",
            [
                f"  order {a.order_id}: recorded {_brl(a.recorded_total)}, "
                f"item list prices sum to {_brl(a.list_price_total)}"
                for a in report.total_mismatches
            ],
        ),
        _section(
            "Orders containing a coming-soon product",
            [
                f"  order {a.order_id}: product {a.product_id} ({a.product_name})"
                for a in report.coming_soon_in_orders
            ],
        ),
        _section(
            f"PIX orders recorded without the {PIX_DISCOUNT_PERCENT}% discount",
            [
                f"  order {a.order_id}: recorded {_brl(a.recorded_total)}, "
                f"list prices sum to {_brl(a.list_price_total)}, "
                f"expected with discount {_brl(a.expected_pix_total)}"
                for a in report.pix_without_discount
            ],
        ),
        _section(
            "Credit orders with an installment below the section 3.1 minimum",
            [
                f"  order {a.order_id}: {a.installments}x of {_brl(a.installment_value)} "
                f"(total {_brl(a.recorded_total)}), minimum {_brl(a.minimum_installment)}"
                for a in report.installments_below_minimum
            ],
        ),
        _section(
            "E-mails shared by more than one customer",
            [
                f"  {a.email}: customers {', '.join(str(i) for i in a.customer_ids)}"
                for a in report.shared_emails
            ],
        ),
        _section(
            "Categories with no products",
            [f"  category {a.category_id}: {a.name}" for a in report.empty_categories],
        ),
    ]
    return "\n\n".join(["Data quality report (records are not modified)", *sections])


def main() -> None:
    print(format_report(detect_anomalies(load_store_records(DATA_DIR))))


def _section(title: str, lines: list[str]) -> str:
    body = lines or [NO_ANOMALIES_LINE]
    return "\n".join([f"{title} ({len(lines)}):", *body])


def _brl(amount: Decimal) -> str:
    return f"R$ {to_money(amount)}"


def _sorted_orders(records: StoreRecords) -> list[Order]:
    return sorted(records.orders, key=lambda order: order.order_id)


def _products_by_id(records: StoreRecords) -> dict[int, Product]:
    return {product.product_id: product for product in records.products}


def _product_of(products: dict[int, Product], item: OrderItem) -> Product:
    product = products.get(item.product_id)
    if product is None:
        raise ValueError(
            f"Order {item.order_id} references unknown product {item.product_id}."
        )
    return product


def _credit_installments(method: PaymentMethod) -> int | None:
    match = CREDIT_PAYMENT_PATTERN.match(method.value)
    if match is None:
        return None
    return int(match.group(1))


def _list_price_totals(records: StoreRecords) -> dict[int, Decimal]:
    """order_items carries no unit price, so the item total is the product's current
    list price times the quantity."""
    products = _products_by_id(records)
    totals: dict[int, Decimal] = {order.order_id: Decimal(0) for order in records.orders}
    for item in records.order_items:
        totals[item.order_id] += _product_of(products, item).price_brl * item.quantity
    return totals


if __name__ == "__main__":
    main()
