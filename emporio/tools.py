from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, ToolException, tool

from emporio.catalog import (
    CatalogProduct,
    CatalogSearchResult,
    ProductLookup,
    UnknownCategoryError,
    list_active_promotions,
    lookup_products,
    search_products,
)
from emporio.eligibility import CountsFrom, Right, RightEligibility
from emporio.escalations import record_escalation
from emporio.models import Availability, OrderStatus, PaymentMethod
from emporio.orders import OrderDetails, find_verified_order
from emporio.store import ProductPrice
from emporio.store_hours import describe_store_status, format_moment, get_store_status

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
AVAILABILITY_LABELS = {
    Availability.AVAILABLE: "disponível",
    Availability.OUT_OF_STOCK: "esgotado no momento",
    Availability.DISCONTINUED: "fora de linha (descontinuado)",
    Availability.COMING_SOON: "em breve (sem data de lançamento)",
}
RIGHT_LABELS = {
    Right.WITHDRAWAL: "Direito de arrependimento (devolução)",
    Right.PREFERENCE_EXCHANGE: "Troca por preferência",
    Right.DEFECT_EXCHANGE: "Troca por defeito de fabricação",
    Right.LEGAL_WARRANTY: "Garantia legal (90 dias)",
}
COUNTS_FROM_LABELS = {
    CountsFrom.RECEIPT_DATE: "data de recebimento (data estimada de entrega)",
    CountsFrom.ORDER_DATE: "data do pedido",
}
DEFECT_EXCHANGE_EXPIRED_NOTE = (
    "Depois do prazo, defeitos de fabricação passam pela garantia do fabricante; a "
    "loja pode intermediar o processo se o cliente pedir."
)
NOT_DELIVERED_AFTER_SALES_MESSAGE = (
    "Pedido ainda não entregue: os prazos de arrependimento, troca e garantia "
    "começam a contar na data de recebimento."
)
CANCELLED_AFTER_SALES_MESSAGE = (
    "Pedido cancelado: não há direito de arrependimento, troca ou garantia a exercer."
)
ESCALATION_RESPONSE_TIME = "24 horas úteis"
UNKNOWN_CATEGORY_MESSAGE = (
    "Nenhuma categoria da loja corresponde a {wording!r}. Use uma das categorias de "
    "valid_categories ou busque pelo nome com find_product."
)
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


def catalog_product_payload(product: CatalogProduct) -> dict[str, Any]:
    return {**product_price_payload(product.price), "category": product.category}


def product_lookup_payload(lookup: ProductLookup) -> dict[str, Any]:
    ended = lookup.ended_promotion
    payload = {
        **product_price_payload(lookup.price),
        "availability": lookup.availability.value,
        "availability_label": AVAILABILITY_LABELS[lookup.availability],
        "ended_promotion": None
        if ended is None
        else {"description": ended.description, "discount_percent": ended.discount_percent},
    }
    if lookup.alternatives is None:
        return payload
    return {
        **payload,
        "alternatives": [catalog_product_payload(p) for p in lookup.alternatives.products],
        "alternatives_in_price_range": lookup.alternatives.in_price_range,
    }


def promotions_payload(result: CatalogSearchResult) -> dict[str, Any]:
    return {
        "category": result.category,
        "promotions": [catalog_product_payload(p) for p in result.products],
        "total": result.total_matches,
    }


def catalog_search_payload(result: CatalogSearchResult) -> dict[str, Any]:
    return {
        "category": result.category,
        "products": [catalog_product_payload(p) for p in result.products],
        "total_matches": result.total_matches,
        "returned": len(result.products),
        "has_more": result.total_matches > len(result.products),
    }


