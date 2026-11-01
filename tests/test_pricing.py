"""E2 test table. Expected values come from specs/epics/E2_DOMAIN_RULES.md and the real
products in specs/02_DATA_FINDINGS.md section 4."""

from __future__ import annotations

from decimal import Decimal

import pytest

from emporio import pricing
from emporio.pricing import (
    InvalidArgumentsError,
    NotForSaleError,
    Product,
    format_brl,
    quote,
    round_brl,
)


def product(
    price: str,
    availability: str = "available",
    promo: int | None = None,
    product_id: int = 95,
    name: str = "Takamine GD20 Dreadnought Natural",
) -> Product:
    return Product(
        product_id=product_id,
        name=name,
        price_brl=Decimal(price),
        availability=availability,
        promo_percent=promo,
    )


# --------------------------------------------------------------------------- rounding


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2089.0500", "2089.05"),
        ("1967.180", "1967.18"),
        # Half-up, not banker's rounding: a till always rounds .005 up.
        ("0.005", "0.01"),
        ("2.675", "2.68"),
        (183.2499999, "183.25"),
    ],
)
def test_round_brl_is_half_up(raw, expected) -> None:
    assert round_brl(raw) == Decimal(expected)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2089.05", "R$ 2.089,05"),
        ("439.20", "R$ 439,20"),
        ("35", "R$ 35,00"),
        ("11499", "R$ 11.499,00"),
        ("0", "R$ 0,00"),
    ],
)
def test_format_brl(value, expected) -> None:
    assert format_brl(value) == expected


# --------------------------------------------------------------------- promotion price


@pytest.mark.parametrize(
    ("price", "percent", "expected"),
    [
        # The four active promotions of 02_DATA_FINDINGS section 4.
        ("2399.00", 18, "1967.18"),  # 90  Crafter HT-100
        ("5999.00", 8, "5519.08"),  # 94  Taylor 110e
        ("549.00", 20, "439.20"),  # 121 Ohana CK-20
        ("359.00", 10, "323.10"),  # 127 Kalani KAL-700T
    ],
)
def test_effective_price_applies_the_promotion(price, percent, expected) -> None:
    assert pricing.effective_price(product(price, promo=percent)) == Decimal(expected)


def test_no_promotion_means_list_price() -> None:
    """Takamine GD20 has a 12% promotion row, but it is inactive (02 section 4)."""
    assert pricing.effective_price(product("2199.00")) == Decimal("2199.00")


@pytest.mark.parametrize("availability", ["coming_soon", "discontinued"])
def test_promotion_never_applies_to_non_sellable_products(availability) -> None:
    """DECISIONS D9: product 113 carries a promotion row and is discontinued."""
    assert pricing.promo_for(product("749.00", availability, promo=15)) is None


# ----------------------------------------------------------------------------- pix rule


def test_pix_takes_five_percent_off_the_list_price() -> None:
    """E2 test table: GD20 2199.00 in PIX -> 2089.05."""
    q = quote(product("2199.00"), "pix")
    assert q.pix_discount == Decimal("109.95")
    assert q.final_total == Decimal("2089.05")


def test_pix_does_not_stack_on_a_promotion() -> None:
    """Manual 6.2. E2 test table: 549.00 at 20% in PIX stays 439.20."""
    q = quote(product("549.00", promo=20), "pix")
    assert q.pix_discount == Decimal("0.00")
    assert q.final_total == Decimal("439.20")
    assert any("não é cumulativo" in note for note in q.notes)


@pytest.mark.parametrize("method", ["debit", "boleto"])
def test_debit_and_boleto_pay_the_effective_price(method) -> None:
    q = quote(product("2199.00"), method, quantity=2)
    assert q.final_total == Decimal("4398.00")
    assert q.pix_discount == Decimal("0.00")


def test_boleto_carries_the_clearing_note() -> None:
    q = quote(product("2199.00"), "boleto")
    assert any("3 dias úteis" in note for note in q.notes)


def test_promotion_shows_the_original_price() -> None:
    """Manual 6.2 requires the original price to be presented together with the discount."""
    q = quote(product("549.00", promo=20), "debit")
    assert q.unit_price == Decimal("549.00")
    assert q.promo is not None and q.promo.percent == 20
    assert any("549,00" in note for note in q.notes)


# ------------------------------------------------------------------------- installments


@pytest.mark.parametrize(
    ("price", "n", "allowed", "value"),
    [
        ("2199.00", 12, True, "183.25"),  # GD20 in 12x
        ("1200.00", 12, True, "100.00"),  # exactly on the 7-12x minimum
        ("349.90", 6, False, "58.32"),  # 58.32 < 80
        ("429.90", 6, False, "71.65"),  # order 16 of the real data
        ("120.00", 3, False, "40.00"),  # 40 < 50
        ("150.00", 3, True, "50.00"),  # exactly on the 1-3x minimum
        ("2199.00", 1, True, "2199.00"),  # 1x is always allowed
        ("10.00", 1, True, "10.00"),  # even below the tier minimum
    ],
)
def test_installment_tiers(price, n, allowed, value) -> None:
    q = quote(product(price), "credit", installments=n)
    assert q.installments is not None
    assert q.installments.allowed is allowed
    assert q.installments.value == Decimal(value)
    if not allowed:
        assert q.installments.reason is not None


