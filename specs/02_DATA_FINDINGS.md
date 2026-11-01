---
type: reference
status: verified
phase: E1
created: 2026-11-01
updated: 2026-11-01
---

# 02 — Data findings (verified)

> Every number below was checked with a profiling script over the original files on 2026-11-01.
> Epic E1 must reproduce these checks automatically in `reports/data_quality.md`.
> Reference "today" for time-based findings: 2026-11-01.

## 1. Files and renaming

The zip extracts with mangled names (`T#U00e9cnico`, `pol#U00edticas`). Copy to `data/raw/` with
clean names; never edit their content.

| Original name | `data/raw/` name | Rows |
|---|---|---|
| `desafio_tecnico_ai_eng - products.csv` | `products.csv` | 65 |
| `desafio_tecnico_ai_eng - categories.csv` | `categories.csv` | 9 |
| `desafio_tecnico_ai_eng - promotions.csv` | `promotions.csv` | 25 |
| `desafio_tecnico_ai_eng - orders.csv` | `orders.csv` | 20 |
| `desafio_tecnico_ai_eng - order_items.csv` | `order_items.csv` | 22 |
| `desafio_tecnico_ai_eng - customers.csv` | `customers.csv` | 50 |
| `políticas_da_loja.pdf` | `store_policies.pdf` | 8 pages |
| `desafio_tecnico_ai_eng_artefact.pdf` | *not copied* (challenge statement) | — |

All files are UTF-8, comma-separated, with header. The customer data is fictitious (provided by
the challenge), so committing it to a public repo is acceptable — state this in the README.

## 2. Referential integrity — OK

- Every `orders.customer_id` exists in `customers`.
- Every `order_items.product_id` and `promotions.product_id` exists in `products`.
- `product_id` range 81–145, unique, **not sorted in the file** (145 appears between 130 and 131).
- Tracking codes all match the manual's format `^BR[A-Z0-9]{9}BR$` (13 chars).
- Customer phones all match `(67) 9XXXX-XXXX`; e-mail domains are fake (`jmail.com`, `coldmail.com`…).

## 3. Products

| Finding | Detail | Treatment |
|---|---|---|
| Status values | `active` 62, `discontinued` 2 (113, 136), `coming_soon` 1 (130) | Derive `availability` |
| Active but no stock | 96 — Giannini GF-3D Dreadnought Sunburst (`stock_quantity = 0`) | `availability = out_of_stock` |
| Discontinued with stock | 136 — Ibanez Bass 2X (stock 13) | Still `discontinued`: status wins over stock |
| Coming soon with stock | 130 — Kala KA-ABP-CTG (stock 2) | `coming_soon`: not for sale yet |
| **Empty categories** | Categories 6 (Sopro – Madeiras), 7 (Sopro – Metais), 8 (Cordas Orquestrais) have **0 products** | `product_count` in categories; agent says "not in our catalog right now", never invents |
| Products per category | 1 Guitarras: 5 · 2 Baixos: 4 · 3 Baterias: 3 · 4 Teclados: 3 · 5 Violões: 35 · 9 Ukuleles: 15 | — |
| `specs` JSON | Valid JSON in all rows; 10 rows use `": "` spacing, 55 compact; **keys differ by category** (violão/ukulele: top, back_sides, neck, strings, scale, electronics, color; guitar/bass: body, neck, strings, color; drums: shells, pieces, hardware, color; keyboards: keys, type, polyphony, color) | Parse to dict; store normalised JSON; derive `strings` (nylon/steel) and `electric` (bool) for violões/ukuleles |
| Synthetic-looking rows | 135–144 have generic names ("Music Man Bass 1X", "Nord Synth 2 Pro") and odd prices (8732, 19567) | Keep; mention in limitations |
| Language trap | "Violão" (acoustic, cat 5) ≠ "Guitarra" (electric, cat 1) in Brazilian Portuguese | Category descriptions in tool schema; prompt note |

Availability derivation (in this order):
`discontinued` → `coming_soon` → `stock_quantity <= 0` → `out_of_stock` → else `available`.

## 4. Promotions

| Finding | Detail | Treatment |
|---|---|---|
| No validity dates | Only `is_active` (0/1) | `is_active` is the only truth (DECISIONS D9) |
| Active promotions | 4 rows: product 127 −10 %, 121 −20 %, 90 −18 %, 94 −8 % | View `active_promotions` |
| Duplicated (inactive) rows | 93 (2 × Páscoa), 96 (2 × Semana do Músico: 18 % and 40 %), 99 (Páscoa + Aniversário) | Irrelevant while inactive; rule D9 if ever active |
| Promotion on discontinued product | 113 (inactive) | Never apply to non-sellable products |
| Takamine GD20 (95) | Has promotion 4 (12 %, "Oferta Especial") but **inactive** | Price is the list price |

