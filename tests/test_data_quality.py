from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from emporio import seed
from emporio.data_quality import (
    detect_anomalies,
    find_coming_soon_in_orders,
    find_empty_categories,
    find_installments_below_minimum,
    find_pix_without_discount,
    find_shared_emails,
    find_total_mismatches,
    format_report,
)
from emporio.models import (
    Category,
    Customer,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    Product,
    ProductStatus,
)
from emporio.records import StoreRecords, load_store_records
from emporio.seed import seed_store
from emporio.settings import DATA_DIR

PRODUCT_PRICE = Decimal("1000.00")
ORDER_DATE = date(2026, 1, 1)


@pytest.fixture(scope="module")
def real_records() -> StoreRecords:
    return load_store_records(DATA_DIR)


def make_product(
    product_id: int = 1,
    price: Decimal = PRODUCT_PRICE,
    status: ProductStatus = ProductStatus.ACTIVE,
    stock: int = 5,
    category_id: int = 1,
) -> Product:
    return Product(
        product_id=product_id,
        price_brl=price,
        name=f"Product {product_id}",
        category_id=category_id,
        description="",
        stock_quantity=stock,
        status=status,
        specs={},
        created_at=ORDER_DATE,
    )


def make_order(
    order_id: int = 1,
    total: Decimal = PRODUCT_PRICE,
    method: PaymentMethod = PaymentMethod.BOLETO,
) -> Order:
    return Order(
        order_id=order_id,
        customer_id=1,
        order_date=ORDER_DATE,
        status=OrderStatus.CONFIRMED,
        total_brl=total,
        payment_method=method,
        tracking_code=None,
        estimated_delivery=None,
        notes=None,
    )


def make_customer(customer_id: int, email: str) -> Customer:
    return Customer(
        customer_id=customer_id,
        name=f"Customer {customer_id}",
        phone="67999990000",
        email=email,
        city="Campo Grande",
    )


def make_records(
    products: list[Product] | None = None,
    orders: list[Order] | None = None,
    order_items: list[OrderItem] | None = None,
    customers: list[Customer] | None = None,
    categories: list[Category] | None = None,
) -> StoreRecords:
    return StoreRecords(
        categories=categories or [],
        products=products or [make_product()],
        promotions=[],
        customers=customers or [],
        orders=orders or [],
        order_items=order_items or [],
    )


def single_item(order_id: int, product_id: int = 1, quantity: int = 1) -> OrderItem:
    return OrderItem(order_id=order_id, product_id=product_id, quantity=quantity)


def test_real_data_total_mismatches(real_records: StoreRecords):
    mismatches = find_total_mismatches(real_records)

    assert [(m.order_id, m.recorded_total, m.list_price_total) for m in mismatches] == [
        (3, Decimal("3450"), Decimal("3498")),
        (20, Decimal("1400"), Decimal("1488")),
    ]


def test_real_data_coming_soon_products_in_orders(real_records: StoreRecords):
    found = find_coming_soon_in_orders(real_records)

    assert [(a.order_id, a.product_id) for a in found] == [(3, 130), (14, 130)]


def test_real_data_pix_orders_without_discount(real_records: StoreRecords):
    found = find_pix_without_discount(real_records)

    assert [a.order_id for a in found] == [1, 5, 10, 13, 17]
    assert all(a.recorded_total == a.list_price_total for a in found)


def test_real_data_installments_below_minimum(real_records: StoreRecords):
    found = find_installments_below_minimum(real_records)

    assert [(a.order_id, a.installments) for a in found] == [(9, 6), (16, 6), (18, 12)]


def test_real_data_shared_emails(real_records: StoreRecords):
    found = find_shared_emails(real_records)

    assert [(a.email, a.customer_ids) for a in found] == [
        ("bruno.martins@jmail.com", (11, 43))
    ]


def test_real_data_empty_categories(real_records: StoreRecords):
    found = find_empty_categories(real_records)

    assert [a.category_id for a in found] == [6, 7, 8]


def test_detect_anomalies_combines_every_detector(real_records: StoreRecords):
    report = detect_anomalies(real_records)

    assert report.total_mismatches == find_total_mismatches(real_records)
    assert report.coming_soon_in_orders == find_coming_soon_in_orders(real_records)
    assert report.pix_without_discount == find_pix_without_discount(real_records)
    assert report.installments_below_minimum == find_installments_below_minimum(
        real_records
    )
    assert report.shared_emails == find_shared_emails(real_records)
    assert report.empty_categories == find_empty_categories(real_records)


def test_total_matching_quantity_times_list_price_is_not_flagged():
    records = make_records(
        orders=[make_order(total=Decimal("3000.00"))],
        order_items=[single_item(1, quantity=3)],
    )

    assert find_total_mismatches(records) == ()


def test_total_differing_by_one_cent_is_flagged():
    records = make_records(
        orders=[make_order(total=Decimal("999.99"))], order_items=[single_item(1)]
    )

    assert [m.order_id for m in find_total_mismatches(records)] == [1]


def test_coming_soon_product_in_order_is_flagged():
    records = make_records(
        products=[make_product(1, status=ProductStatus.COMING_SOON)],
        orders=[make_order()],
        order_items=[single_item(1)],
    )

    assert [(a.order_id, a.product_id) for a in find_coming_soon_in_orders(records)] == [
        (1, 1)
    ]


def test_out_of_stock_product_in_order_is_not_flagged():
    records = make_records(
        products=[make_product(1, stock=0)],
        orders=[make_order()],
        order_items=[single_item(1)],
    )

    assert find_coming_soon_in_orders(records) == ()


