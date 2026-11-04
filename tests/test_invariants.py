"""Properties that must hold for every product, not just the ones in the examples.

Table tests prove the cases someone thought of. These sweep the whole catalogue against
every payment method and every instalment count and assert the things that must never be
false. Money is where a bug is most expensive and least visible.
"""

from __future__ import annotations

import itertools
import json
import random
import sqlite3
from decimal import Decimal

import pytest

from emporio import memory, pricing
from emporio.config import PROJECT_ROOT
from emporio.pricing import NotForSaleError, Product, quote

DB = PROJECT_ROOT / "data" / "processed" / "emporio.db"
METHODS = ("pix", "debit", "credit", "boleto")
DELIVERIES = ("pickup", "metro_campo_grande", "other_city")


@pytest.fixture(scope="module")
def catalogue() -> list[Product]:
    if not DB.exists():
        pytest.skip("run `python -m emporio build-data` first")
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT p.*, (SELECT discount_percent FROM active_promotions ap "
        "WHERE ap.product_id = p.product_id) AS promo FROM products p"
    ).fetchall()
    connection.close()
    return [
        Product(
            product_id=row["product_id"],
            name=row["name"],
            price_brl=Decimal(str(row["price_brl"])),
            availability=row["availability"],
            promo_percent=row["promo"],
        )
        for row in rows
    ]


def two_decimals(value: Decimal) -> bool:
    return value == value.quantize(Decimal("0.01"))


def test_the_sweep_actually_covers_the_catalogue(catalogue) -> None:
    assert len(catalogue) == 65
    assert sum(1 for p in catalogue if p.availability == "available") == 61


def test_every_quote_in_the_catalogue_holds_its_invariants(catalogue) -> None:
    """Any one of these being false is a wrong price shown to a customer."""
    checked = 0
    for product, method, delivery in itertools.product(catalogue, METHODS, DELIVERIES):
        if product.availability not in pricing.SELLABLE:
            with pytest.raises(NotForSaleError):
                quote(product, method, delivery=delivery)
            continue

        for quantity in (1, 3):
            result = quote(product, method, quantity=quantity, delivery=delivery)
            checked += 1
            tag = f"{product.product_id} {method} {delivery} x{quantity}"

            # Money is money: two decimals, never negative.
            for name, value in (
                ("unit_price", result.unit_price),
                ("subtotal", result.subtotal),
                ("pix_discount", result.pix_discount),
                ("final_total", result.final_total),
            ):
                assert two_decimals(value), f"{tag}: {name} has sub-centavo precision"
                assert value >= 0, f"{tag}: {name} is negative"

            # The breakdown has to add up, or the customer cannot check our arithmetic.
            assert result.final_total == result.subtotal - result.pix_discount, tag
            assert result.subtotal <= result.unit_price * quantity, tag

            # Manual 6.2: PIX never stacks on a promotion, and never applies elsewhere.
            if method != "pix" or result.promo:
                assert result.pix_discount == 0, f"{tag}: unexpected PIX discount"
            else:
                expected = pricing.round_brl(result.subtotal * Decimal("0.05"))
                assert result.pix_discount == expected, tag

            # A promotion can only ever lower the unit price.
            if result.promo:
                assert result.promo.unit_price < result.unit_price, tag

            # Shipping is one of exactly three outcomes (manual 5.1 and 5.2).
            cost = result.shipping.cost
            if delivery == "other_city":
                assert cost is None and result.grand_total is None, tag
            else:
                assert cost in (Decimal("0.00"), Decimal("35.00")), f"{tag}: shipping {cost}"
                assert result.grand_total == result.final_total + cost, tag
                if delivery == "metro_campo_grande":
                    free = result.subtotal >= Decimal("500.00")
                    assert (cost == 0) is free, f"{tag}: free-shipping threshold wrong"

    assert checked > 1400, f"the sweep only ran {checked} quotes"


def test_installment_plans_are_consistent_for_every_product(catalogue) -> None:
    """For each sellable product: the stated maximum is allowed and one more is not."""
    for product in catalogue:
        if product.availability not in pricing.SELLABLE:
            continue
        base = quote(product, "credit", installments=1)
        best = base.max_installments_allowed
        tag = f"product {product.product_id} (total {base.final_total})"

        assert 1 <= best <= 12, tag
        assert base.max_installment_value == pricing.installment_value(base.subtotal, best), tag

        allowed = quote(product, "credit", installments=best)
        assert allowed.installments is not None and allowed.installments.allowed, tag

        if best < 12:
            refused = quote(product, "credit", installments=best + 1)
            assert refused.installments is not None
            assert not refused.installments.allowed, f"{tag}: {best + 1}x should be refused"
            assert refused.installments.reason, tag

        for n in range(1, best + 1):
            plan = quote(product, "credit", installments=n).installments
            assert plan is not None and plan.allowed, f"{tag}: {n}x should be allowed"
            # Rounding can shift the total by at most a centavo per instalment.
            assert abs(plan.value * n - base.final_total) <= Decimal("0.01") * n, tag


def test_a_refused_plan_always_prices_its_alternative(catalogue) -> None:
    """The gap that made the agent do arithmetic: never leave the maximum unpriced."""
    for product in catalogue:
        if product.availability not in pricing.SELLABLE:
            continue
        result = quote(product, "credit", installments=12)
        if result.installments and not result.installments.allowed:
            assert result.max_installment_value > 0
            priced = pricing.format_brl(result.max_installment_value)
            assert any(priced in note for note in result.notes), (
                f"product {product.product_id}: the maximum is named but not priced"
            )


@pytest.mark.parametrize("quantity", [1, 2, 7, 20])
def test_quantity_scales_the_subtotal_exactly(catalogue, quantity) -> None:
    for product in catalogue[:20]:
        if product.availability not in pricing.SELLABLE:
            continue
        one = quote(product, "debit", quantity=1)
        many = quote(product, "debit", quantity=quantity)
        assert many.subtotal == one.subtotal * quantity


# -------------------------------------------------------------- memory window fuzzing


def test_a_random_window_is_never_left_with_an_orphan_tool_message() -> None:
    """Whatever the conversation looked like, the window we send must be sendable.

    The API rejects a tool message whose requesting assistant message is missing, and the
    customer then gets a fallback for a bug that is entirely ours.
    """
    rng = random.Random(20261104)
    for _ in range(300):
        conversation: list[dict] = []
        for _ in range(rng.randint(1, 14)):
            kind = rng.choice(["user", "assistant", "tools"])
            if kind == "user":
                conversation.append({"role": "user", "content": "oi"})
            elif kind == "assistant":
                conversation.append({"role": "assistant", "content": "ola"})
            else:
                call_ids = [f"c{rng.randint(0, 999)}" for _ in range(rng.randint(1, 3))]
                conversation.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": cid,
                                "type": "function",
                                "function": {"name": "get_product", "arguments": "{}"},
                            }
                            for cid in call_ids
                        ],
                    }
                )
                for cid in call_ids:
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": cid,
                            "name": "get_product",
                            "content": "{}",
                        }
                    )

        for size in range(1, len(conversation) + 1):
            window = memory.trim_to_valid_window(conversation[-size:])
            if not window:
                continue
            assert window[0]["role"] != "tool", "window starts on an orphan result"
            last = window[-1]
            unanswered = last["role"] == "assistant" and last.get("tool_calls")
            assert not unanswered, "window ends on an unanswered request"
            assert json.dumps(window)  # still serialisable for the wire
