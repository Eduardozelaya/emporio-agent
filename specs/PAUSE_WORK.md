---
type: state
status: active
phase: meta
created: 2026-11-01
---

# PAUSE_WORK — live snapshot

> Newest entry on top. Update at the end of every work session (and before any break longer
> than an hour). Claude Code must read this before starting.

## ▶️ RESUME HERE — 2026-11-01 (E0 + E2 done)

**State:** E0 and E2 complete. 9 commits on `main`, published at
https://github.com/Eduardozelaya/emporio-agent. `ruff` + `pytest` green — **107 tests**, no
API key needed.
**Next:** E1 (data layer: raw CSV → `emporio.db` + `policies.md` + quality report). E3 then has
everything it needs.
**Deadline:** Tue 2026-11-03 23:59 BRT (DECISIONS D0). Target: tag by Tue ~20:00.

### Open questions
- [x] OpenAI key available (D3) — confirmed 2026-11-01.
- [x] Commit identity — Eduardo Zelaya <eduardo.correia.zelaya@gmail.com>, set per-repo.
- [x] Public GitHub repo created and `main` pushed.
- [ ] Confirm with the recruiter whether the submission really needs a **PDF via Google Forms**:
      the challenge PDF only asks to reply to the e-mail with the repo link. If not required,
      E7-T4 (~1h) can be dropped.
- [ ] Ask the recruiter whether the holiday extends the deadline (optional, D0).

### Decisions taken today (before writing code)

Reviewed the whole spec set against the challenge PDF, the 6 CSVs and the 8-page manual.
Every number in 02_DATA_FINDINGS was re-verified against the raw files and **all of them held**
(row counts, the 12 violões ≤ R$1000, the 4 active promotions, order 3/20 total mismatches,
installment violations 9/16/18, duplicate customer 11/43). Five gaps were found and closed:

| Gap | Resolution |
|---|---|
| Examples pinned to 2026-11-01 would have the agent announce opening on Mon 11-02 — **Finados** | **D18**: minimal national holiday calendar in `store_hours.py`; A9 superseded |
| `quote_price` returned a "final total" with no shipping, although §5.1 is computable | **D19**: `delivery` argument + `shipping`/`grand_total`; other cities escalate |
| §7.2 asks to greet by name, but D8 keeps the customer table from the LLM — impossible instruction | **D20**: `customer_first_name` returned only after verification |
| §5.1 covers "above" and "below" R$ 500 but not exactly R$ 500,00 | **A14**: ≥ R$ 500 is free (customer's favour); boundary is an explicit test |
| `search_products` default `limit=8` contradicted E3 AC1 ("return the 12 violões") | Default raised to 12; `total_found` always reports the full count |

Also fixed: `db.py`/`llm.py` were missing from the repo layout in 01_ARCHITECTURE §9.

### Assistant corrections log (feeds README §AI usage)
| Date | Task | What the assistant proposed | What I changed and why |
|---|---|---|---|
| 2026-11-01 | E0 setup | — | Caught by review: `zoneinfo` has no IANA database on Windows, so `America/Campo_Grande` fails. Added a platform-conditional `tzdata` dependency. |
| 2026-11-01 | E0-T4 | `.gitattributes` with a blanket `* text=auto eol=lf` | Git was silently rewriting the CRLF endings of the original CSVs. `data/raw` is evidence and must stay byte-identical, so it is now `-text`. Verified the stored blob matches the source file byte count. |
| 2026-11-01 | E2-T1 | Commit message said "promotion and pix rules" while the diff also carried installments, quote and shipping | Amended before pushing: a commit message that does not describe its diff is worse than a big commit. The history has to be readable by the evaluator. |
| 2026-11-01 | E2-T1 | Rounding the PIX discount vs rounding the final total | Caught on a failing test: 799.90 × 5 % = 39.995. Chose to round the **discount** (R$ 40,00 → total R$ 759,90) rather than the total (R$ 759,91), because only the first can be printed on a receipt as a real money line. |

### Session log
| Date | Done | Commits | Notes |
|---|---|---|---|
| 2026-11-01 | Specs | — | Kit created from analysis of challenge, data, manual and my StayBot project |
| 2026-11-01 | Spec review + E0 | `de0b52a`…`d5e9b35` (7) | Verified every data finding against the raw CSVs; closed 5 spec gaps (D18, D19, D20, A14, limit); built package, config, CLI stub, 13 tests, CI workflow; repo pushed |
| 2026-11-01 | E2 | `92e1862`, `2726e29` | `pricing.py` (promo, PIX, tiers, shipping) and `store_hours.py` (hours, national holidays, SLA). 107 tests green |
