from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, ToolException, tool

from emporio.store import ProductPrice, find_products

THOUSANDS_SEPARATOR = "."
DECIMAL_SEPARATOR = ","


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


def build_tools(store_db_path: Path) -> list[BaseTool]:
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

    find_product.handle_tool_error = True
    return [find_product]
