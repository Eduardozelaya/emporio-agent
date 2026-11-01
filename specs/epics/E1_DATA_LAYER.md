---
type: epic
epic: E1
status: todo
created: 2026-11-01
estimate: 2.5h
depends_on: [E0]
---

# E1 — Data layer (raw → clean SQLite + policies text)

## Goal
Turn the raw CSVs into a clean, queryable SQLite database and the policy PDF into reviewed
Markdown, reproducing every finding in [02_DATA_FINDINGS](../02_DATA_FINDINGS.md) automatically.

## Why
Every tool depends on trustworthy data. "Tratamento dos dados" is an explicit evaluation item, so
the treatment must be visible (report) and justified (README).

## Scope
- `data_loader.py`: read → validate → transform → write `data/processed/emporio.db`.
- `reports/data_quality.md`: generated list of issues (committed).
- `policies.py`: PDF → text; `data/processed/policies.md` reviewed by hand and committed.

**Out:** time-dependent flags (stale orders) — computed at query time in E3 (DECISIONS D17).

## Acceptance criteria
1. WHEN `python -m emporio build-data` runs THEN it SHALL create `emporio.db` with tables
   `categories, products, promotions, customers, orders, order_items, data_quality_issues` and view
   `active_promotions`, and SHALL be idempotent (second run gives the same result).
2. WHEN the loader runs THEN files in `data/raw/` SHALL NOT be modified.
3. WHEN a product is loaded THEN it SHALL have `availability` derived by the rule in 02 §3, parsed
   `specs_json`, and for categories Violões/Ukuleles the derived `strings` and `electric` fields.
4. WHEN categories are loaded THEN each SHALL have `product_count` (6, 7, 8 = 0).
5. WHEN customers are loaded THEN `email_norm` and `phone_digits` SHALL be filled and customer 43
   SHALL have `duplicate_of = 11`.
6. WHEN orders are loaded THEN `payment_method` SHALL be split into method + installments.
7. WHEN the loader finishes THEN `data_quality_issues` and `reports/data_quality.md` SHALL list at
   least: total mismatches (orders 3, 20), installment violations (9, 16, 18), PIX without discount
   (1, 5, 10, 13, 17), coming-soon product in orders (3, 14), active product with zero stock (96),
   empty categories (6, 7, 8), duplicate customer (11/43).
8. WHEN `policies.md` is read THEN it SHALL contain all sections of the manual as Markdown and the
   **[note]** annotations A1–A3 from [03_POLICY_NOTES](../03_POLICY_NOTES.md).

## Design notes
- Pipeline functions are pure (`DataFrame → DataFrame`) and tested individually; only `main()` does I/O.
- `active_promotions` view: `is_active = 1` AND product sellable; if several rows, highest discount (D9).
- Text normalisation helper `normalize_text()` (lowercase, strip accents) stored as
  `products.name_norm` to support search in E3.
- Policy extraction: `pypdf` → raw text → manual cleanup into headings/tables. The script writes
  `data/processed/policies_raw.txt` (gitignored); the curated `policies.md` is committed.

## Tasks

| ID | Task | Depends | Commit message | Done when |
|---|---|---|---|---|
| E1-T1 | `data_loader.read_raw()` + schema checks (columns, types, FK integrity) | E0 | `feat(data): read and validate raw csv files` | Test asserts row counts 65/9/25/20/22/50 |
| E1-T2 | Product transforms: availability, specs parsing, strings/electric, `name_norm`; category `product_count` | T1 | `feat(data): derive product availability and specs fields` | Tests for 96, 113, 130, 136 and category counts |
| E1-T3 | Customer + order transforms: normalisation, duplicate flag, payment parsing | T1 | `feat(data): normalize customers and parse order payments` | Tests for 11/43 and `credit_12x` |
| E1-T4 | Data-quality checks → `data_quality_issues` rows | T2, T3 | `feat(data): detect data quality issues` | Test asserts every issue in AC7 |
| E1-T5 | Write SQLite + `active_promotions` view + `build-data` CLI command + markdown report | T4 | `feat(data): build sqlite database and quality report` | `emporio.db` and `reports/data_quality.md` generated |
| E1-T6 | `policies.py` extraction + curated `data/processed/policies.md` (human review) | E0 | `feat(policies): extract and curate store policy manual` | Test asserts key facts (address, hours, 7 dias, 30 dias, 5%) present |
| E1-T7 | Oracle tests: violões ≤ 1000 available = 12 ids; 4 active promotions | T5 | `test(data): oracle checks from data findings` | Matches 02 §7 |

## Independent test
`python -m emporio build-data && sqlite3 data/processed/emporio.db "select count(*) from active_promotions"` → `4`.
Open `reports/data_quality.md` and compare with [02_DATA_FINDINGS](../02_DATA_FINDINGS.md).

## Human review checkpoint
Read `policies.md` side by side with the PDF. This is the only artefact that is hand-curated —
you must be able to say "I reviewed every line".