def test_discontinued_product_in_order_is_not_flagged():
    records = make_records(
        products=[make_product(1, status=ProductStatus.DISCONTINUED)],
        orders=[make_order()],
        order_items=[single_item(1)],
    )

    assert find_coming_soon_in_orders(records) == ()


def test_pix_order_at_list_price_is_flagged_with_the_expected_total():
    records = make_records(
        orders=[make_order(total=PRODUCT_PRICE, method=PaymentMethod.PIX)],
        order_items=[single_item(1)],
    )

    (found,) = find_pix_without_discount(records)

    assert found.expected_pix_total == Decimal("950.00")


def test_pix_order_with_the_discount_is_not_flagged():
    records = make_records(
        orders=[make_order(total=Decimal("950.00"), method=PaymentMethod.PIX)],
        order_items=[single_item(1)],
    )

    assert find_pix_without_discount(records) == ()


def test_pix_order_with_a_partial_discount_is_flagged():
    records = make_records(
        orders=[make_order(total=Decimal("960.00"), method=PaymentMethod.PIX)],
        order_items=[single_item(1)],
    )

    assert [a.order_id for a in find_pix_without_discount(records)] == [1]


def test_non_pix_order_at_list_price_is_not_flagged_as_pix():
    records = make_records(
        orders=[make_order(total=PRODUCT_PRICE, method=PaymentMethod.BOLETO)],
        order_items=[single_item(1)],
    )

    assert find_pix_without_discount(records) == ()


def test_pix_order_with_mismatching_total_is_reported_by_both_detectors():
    records = make_records(
        orders=[make_order(total=Decimal("1100.00"), method=PaymentMethod.PIX)],
        order_items=[single_item(1)],
    )

    assert [m.order_id for m in find_total_mismatches(records)] == [1]
    assert [a.order_id for a in find_pix_without_discount(records)] == [1]


@pytest.mark.parametrize(
    ("method", "total", "flagged"),
    [
        (PaymentMethod.CREDIT_3X, Decimal("149.99"), True),
        (PaymentMethod.CREDIT_3X, Decimal("150.00"), False),
        (PaymentMethod.CREDIT_6X, Decimal("479.99"), True),
        (PaymentMethod.CREDIT_6X, Decimal("480.00"), False),
        (PaymentMethod.CREDIT_12X, Decimal("1199.99"), True),
        (PaymentMethod.CREDIT_12X, Decimal("1200.00"), False),
        (PaymentMethod.DEBIT, Decimal("10.00"), False),
        (PaymentMethod.BOLETO, Decimal("10.00"), False),
        (PaymentMethod.PIX, Decimal("10.00"), False),
    ],
)
def test_installment_minimum_boundary(
    method: PaymentMethod, total: Decimal, flagged: bool
):
    records = make_records(orders=[make_order(total=total, method=method)])

    assert bool(find_installments_below_minimum(records)) is flagged


def test_installment_anomaly_carries_the_value_and_the_minimum():
    records = make_records(
        orders=[make_order(total=Decimal("349.90"), method=PaymentMethod.CREDIT_6X)]
    )

    (found,) = find_installments_below_minimum(records)

    assert (found.installments, found.installment_value, found.minimum_installment) == (
        6,
        Decimal("58.32"),
        Decimal("80.00"),
    )


def test_emails_differing_only_by_case_count_as_shared():
    records = make_records(
        customers=[
            make_customer(1, "Same@Example.com"),
            make_customer(2, "same@example.com"),
            make_customer(3, "other@example.com"),
        ]
    )

    assert [(a.email, a.customer_ids) for a in find_shared_emails(records)] == [
        ("same@example.com", (1, 2))
    ]


def test_distinct_emails_are_not_flagged():
    records = make_records(
        customers=[make_customer(1, "a@example.com"), make_customer(2, "b@example.com")]
    )

    assert find_shared_emails(records) == ()


def test_category_without_products_is_flagged_and_one_with_products_is_not():
    records = make_records(
        products=[make_product(1, category_id=1)],
        categories=[
            Category(category_id=1, name="Used", description=""),
            Category(category_id=2, name="Empty", description=""),
        ],
    )

    assert [(a.category_id, a.name) for a in find_empty_categories(records)] == [
        (2, "Empty")
    ]


def test_order_item_with_unknown_product_fails_loudly():
    records = make_records(orders=[make_order()], order_items=[single_item(1, 999)])

    with pytest.raises(ValueError, match="unknown product 999"):
        find_total_mismatches(records)


def test_report_groups_anomalies_by_kind_with_ids_and_numbers(real_records: StoreRecords):
    text = format_report(detect_anomalies(real_records))

    assert "Order totals that differ from the sum of item list prices (2):" in text
    assert "order 3: recorded R$ 3450.00, item list prices sum to R$ 3498.00" in text
    assert "order 14: product 130" in text
    assert "order 9: 6x of R$ 58.32 (total R$ 349.90), minimum R$ 80.00" in text
    assert "bruno.martins@jmail.com: customers 11, 43" in text
    assert "category 8: Cordas Orquestrais" in text


def test_report_of_clean_data_says_none():
    text = format_report(detect_anomalies(make_records()))

    assert text.count("(0):") == 6
    assert "  none" in text


def test_seed_main_prints_the_report_without_touching_the_real_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    db_path = tmp_path / "store.db"
    monkeypatch.setattr(seed, "STORE_DB_PATH", db_path)
    monkeypatch.setattr(
        seed, "seed_store", lambda: seed_store(db_path, DATA_DIR)
    )

    seed.main()

    output = capsys.readouterr().out
    assert db_path.exists()
    assert "Data quality report" in output
    assert "order 20: recorded R$ 1400.00" in output
