---
type: epic
epic: E2
status: done
created: 2026-11-01
estimate: 1.5h
depends_on: [E0]
---

# E2 — Domain rules (pricing + store hours)

## Goal
All money and time rules of the manual as **pure, table-tested functions**, so the LLM never
does arithmetic and never guesses whether the store is open.

## Why
"Nunca fornecer informações sobre preços … sem consultar o sistema" (manual §7.1). Wrong numbers
are the most damaging error a store agent can make (misleading advertising). Pure functions are
trivially testable and easy to defend in an interview.

## Scope
- `pricing.py`: `round_brl`, `effective_price`, `pix_total`, `installment_options`,
  `shipping_cost` (D19), `quote`.
- `store_hours.py`: `holidays(year)` (D18), `is_business_day`, `status(now)`, `next_opening(now)`,
  `expected_response(now)`.

**Out:** shipping cost for cities outside the Campo Grande metro area — the manual says it depends
on CEP, weight and dimensions, which we do not have. `quote` returns `cost: null` and the agent
offers a special quote via escalation.

## Acceptance criteria
1. WHEN a product has an active promotion THEN `effective_price` SHALL be list × (1 − p/100),
   rounded half-up to 2 decimals.
2. WHEN payment is PIX and there is **no** active promotion THEN total SHALL get 5 % off;
   WHEN there **is** an active promotion THEN PIX SHALL NOT add any discount (manual §6.2).
3. WHEN installments n are requested THEN the quote SHALL mark them allowed only if 1 ≤ n ≤ 12
   and the installment value meets the tier minimum (≤3x: 50 · 4–6x: 80 · 7–12x: 100; 1x always),
   and SHALL return `max_installments_allowed` and a reason when not allowed.
4. WHEN payment is debit or boleto THEN total SHALL be the effective price × quantity, with a note
   for boleto ("compensação em até 3 dias úteis").
5. WHEN the product is not sellable (discontinued/coming_soon) THEN `quote` SHALL refuse with
   `not_for_sale`.
6. WHEN `status(now)` is called THEN it SHALL return open/closed using Mon–Fri 09–18,
   Sat 09–13, Sun closed (America/Campo_Grande), and the next opening datetime when closed.
7. WHEN `expected_response(now)` is called THEN it SHALL return a pt-BR sentence for the
   escalation SLA (24 business hours = by the same time on the next business day; if closed, from
   the next opening) — see 03_POLICY_NOTES A13.
8. WHEN the date is a Brazilian **national holiday** THEN the store SHALL be closed and
   `next_opening` SHALL skip it (D18), including Easter-derived holidays.
9. WHEN `delivery = metro_campo_grande` THEN shipping SHALL be 0.00 if the goods subtotal is
   **R$ 500.00 or more** (A14) and 35.00 otherwise; WHEN `delivery = other_city` THEN `cost` SHALL be
   `null` with a note that it depends on CEP/weight/size; WHEN `delivery = pickup` THEN `cost`
   SHALL be 0.00 and `grand_total` SHALL equal `final_total` (D19).

## Design notes
- Use `Decimal` internally, convert to `float` with 2 decimals at the boundary.
- `quote(product, payment_method, installments=None, quantity=1) -> Quote` (Pydantic model).
- Keep a `format_brl(value) -> "R$ 2.089,05"` helper for examples and CLI, but tools return numbers.

## Tasks

| ID | Task | Depends | Commit message | Done when |
|---|---|---|---|---|
| E2-T1 | `pricing.py` core: rounding, effective price, PIX rule, `format_brl` | E0 | `feat(pricing): promotion and pix rules` | Table tests pass |
| E2-T2 | Installment tiers + `quote()` + `Quote` model | T1 | `feat(pricing): installment rules and price quote` | Table tests pass |
| E2-T3 | `store_hours.py` status/next opening/expected response + national holidays (D18) | E0 | `feat(hours): store opening hours, holidays and response window` | Table tests pass |
| E2-T4 | `shipping_cost` + `delivery` in `quote()` (D19) | T2 | `feat(pricing): metro delivery shipping rule` | AC9 + boundary test |

## Test table (must exist in `tests/test_pricing.py` / `tests/test_store_hours.py`)

| Case | Input | Expected |
|---|---|---|
| GD20 PIX | 2199.00, no promo, pix | 2089.05 |
| GD20 12x | 2199.00, credit 12 | allowed, 183.25 |
| Promo + PIX | 549.00, 20 %, pix | 439.20 (no extra 5 %) |
| Promo price | 2399.00, 18 % | 1967.18 |
| 6x too low | 349.90, credit 6 | not allowed (58.32 < 80), max = 4 |
| Small ticket | 120.00, credit 3 | not allowed (40 < 50), max = 2 |
| 12x boundary | 1200.00, credit 12 | allowed (100.00) |
| 13x | any, credit 13 | invalid |
| Not for sale | product 130 | `not_for_sale` |
| Sunday + holiday Monday | 2026-11-01 12:20 | closed; next opening **Tue 2026-11-03 09:00** (Mon 11-02 is Finados, D18) |
| Saturday | 2026-11-07 12:59 / 13:00 | open / closed |
| Weekday | 2026-11-03 18:00 | closed, next Wed 09:00 |
| Fixed holiday | 2026-09-07 10:00 (Mon) | closed, next Tue 09:00 |
| Easter-derived | Good Friday 2026-04-03 10:00 | closed |
| Shipping free boundary | subtotal 500.00, metro | 0.00 (A14) |
| Shipping fee | subtotal 499.99, metro | 35.00 |
| Shipping other city | subtotal 2199.00, other_city | `cost = null` + note |
| Shipping pickup | subtotal 359.00, pickup | 0.00, grand_total = final_total |