def unknown_category_payload(error: UnknownCategoryError) -> dict[str, Any]:
    return {
        "category_recognized": False,
        "message": UNKNOWN_CATEGORY_MESSAGE.format(wording=error.wording),
        "valid_categories": error.valid_categories,
    }


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def right_payload(eligibility: RightEligibility) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "right": RIGHT_LABELS[eligibility.right],
        "counts_from": COUNTS_FROM_LABELS[eligibility.counts_from],
        "deadline": format_date(eligibility.deadline),
        "is_open": eligibility.is_open,
    }
    if eligibility.is_open:
        payload["days_remaining"] = eligibility.days_remaining
    else:
        payload["days_since_deadline"] = eligibility.days_since_deadline
        if eligibility.right is Right.DEFECT_EXCHANGE:
            payload["note"] = DEFECT_EXCHANGE_EXPIRED_NOTE
    return payload


def after_sales_payload(order: OrderDetails) -> dict[str, Any]:
    if order.status is OrderStatus.DELIVERED:
        return {
            "receipt_date": None
            if order.estimated_delivery is None
            else format_date(order.estimated_delivery),
            "rights": [right_payload(eligibility) for eligibility in order.rights],
        }
    message = (
        CANCELLED_AFTER_SALES_MESSAGE
        if order.status is OrderStatus.CANCELLED
        else NOT_DELIVERED_AFTER_SALES_MESSAGE
    )
    return {"message": message}


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
            "after_sales": after_sales_payload(order),
        },
    }


def identity_check_failed_payload() -> dict[str, Any]:
    return {"verified": False, "message": IDENTITY_CHECK_FAILED_MESSAGE}


def escalation_payload(reason: str, reference_date: datetime) -> dict[str, Any]:
    status = get_store_status(reference_date)
    return {
        "recorded": True,
        "reason": reason,
        "response_time": ESCALATION_RESPONSE_TIME,
        "store_is_open": status.is_open,
        "team_back_at": None
        if status.next_opening is None
        else format_moment(status.next_opening),
        "store_status": describe_store_status(reference_date),
    }


