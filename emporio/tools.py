from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, ToolException, tool

from emporio.models import OrderStatus, PaymentMethod
from emporio.orders import OrderDetails, find_verified_order
from emporio.store import ProductPrice, find_products

THOUSANDS_SEPARATOR = "."
DECIMAL_SEPARATOR = ","
DATE_FORMAT = "%d/%m/%Y"

ORDER_STATUS_LABELS = {
    OrderStatus.PENDING: "pendente",
    OrderStatus.CONFIRMED: "confirmado",
    OrderStatus.SHIPPED: "enviado",
    OrderStatus.DELIVERED: "entregue",
    OrderStatus.CANCELLED: "cancelado",
}
PAYMENT_METHOD_LABELS = {
    PaymentMethod.PIX: "Pix",
    PaymentMethod.BOLETO: "boleto",
    PaymentMethod.DEBIT: "cartão de débito",
    PaymentMethod.CREDIT_3X: "cartão de crédito em até 3x",
    PaymentMethod.CREDIT_6X: "cartão de crédito em até 6x",
    PaymentMethod.CREDIT_12X: "cartão de crédito em até 12x",
}
IDENTITY_CHECK_FAILED_MESSAGE = (
    "Não foi possível confirmar o pedido com os dados informados."
)


def format_brl(amount: Decimal) -> str:
    us_formatted = f"{amount:,.2f}"
    swapped = us_formatted.replace(",", "\0").replace(".", DECIMAL_SEPARATOR)
    return "R$ " + swapped.replace("\0", THOUSANDS_SEPARATOR)


def product_price_payload(product: ProductPrice) -> dict[str, Any]:
    promotion = product.active_promotion
    return {
        "product_id": product.product_id,
        "name": product.name,
        "original_price": format_brl(product.original_price),
        "active_promotion": None
        if promotion is None
        else {
            "description": promotion.description,
            "discount_percent": promotion.discount_percent,
        },
        "final_price": format_brl(product.final_price),
    }


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def order_payload(order: OrderDetails) -> dict[str, Any]:
    return {
        "verified": True,
        "order": {
            "order_id": order.order_id,
            "customer_first_name": order.customer_first_name,
            "status": ORDER_STATUS_LABELS[order.status],
            "order_date": format_date(order.order_date),
            "items": [
                {"product_name": line.product_name, "quantity": line.quantity}
                for line in order.items
            ],
            "order_total": format_brl(order.total),
            "payment_method": PAYMENT_METHOD_LABELS[order.payment_method],
            "tracking_code": order.tracking_code,
            "estimated_delivery": None
            if order.estimated_delivery is None
            else format_date(order.estimated_delivery),
            "is_late": order.is_late,
            "days_late": order.days_late,
        },
    }


def identity_check_failed_payload() -> dict[str, Any]:
    return {"verified": False, "message": IDENTITY_CHECK_FAILED_MESSAGE}


def build_tools(store_db_path: Path, reference_date: datetime) -> list[BaseTool]:
    @tool
    def find_product(product_id: int | None = None, name: str | None = None) -> dict[str, Any]:
        """Look up the price of a product in the store catalog.

        Provide either product_id or name. The name may be partial and is matched
        ignoring case and accents (e.g. "takamine gd20"). Returns up to 5 matching
        products, each with original_price, active_promotion (null when there is
        none) and final_price, which is what the customer pays. An empty list means
        no product matched.
        """
        try:
            products = find_products(store_db_path, product_id=product_id, name=name)
        except ValueError as error:
            raise ToolException(str(error)) from error
        return {"products": [product_price_payload(p) for p in products]}

    @tool
    def get_order(order_id: int | None = None, contact: str | None = None) -> dict[str, Any]:
        """Look up an order after the Identity Check.

        Both order_id (the order number) and contact (the customer's e-mail or phone,
        exactly as the customer typed it) are required; the contact is checked only
        against the customer who placed that order. Returns verified true with the
        order details (status, order date, items, order total, payment method,
        tracking code, estimated delivery, is_late and days_late) when the check
        passes. Returns verified false with a generic message when it fails, whether
        the order does not exist, the contact does not match or an input is missing;
        the failure never says which.
        """
        order = find_verified_order(store_db_path, order_id, contact, reference_date)
        if order is None:
            return identity_check_failed_payload()
        return order_payload(order)

    find_product.handle_tool_error = True
    return [find_product, get_order]
