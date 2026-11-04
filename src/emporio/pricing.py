"""Money rules of the store manual, as pure functions.

The LLM is never allowed to do arithmetic (manual section 7.1: "never give information about
prices, stock or deadlines without checking the system"). Every value a customer sees comes
from `quote()`.

Rules implemented here:
  * promotion price            — manual 6.2, DECISIONS D9
  * PIX 5%, not cumulative     — manual 3 and 6.2
  * installment tiers          — manual 3.1, DECISIONS D11 / POLICY_NOTES A3
  * metro delivery shipping    — manual 5.1, DECISIONS D19 / POLICY_NOTES A14
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

Availability = Literal["available", "out_of_stock", "coming_soon", "discontinued"]
PaymentMethod = Literal["pix", "debit", "credit", "boleto"]
Delivery = Literal["pickup", "metro_campo_grande", "other_city"]

CENTS = Decimal("0.01")
PIX_DISCOUNT_RATE = Decimal("0.05")
MAX_INSTALLMENTS = 12

#: (upper bound of the tier, minimum value of each installment) — manual 3.1.
INSTALLMENT_TIERS: tuple[tuple[int, Decimal], ...] = (
    (3, Decimal("50.00")),
    (6, Decimal("80.00")),
    (12, Decimal("100.00")),
)

FREE_SHIPPING_FROM = Decimal("500.00")
METRO_SHIPPING_FEE = Decimal("35.00")

#: A price can be quoted for these; the others are refused with `not_for_sale`.
#: `out_of_stock` stays quotable: the price is real, we just cannot promise delivery.
SELLABLE: frozenset[str] = frozenset({"available", "out_of_stock"})


class PricingError(Exception):
    """Domain error with a stable code that tools turn into an error dict."""

    code = "pricing_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotForSaleError(PricingError):
    code = "not_for_sale"


class InvalidArgumentsError(PricingError):
    code = "invalid_arguments"


def _money(value: Decimal | float | int | str) -> Decimal:
    """Coerce to Decimal without inheriting binary float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_brl(value: Decimal | float | int | str) -> Decimal:
    """Round to centavos, half-up — the rounding a shop till uses, not banker's rounding."""
    return _money(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def format_brl(value: Decimal | float | int | str) -> str:
    """Format as Brazilian currency: 2089.05 -> 'R$ 2.089,05'."""
    amount = round_brl(value)
    whole, _, cents = f"{abs(amount):.2f}".partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    sign = "-" if amount < 0 else ""
    return f"{sign}R$ {'.'.join(groups)},{cents}"


class Product(BaseModel):
    """The minimum a price quote needs. Built by the tools layer from the database."""

    product_id: int
    name: str
    price_brl: Decimal
    availability: Availability
    promo_percent: int | None = Field(default=None, ge=1, le=99)


class Promo(BaseModel):
    percent: int
    unit_price: Decimal


class Shipping(BaseModel):
    #: None means "we cannot compute it" (other cities need a quote), not "free".
    cost: Decimal | None
    free_reason: str | None
    rule: str


class InstallmentPlan(BaseModel):
    requested: int
    allowed: bool
    value: Decimal
    reason: str | None


class Quote(BaseModel):
    product_id: int
    name: str
    payment_method: PaymentMethod
    quantity: int
    #: List price of one unit, before any discount — always shown next to a promo (manual 6.2).
    unit_price: Decimal
    promo: Promo | None
    subtotal: Decimal
    pix_discount: Decimal
    #: Goods only. Use `grand_total` when the customer asked about delivery (DECISIONS D19).
    final_total: Decimal
    shipping: Shipping
    grand_total: Decimal | None
    installments: InstallmentPlan | None
    max_installments_allowed: int
    #: What each instalment costs at that maximum. Returned even when the customer asked for
    #: a plan we refused: without it the model has the number of instalments but not their
    #: value, and a live run showed it dividing the total itself to fill the gap.
    max_installment_value: Decimal
    notes: list[str]


def promo_for(product: Product) -> Promo | None:
    """Active promotion of a product, or None. Never applies to non-sellable items (D9)."""
    if not product.promo_percent or product.availability not in SELLABLE:
        return None
    discounted = _money(product.price_brl) * (Decimal(100 - product.promo_percent) / Decimal(100))
    return Promo(percent=product.promo_percent, unit_price=round_brl(discounted))


def effective_price(product: Product) -> Decimal:
    """Unit price actually charged: the promotion price when there is one, else list price."""
    promo = promo_for(product)
    return promo.unit_price if promo else round_brl(product.price_brl)


def min_installment_value(n: int) -> Decimal:
    """Minimum value of each installment for an n-instalment plan (manual 3.1)."""
    for upper_bound, minimum in INSTALLMENT_TIERS:
        if n <= upper_bound:
            return minimum
    raise InvalidArgumentsError(f"installments must be between 1 and {MAX_INSTALLMENTS}, got {n}")


def installment_value(total: Decimal, n: int) -> Decimal:
    return round_brl(_money(total) / Decimal(n))


def check_installments(total: Decimal, n: int) -> InstallmentPlan:
    """Decide whether paying `total` in `n` instalments is allowed, with a pt-BR reason."""
    if n < 1 or n > MAX_INSTALLMENTS:
        raise InvalidArgumentsError(
            f"installments must be between 1 and {MAX_INSTALLMENTS}, got {n}"
        )
    value = installment_value(total, n)
    if n == 1:
        return InstallmentPlan(requested=1, allowed=True, value=value, reason=None)
    minimum = min_installment_value(n)
    if value < minimum:
        return InstallmentPlan(
            requested=n,
            allowed=False,
            value=value,
            reason=(
                f"Em {n}x a parcela fica em {format_brl(value)}, "
                f"abaixo do mínimo de {format_brl(minimum)} para {n}x."
            ),
        )
    return InstallmentPlan(requested=n, allowed=True, value=value, reason=None)


def max_installments(total: Decimal) -> int:
    """Largest allowed number of instalments for `total`.

    Searched from the top because the rule is not monotonic: R$ 349,90 passes at 4x
    (R$ 87,48 >= R$ 80) but fails at 5x (R$ 69,98 < R$ 80).
    """
    for n in range(MAX_INSTALLMENTS, 1, -1):
        if installment_value(total, n) >= min_installment_value(n):
            return n
    return 1


def shipping_cost(subtotal: Decimal, delivery: Delivery) -> Shipping:
    """Delivery cost per manual 5.1 / 5.2.

    The threshold is applied to the goods subtotal, before any payment discount, so that
    choosing PIX can never cost the customer the free shipping they already earned.
    """
    if delivery == "pickup":
        return Shipping(
            cost=Decimal("0.00"),
            free_reason=None,
            rule="Retirada na loja, sem frete.",
        )
    if delivery == "metro_campo_grande":
        metro_rule = (
            f"Região metropolitana de Campo Grande: grátis a partir de "
            f"{format_brl(FREE_SHIPPING_FROM)}, senão {format_brl(METRO_SHIPPING_FEE)}."
        )
        if _money(subtotal) >= FREE_SHIPPING_FROM:
            return Shipping(
                cost=Decimal("0.00"),
                free_reason=(
                    f"Frete grátis para pedidos a partir de {format_brl(FREE_SHIPPING_FROM)}."
                ),
                rule=metro_rule,
            )
        return Shipping(cost=METRO_SHIPPING_FEE, free_reason=None, rule=metro_rule)
    return Shipping(
        cost=None,
        free_reason=None,
        rule=(
            "Outras cidades (PAC, SEDEX ou Jadlog): o valor depende do CEP, peso e dimensões "
            "do produto, por isso precisa de cotação."
        ),
    )


def quote(
    product: Product,
    payment_method: PaymentMethod,
    installments: int | None = None,
    quantity: int = 1,
    delivery: Delivery = "pickup",
) -> Quote:
    """Full price breakdown for one product. The only place money is computed."""
    if quantity < 1:
        raise InvalidArgumentsError(f"quantity must be at least 1, got {quantity}")
    if product.availability not in SELLABLE:
        raise NotForSaleError(
            f"Product {product.product_id} ({product.name}) is {product.availability} "
            "and cannot be sold."
        )

    notes: list[str] = []
    promo = promo_for(product)
    unit = promo.unit_price if promo else round_brl(product.price_brl)
    subtotal = round_brl(unit * quantity)

    # Manual 6.2: the 5% PIX discount does not apply on top of a promotional price.
    pix_discount = Decimal("0.00")
    if payment_method == "pix":
        if promo:
            notes.append(
                "O desconto de 5% do PIX não é cumulativo com promoções (manual §6.2); "
                "o preço promocional já é o menor valor."
            )
        else:
            pix_discount = round_brl(subtotal * PIX_DISCOUNT_RATE)

    final_total = round_brl(subtotal - pix_discount)

    plan: InstallmentPlan | None = None
    if payment_method == "credit":
        plan = check_installments(final_total, installments if installments is not None else 1)
        if not plan.allowed:
            best = max_installments(final_total)
            notes.append(
                f"O máximo para este valor é {best}x de "
                f"{format_brl(installment_value(final_total, best))}."
            )
    elif installments is not None and installments > 1:
        notes.append("Parcelamento só está disponível no cartão de crédito.")

    allowed_max = max_installments(subtotal)
    ship = shipping_cost(subtotal, delivery)
    grand_total = None if ship.cost is None else round_brl(final_total + ship.cost)

    if promo:
        notes.append(
            f"Preço original {format_brl(product.price_brl)} com {promo.percent}% de desconto."
        )
    if payment_method == "boleto":
        notes.append("Boleto bancário: compensação em até 3 dias úteis.")
    if product.availability == "out_of_stock":
        notes.append(
            "Produto sem estoque no momento: o preço é válido, mas não há previsão de entrega."
        )
    if ship.free_reason:
        notes.append(ship.free_reason)
    if ship.cost is None:
        notes.append(ship.rule)

    return Quote(
        product_id=product.product_id,
        name=product.name,
        payment_method=payment_method,
        quantity=quantity,
        unit_price=round_brl(product.price_brl),
        promo=promo,
        subtotal=subtotal,
        pix_discount=pix_discount,
        final_total=final_total,
        shipping=ship,
        grand_total=grand_total,
        installments=plan,
        # Always reported, so "em quantas vezes posso parcelar?" never needs a second call.
        max_installments_allowed=allowed_max,
        max_installment_value=installment_value(subtotal, allowed_max),
        notes=notes,
    )