def build_tools(
    store_db_path: Path, escalation_log_path: Path, reference_date: datetime
) -> list[BaseTool]:
    @tool
    def find_product(product_id: int | None = None, name: str | None = None) -> dict[str, Any]:
        """Look up one product in the store catalog: price, availability and promotions.

        Provide either product_id or name. Pass only brand and model as the name
        (e.g. "takamine gd20", "kala ka-abp-ctg"), not the instrument type: it is
        matched as a substring ignoring case and accents. Returns up to 5 matching
        products, each with original_price, active_promotion (null when there is
        none) and final_price, which is what the customer pays. An empty list means
        no product matched.

        availability is one of available, out_of_stock, discontinued or coming_soon
        (availability_label has the Portuguese wording); only available products can
        be bought. coming_soon has no release date. When the product has no active
        promotion but had one that ended, ended_promotion has its description and
        discount_percent; it is no longer valid and final_price already ignores it.
        For a product that is not available, alternatives lists up to 3 available
        products of the same category (same fields as search_catalog results), the
        nearest in price first. alternatives_in_price_range is true when they are
        within 30% of the product's price; when false, none costs about the same and
        these are just the closest-priced options of the category. An empty
        alternatives list means the category has no available product.
        """
        try:
            lookups = lookup_products(store_db_path, product_id=product_id, name=name)
        except ValueError as error:
            raise ToolException(str(error)) from error
        return {"products": [product_lookup_payload(lookup) for lookup in lookups]}

    @tool
    def search_catalog(
        category: str | None = None,
        max_price: float | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        """Browse the catalog with filters; use it for open questions such as "quais
        violões até R$ 1000?" or "tem ukulele?". For the price of one specific product
        use find_product instead.

        At least one filter is required. category is the customer's wording ("violão",
        "violões", "ukulele", "guitarra", "teclado", "sax"...), matched ignoring case
        and accents; the result echoes the store category it resolved to. If the
        wording matches no store category the result has category_recognized false and
        the list valid_categories. max_price is a positive number in reais (1000 for
        R$ 1.000,00) and is compared with the final_price, so promotions count. text
        narrows by words that must all appear in the product name or description.
        Only products for sale right now are returned (stock is not shown). Each
        product has original_price, active_promotion (null when there is none) and
        final_price, which is what the customer pays, sorted by final_price ascending.
        The list is capped: total_matches is the full count, returned is how many are
        listed and has_more is true when there are others. An empty products list means
        nothing is available right now with those filters; with only a category it
        means the store has nothing available in that category.
        """
        try:
            result = search_products(
                store_db_path,
                category=category,
                max_price=None if max_price is None else Decimal(str(max_price)),
                text=text,
            )
        except UnknownCategoryError as error:
            return unknown_category_payload(error)
        except ValueError as error:
            raise ToolException(str(error)) from error
        return catalog_search_payload(result)

    @tool
    def list_promotions(category: str | None = None) -> dict[str, Any]:
        """List the active promotions, the answer to "o que está em promoção?".

        Only products for sale right now with an active promotion are listed, ordered
        by discount_percent (highest first). Each has original_price,
        active_promotion (description and discount_percent) and final_price, which is
        what the customer pays. category is optional, in the customer's wording
        ("violão", "ukulele"...), same matching as search_catalog; if it matches no
        store category the result has category_recognized false and valid_categories.
        total is how many promotions are listed; an empty list means there is no
        active promotion (in that category, when one was given).
        """
        try:
            result = list_active_promotions(store_db_path, category=category)
        except UnknownCategoryError as error:
            return unknown_category_payload(error)
        return promotions_payload(result)

    @tool
    def get_order(order_id: int | None = None, contact: str | None = None) -> dict[str, Any]:
        """Look up an order after the Identity Check.

        Both order_id (the order number) and contact (the customer's e-mail or phone,
        exactly as the customer typed it) are required; the contact is checked only
        against the customer who placed that order. Returns verified true with the
        order details (status, order date, items, order total, payment method,
        tracking code, estimated delivery, is_late and days_late) when the check
        passes, plus after_sales: for delivered orders the receipt date and, for each
        right (withdrawal, preference exchange, defect exchange, legal warranty),
        whether it is still open, its deadline and the days remaining or elapsed;
        for other orders a message about the windows. Returns verified false with a generic message when it fails, whether
        the order does not exist, the contact does not match or an input is missing;
        the failure never says which.
        """
        order = find_verified_order(store_db_path, order_id, contact, reference_date)
        if order is None:
            return identity_check_failed_payload()
        return order_payload(order)

    @tool
    def escalate_to_team(
        reason: str, summary: str, order_id: int | None = None
    ) -> dict[str, Any]:
        """Record an escalation so the human team follows up with the customer.

        This only records the case; it does not resolve, cancel, refund or change
        anything, and it returns no order data. reason must be one of:
        - complaint: the customer complains about a product, delivery or service.
        - cancellation_request: the customer wants to cancel a pending or confirmed
          order (the store has no cancellation policy, so nothing can be promised).
        - policy_doubt: a question the store manual does not answer or a doubt about
          how a policy applies; the team decides.
        - late_order: a shipped order that get_order flagged with is_late true.
        - other: any other case Lia cannot or must not resolve alone.
        summary is a short, factual note in Portuguese written from the
        conversation, without the customer's e-mail or phone. order_id is the order
        number, only after get_order returned verified true for it; omit it for
        cases without an order. Returns recorded true with the response time
        (response_time), whether the store is open (store_is_open) and, when it is
        closed, when the team is back (team_back_at).
        """
        try:
            record = record_escalation(
                escalation_log_path, reason, summary, order_id, reference_date
            )
        except ValueError as error:
            raise ToolException(str(error)) from error
        return escalation_payload(record.reason.value, reference_date)

    find_product.handle_tool_error = True
    search_catalog.handle_tool_error = True
    list_promotions.handle_tool_error = True
    escalate_to_team.handle_tool_error = True
    return [find_product, search_catalog, list_promotions, get_order, escalate_to_team]