Active promotion prices (rounded half-up, 2 decimals):

| Product | List | % | Promo price |
|---|---|---|---|
| 90 Crafter HT-100 Folk Aço Natural | 2,399.00 | 18 | 1,967.18 |
| 94 Taylor 110e Dreadnought Natural | 5,999.00 | 8 | 5,519.08 |
| 121 Ohana CK-20 Concert Natural | 549.00 | 20 | 439.20 |
| 127 Kalani KAL-700T Tenor Natural | 359.00 | 10 | 323.10 |

## 5. Orders and items

| Finding | Detail | Treatment |
|---|---|---|
| Status distribution | delivered 7 · confirmed 4 · pending 4 · cancelled 4 · shipped 1 | Map to pt-BR labels |
| Tracking only when shipped/delivered | confirmed/pending/cancelled have no tracking and no estimated delivery | Tool returns `null`, agent explains why |
| **Total ≠ items** | Order 3: 3,450.00 vs 2 × 1,749.00 = 3,498.00 (−48.00) · Order 20: 1,400.00 vs 799.00 + 689.00 = 1,488.00 (−88.00) | Keep recorded total (D16), flag |
| **Coming-soon product sold** | Orders 3 (delivered, 2025-11-20) and 14 (pending) contain product 130 (`coming_soon`) | Flag; agent does not promise delivery for 14 → escalate |
| **Installment rule violated** | Order 9: 349.90 in 6x = 58.32 < 80 · Order 16: 429.90 in 6x = 71.65 < 80 · Order 18 (cancelled): 459.90 in 12x = 38.33 < 100 | Flag only (historical) |
| **PIX discount not reflected** | PIX orders 1, 5, 10, 13, 17 have total = list price (no 5 %) | Flag; assumption: totals are pre-discount or the discount was applied at payment |
| **Stale shipped order** | Order 8 `shipped`, estimated delivery 2026-02-28 (8 months ago) | `needs_attention` → agent escalates |
| **Stale open orders** | confirmed/pending since 2026-02-20 … 2026-03-22 | `needs_attention` (> 15 days) |
| Cancelled reasons | Only cancelled orders have `notes` (17–20) | Agent may share the reason with the verified owner |
| No delivery date | Only `estimated_delivery`; no actual receipt date | Return window (7 days after receipt, manual §4.1) → agent asks the customer |
| No sales channel | Orders don't say online vs in-store | Assume online (03_POLICY_NOTES A4) |
| Payment method codes | `pix`, `debit`, `boleto`, `credit_3x`, `credit_6x`, `credit_12x` | Parse `credit_Nx` → method + N |

## 6. Customers

| Finding | Detail | Treatment |
|---|---|---|
| Duplicate person | 11 "Bruno Carvalho Martins" and 43 "Bruno Martins" share `bruno.martins@jmail.com` (different phones, both Três Lagoas) | `duplicate_of = 11` on 43; verification by e-mail still works |
| Cities | Campo Grande 24, Dourados 7, Três Lagoas 7, Corumbá 6, Ponta Porã 6 | Useful for shipping explanation (metro vs other cities) |
| Usage | Only for order ownership verification | Never sent to the LLM |

Normalisation: e-mail `strip().lower()`; phone → digits only (`67998123456`), also accept without
the area code `67`.

## 7. Expected answers (test oracle)

| Question | Expected facts |
|---|---|
| Violões ≤ R$ 1,000 available | 12 products: 83 (429.90), 85 (459.90), 89 (549.00), 88 (579.90), 81 (599.90), 84 (689.00), 87 (699.90), 86 (749.00), 107 (799.00), 82 (849.00), 91 (899.00), 112 (999.00). **Excluded:** 96 (out of stock), 113 (discontinued) |
| Takamine GD20 | 95 · 2,199.00 · stock 5 · no active promo · PIX 2,089.05 · 12x of 183.25 allowed |
| "Takamine" alone | 4 matches: 95 GD20, 100 GC5CE, 105 GN51CE, 115 GC1CE → clarify |
| Active promotions | the 4 rows in §4 |
| Order 8 (customer 2, anacarol.ferreira@coldmail.com) | shipped, tracking BRJL5544332BR, estimated 2026-02-28 → needs attention |
| Order 8 with another e-mail | `verification_failed` |
| Saxophone / violin | Category exists, 0 products → not available |
