from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from emporio.store import PERCENT_DENOMINATOR, to_money

PIX_DISCOUNT_PERCENT = 5
MAX_INSTALLMENTS = 12


@dataclass(frozen=True)
class InstallmentTier:
    max_installments: int
    minimum_installment: Decimal


# Policy section 3.1, which wins over the summary table in section 3. Tiers are
# ordered by max_installments; a number of installments belongs to the first tier
# that covers it.
INSTALLMENT_TIERS = (
    InstallmentTier(max_installments=3, minimum_installment=Decimal("50.00")),
    InstallmentTier(max_installments=6, minimum_installment=Decimal("80.00")),
    InstallmentTier(max_installments=MAX_INSTALLMENTS, minimum_installment=Decimal("100.00")),
)


class InstallmentRefusal(StrEnum):
    ABOVE_MAXIMUM = "above_maximum_installments"
    BELOW_MINIMUM = "below_minimum_installment"


@dataclass(frozen=True)
class InstallmentCheck:
    installments: int
    allowed: bool
    # Present only when allowed.
    installment_value: Decimal | None
    # Present only when the refusal is BELOW_MINIMUM.
    minimum_installment: Decimal | None
    refusal: InstallmentRefusal | None


def pix_price(final_price: Decimal, has_active_promotion: bool) -> Decimal:
    if has_active_promotion:
        return final_price
    discount_factor = (PERCENT_DENOMINATOR - PIX_DISCOUNT_PERCENT) / PERCENT_DENOMINATOR
    return to_money(final_price * discount_factor)


def installment_value(total: Decimal, installments: int) -> Decimal:
    require_positive_installments(installments)
    return to_money(total / installments)


def minimum_installment_value(installments: int) -> Decimal:
    require_positive_installments(installments)
    for tier in INSTALLMENT_TIERS:
        if installments <= tier.max_installments:
            return tier.minimum_installment
    raise ValueError(
        f"Installments cannot exceed {MAX_INSTALLMENTS}; got {installments}."
    )


def is_installment_allowed(total: Decimal, installments: int) -> bool:
    require_positive_installments(installments)
    if installments > MAX_INSTALLMENTS:
        return False
    if installments == 1:
        return True
    # Compared on the exact total, not on the rounded installment value, so a total
    # one cent short of the minimum is refused even if it rounds up to it.
    return total >= installments * minimum_installment_value(installments)


def max_installments(total: Decimal) -> int:
    # Allowed counts are a prefix of 1..MAX_INSTALLMENTS because the minimum per
    # installment never decreases as the count grows.
    for installments in range(MAX_INSTALLMENTS, 1, -1):
        if is_installment_allowed(total, installments):
            return installments
    return 1


def check_installments(total: Decimal, installments: int) -> InstallmentCheck:
    require_positive_installments(installments)
    if installments > MAX_INSTALLMENTS:
        return InstallmentCheck(
            installments=installments,
            allowed=False,
            installment_value=None,
            minimum_installment=None,
            refusal=InstallmentRefusal.ABOVE_MAXIMUM,
        )
    if not is_installment_allowed(total, installments):
        return InstallmentCheck(
            installments=installments,
            allowed=False,
            installment_value=None,
            minimum_installment=minimum_installment_value(installments),
            refusal=InstallmentRefusal.BELOW_MINIMUM,
        )
    return InstallmentCheck(
        installments=installments,
        allowed=True,
        installment_value=installment_value(total, installments),
        minimum_installment=None,
        refusal=None,
    )


def to_amount(value: float) -> Decimal:
    raw = Decimal(str(value))
    if not raw.is_finite():
        raise ValueError("amount must be a positive number of reais.")
    amount = to_money(raw)
    if amount <= 0:
        raise ValueError("amount must be a positive number of reais.")
    return amount


def require_positive_installments(installments: int) -> None:
    if installments < 1:
        raise ValueError(f"Installments must be at least 1; got {installments}.")