@pytest.mark.parametrize(
    ("price", "expected_max"),
    [
        ("349.90", 4),  # passes at 4x (87.48) but fails at 5x (69.98)
        ("120.00", 2),
        ("1200.00", 12),
        ("2199.00", 12),
        ("30.00", 1),
    ],
)
def test_max_installments(price, expected_max) -> None:
    assert pricing.max_installments(Decimal(price)) == expected_max


def test_rejected_plan_tells_the_customer_the_real_maximum() -> None:
    q = quote(product("349.90"), "credit", installments=6)
    assert any("4x" in note for note in q.notes)


@pytest.mark.parametrize("n", [0, 13, -1, 99])
def test_installments_outside_one_to_twelve_are_invalid(n) -> None:
    with pytest.raises(InvalidArgumentsError):
        quote(product("2199.00"), "credit", installments=n)


def test_installments_outside_credit_are_flagged() -> None:
    q = quote(product("2199.00"), "pix", installments=6)
    assert q.installments is None
    assert any("cartão de crédito" in note for note in q.notes)


# --------------------------------------------------------------------------- not for sale


@pytest.mark.parametrize(
    ("availability", "product_id"),
    [("coming_soon", 130), ("discontinued", 113)],
)
def test_non_sellable_products_are_refused(availability, product_id) -> None:
    with pytest.raises(NotForSaleError) as exc:
        quote(product("1749.00", availability, product_id=product_id), "pix")
    assert exc.value.code == "not_for_sale"


def test_out_of_stock_is_still_quotable_with_a_warning() -> None:
    """Product 96 is active with zero stock: the price is real, delivery is not promised."""
    q = quote(product("799.90", "out_of_stock", product_id=96), "pix")
    assert q.final_total == Decimal("759.90")
    assert any("sem estoque" in note for note in q.notes)


def test_pix_discount_is_rounded_as_its_own_money_line() -> None:
    """799.90 * 5% = 39.995.

    We round the *discount* to 40.00 and subtract, giving 759.90, instead of rounding the
    final total (759.905 -> 759.91). One centavo apart, but only the first can be printed on a
    receipt: 'desconto R$ 40,00' has to be a real amount of money.
    """
    q = quote(product("799.90"), "pix")
    assert q.pix_discount == Decimal("40.00")
    assert q.final_total == Decimal("759.90")
    assert q.subtotal - q.pix_discount == q.final_total


def test_quantity_must_be_positive() -> None:
    with pytest.raises(InvalidArgumentsError):
        quote(product("2199.00"), "pix", quantity=0)


# -------------------------------------------------------------------------------- shipping


@pytest.mark.parametrize(
    ("price", "delivery", "cost"),
    [
        ("500.00", "metro_campo_grande", "0.00"),  # A14 boundary: >= 500 is free
        ("499.99", "metro_campo_grande", "35.00"),
        ("2199.00", "metro_campo_grande", "0.00"),
        ("359.00", "pickup", "0.00"),
    ],
)
def test_shipping_cost(price, delivery, cost) -> None:
    q = quote(product(price), "debit", delivery=delivery)
    assert q.shipping.cost == Decimal(cost)
    assert q.grand_total == q.final_total + Decimal(cost)


def test_other_cities_need_a_quote() -> None:
    """Manual 5.2: cost depends on CEP, weight and size, which we do not have (D19)."""
    q = quote(product("2199.00"), "pix", delivery="other_city")
    assert q.shipping.cost is None
    assert q.grand_total is None
    assert any("cotação" in note for note in q.notes)


def test_pix_discount_cannot_take_away_earned_free_shipping() -> None:
    """R$ 520 in PIX drops to R$ 494, but the order already qualified for free shipping."""
    q = quote(product("520.00"), "pix", delivery="metro_campo_grande")
    assert q.final_total == Decimal("494.00")
    assert q.shipping.cost == Decimal("0.00")
    assert q.grand_total == Decimal("494.00")


def test_pickup_is_the_default() -> None:
    q = quote(product("359.00"), "debit")
    assert q.shipping.cost == Decimal("0.00")
    assert q.grand_total == q.final_total


# ------------------------------------------------------------------- end-to-end oracle


def test_gd20_full_quote_matches_the_data_findings_oracle() -> None:
    """02_DATA_FINDINGS section 7: 2,199.00, no active promo, PIX 2,089.05, 12x of 183.25."""
    pix = quote(product("2199.00"), "pix")
    credit = quote(product("2199.00"), "credit", installments=12)

    assert pix.promo is None
    assert pix.final_total == Decimal("2089.05")
    assert credit.final_total == Decimal("2199.00")
    assert credit.installments is not None and credit.installments.allowed
    assert credit.installments.value == Decimal("183.25")
    assert credit.max_installments_allowed == 12
