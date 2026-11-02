---
type: state
status: active
phase: meta
created: 2026-11-01
---

# PAUSE_WORK — live snapshot

> Newest entry on top. Update at the end of every work session (and before any break longer
> than an hour). Claude Code must read this before starting.

## ▶️ RESUME HERE — 2026-11-01 (E0–E3 done)

**State:** E0, E1, E2 and E3 complete, published at
https://github.com/Eduardozelaya/emporio-agent. `ruff` + `pytest` green — **258 tests**, no
API key needed. The six tools work end to end and can be driven by hand with
`python -m emporio tool <name> '<json>'`.
**Next:** E4 (prompt + LLM client + tool loop). This is the first epic that needs the API key.
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
| 2026-11-01 | E1 | E0's CLI test used `build-data` as its example of an unimplemented command | Once E1 implemented it, the test silently ran a real build against the working tree. Repointed at `eval`; a test must never depend on a command staying unimplemented. |
| 2026-11-01 | E1 | — | Found while coding: `specs.strings` means the string **material** (nylon/steel) in Violões/Ukuleles but the string **count** ("6", "4") in Guitarras/Baixos. Deriving it everywhere would have put "6" in a material filter. Only categories 5 and 9 get `strings`/`electric`. |
| 2026-11-01 | E3-T3 | First name search was a token `LIKE` plus `difflib` on the whole name | Failed two realistic queries: "takamini gd 20" (whole-string similarity is low because the product name is longer) and "violão Yamaha" (no product name contains "violão" — it is the category). Replaced with per-token scoring plus a pass that drops category words. |
| 2026-11-01 | E3 | `get_order_status` description only said what the tool returns | A failing test exposed it. Tool descriptions are the only routing lever over the model, so each one now names the triggering situation and carries its guardrail; a test asserts both. |
| 2026-11-01 | E3 | Left a no-op `_unused_imports_guard()` function in `tools.py` | Dead code written to silence an unused import instead of deleting the import. Removed both. |
| 2026-11-02 | E4-T5 | Retry slept a flat 0.5 s on every provider error | The first live run fell back on all seven questions. The provider was saying "try again in 42s" and we retried immediately. Now the hint is parsed from the headers and honoured (D21). |
| 2026-11-02 | E4-T5 | `LLMError` was swallowed with no trace | The fallback was right but hid "no credits remaining" — the one sentence that explained everything. `Reply.error` now reaches the operator and the turn log, never the customer. |
| 2026-11-02 | E4-T5 | Prompt said "no máximo 5 por mensagem" | The model read it as a *query* limit and called `search_products(limit=5)`. Clarified that it governs what is written, not what is fetched. |
| 2026-11-02 | E4-T5 | Prompt did not forbid re-asking for known information | "violões até R$1000" got answered with "qual o valor máximo?". Added the rule to extract filters from the message itself. |

### Session log
| Date | Done | Commits | Notes |
|---|---|---|---|
| 2026-11-01 | Specs | — | Kit created from analysis of challenge, data, manual and my StayBot project |
| 2026-11-01 | Spec review + E0 | `de0b52a`…`d5e9b35` (7) | Verified every data finding against the raw CSVs; closed 5 spec gaps (D18, D19, D20, A14, limit); built package, config, CLI stub, 13 tests, CI workflow; repo pushed |
| 2026-11-01 | E2 | `92e1862`, `2726e29` | `pricing.py` (promo, PIX, tiers, shipping) and `store_hours.py` (hours, national holidays, SLA). 107 tests green |
| 2026-11-01 | E1 | see below | `data_loader.py` → `emporio.db` + `reports/data_quality.md` (19 findings); `policies.py` + curated `policies.md`. 198 tests green |
| 2026-11-01 | E3 | see below | `db.py` (read-only store / writable app) and `tools.py` with the six tools, schema export, safe dispatcher and the `tool` debug command. 258 tests green |
