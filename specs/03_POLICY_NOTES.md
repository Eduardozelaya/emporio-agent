---
type: reference
status: verified
phase: E1
created: 2026-11-01
updated: 2026-11-01
---

# 03 — Policy manual notes

> Index of `store_policies.pdf` (v2.1, June 2025) and the interpretation decisions for its
> ambiguities. `data/processed/policies.md` must carry the annotations marked **[note]** below.

## 1. Section index and how the agent uses each

| § | Topic | Used as | Key facts |
|---|---|---|---|
| 1 | About the store | Prompt (scope) | Founded 2008; **instruments only — no accessories** (strings, picks, cables, cases, pedals, amps) |
| 1.2 | Company data | Prompt (answers) | Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, 79202-333 · (67) 3341-4444 · CNPJ 12.345.678/0001-90 |
| 2 | Opening hours | Prompt + `store_hours.py` | Mon–Fri 09:00–18:00 · Sat 09:00–13:00 · Sun/holidays closed · may extend on special dates |
| 3 | Payment methods | Prompt + `pricing.py` | PIX (5 % off list price) · debit · credit up to 12x interest-free · boleto (clears in up to 3 business days) |
| 3.1 | Installments | `pricing.py` | Tiers (A3) · mixed payment methods allowed above R$ 2,000 |
| 4.1 | Right of withdrawal (online) | Prompt | 7 calendar days **after receipt**, original packaging, unused · refund same method within 10 business days · return shipping paid by the store |
| 4.2 | Defect exchange | Prompt | Up to 30 days after purchase; after that, manufacturer warranty (store can mediate); misuse not covered |
| 4.3 | Preference exchange | Prompt | Up to 7 days, subject to availability, perfect condition, original packaging; price difference charged/refunded |
| 4.4 | Not exchangeable | Prompt | Customised/special setup instruments · "final sale" clearance items · wind-instrument mouthpieces (hygiene) |
| 5.1 | Metro Campo Grande delivery | Prompt | Free above R$ 500; otherwise R$ 35 flat; 1–3 business days; own motorcycle courier, phone call before delivery |
| 5.2 | Other cities | Prompt | PAC 5–12, SEDEX 2–5, Jadlog 3–8 business days; cost by CEP/weight/size; large instruments need a special quote; insured; refuse damaged deliveries |
| 5.3 | Tracking code | Prompt | Sent by e-mail and WhatsApp on dispatch; format BR + 9 alphanumerics + BR |
| 6.1 | Promotion calendar | Prompt | Aug anniversary 10–25 % · **Nov Black Friday 15–30 %** · Feb back-to-school · clearance · Musician's week (Nov 22) |
| 6.2 | Promotion rules | Prompt + `pricing.py` | **Not cumulative; PIX 5 % does not apply on promo prices** · subject to stock, no rain check · always show original price + % |
| 7.1 | Service guidelines | Prompt (behaviour) | Tone informal but professional ("a friend who knows music") · ≤ 5 min response · out of hours: tell when the team is back · **never state price, stock or deadlines without checking the system** · redirect accessory requests, suggest partner stores when possible |
| 7.2 | Standard flow | Prompt (behaviour) | Greet (by name if available) → understand → look up → answer clearly → close politely |
| 7.3 | Special situations | Prompt (behaviour) | Out of stock → alternatives · discontinued → equivalents · expired promo → be transparent, show current price · complaint → empathy, register, forward; **response within 24 business hours** |
| 8 | Warranty | Prompt | Legal 90 days from receipt · manufacturer 6 months–2 years · not covered: wear (frets, strings, felts, reeds), misuse, third-party repairs, cosmetic damage |
| 9 | Privacy (LGPD) | Prompt + D8 | Data used only for orders, status, opt-in marketing, legal duties · not shared for marketing · customer may request deletion via WhatsApp or e-mail |
| 10 | Final provisions | Prompt (escalation) | **When in doubt about applying a policy, consult management** → escalate |

## 2. Ambiguities and decisions

| ID | Ambiguity | Where | Decision |
|---|---|---|---|
| A1 | Two phone numbers: (67) 3341-4444 (cover, §1.2) vs (67) 3321-4500 (§7, "WhatsApp channel") | Cover/§1.2 vs §7 | Use **(67) 3341-4444** (official company data, appears twice). **[note]** in policies.md |
| A2 | E-mail written `contato@empóriodamusica.com.br` (accent) in §1.2 vs no accent on cover | §1.2 | Use **contato@emporiodamusica.com.br** (accented domains are unlikely). **[note]** |
| A3 | Installments: table says "credit up to 12x, min installment R$ 100"; §3.1 says "up to 3x no minimum (except below R$ 50)", 4–6x min R$ 80, 7–12x min R$ 100 | §3 vs §3.1 | Tiers: ≤3x min R$ 50 · 4–6x min R$ 80 · 7–12x min R$ 100 (DECISIONS D11) |
| A4 | Withdrawal right applies to "online purchases"; orders have no channel | §4.1 vs data | Assume orders in the base are **online** |
| A5 | 7-day preference exchange: counted from purchase or receipt? | §4.3 | Do not state a start date; explain rule; escalate borderline cases |
| A6 | Withdrawal counted "after receipt", data has no receipt date | §4.1 vs data | Agent **asks** the customer when they received it |
| A7 | "Suggest partner stores" but no list is given | §7.1 | Never invent store names; just redirect |
| A8 | "More than 300 instruments" vs 65 in the catalog | §1 vs data | Only talk about what the system returns |
| A9 | Holidays are "closed" but not listed | §2 | **Superseded by DECISIONS D18:** `store_hours.py` carries a minimal Brazilian **national** holiday calendar (fixed dates + Easter-derived). Municipal/state holidays of Campo Grande/MS remain a documented limitation |
| A10 | Defect exchange 30 days vs legal warranty 90 days | §4.2 vs §8.1 | Repeat both facts as written; for disputes → escalate (`policy_exception`). The agent does not give legal advice |
| A11 | Response-time SLA "≤ 5 min" is for humans | §7.1 | Not applicable to the bot; ignore |
| A12 | Promotion calendar (§6.1) vs actual promotions | §6.1 vs data | Calendar = "usually"; only `is_active` promotions are offered (manual §7.3: never promise expired discounts) |
| A13 | Complaint response "within 24 business hours" (horas úteis) has no defined counting rule | §7.3 | Read as **one business day**: same time on the next business day; if the store is closed now, counted from the next opening. Computed by `store_hours.expected_response` |
| A14 | Shipping: "free **above** R$ 500" and "flat fee **below** R$ 500" leave exactly R$ 500,00 uncovered | §5.1 | Treat **≥ R$ 500,00 as free** (reading in the customer's favour; standard retail practice). Boundary case is an explicit test |

## 3. Rules that must be enforced in code (not only in the prompt)

| Rule | Where |
|---|---|
| PIX 5 % only on list price, never on promo price | `pricing.quote` |
| Installment tiers and 1–12 range | `pricing.installment_options` |
| Promotion only for sellable products | `pricing.effective_price` |
| Metro delivery free above R$ 500, else R$ 35; other cities need a quote (D19) | `pricing.shipping_cost` |
| Store open/closed and next opening, **holidays included** (D18) | `store_hours.status` |
| Order shown only after e-mail/phone match | `tools.get_order_status` |
| Stale order detection | `tools.get_order_status` (uses `EMPORIO_TODAY`) |
