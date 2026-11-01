---
type: decisions
status: active
phase: meta
created: 2026-11-01
updated: 2026-11-01
---

# Decision log

Format: **context → options → what weighs → decision → consequence**. Status: `decided` unless
noted. The README "Technical decisions" section summarises these; this file keeps the detail.

---

### D0 — Deadline interpretation
- **Context:** case received Sat 2026-10-31; rule is "end of the 2nd business day". Mon 2026-11-02
  is a national holiday (Finados).
- **Options:** Tue 11-03 23:59 (holiday ignored) · Wed 11-04 23:59 (holiday counted).
- **Decision:** work towards **Tue 11-03 23:59**; Wednesday is only a buffer if the recruiter confirms.
- **Consequence:** freeze the repo (tag `v1.0-submission`) before Tue 23:59; no commits after.

### D1 — Agent approach: native tool calling (function calling)
- **Context:** the agent must decide when to query data vs policies. Answers depend on data
  (prices, stock), so the model must *see* the data before writing.
- **Options:**
  1. Intent classification to JSON + `switch` (pattern used in my production bot StayBot) — the
     model writes the reply before seeing data; needs a second call or templates.
  2. **Tool calling loop** — model requests tools, sees results, then writes.
  3. SQL agent — model writes free SQL.
  4. Framework agent (LangChain/LangGraph/LlamaIndex).
- **Weighs:** accuracy, privacy, simplicity, explainability in an interview.
- **Decision:** **2**, with a small hand-written loop.
- **Why not 3:** free SQL can leak other customers' data or produce wrong joins; closed tools
  enforce verification in code. **Why not 4:** for 6 tools and one loop, a framework adds
  abstraction without benefit; the plain loop is ~60 lines and fully visible.
- **Consequence:** tool descriptions become the main routing lever; tests check *which tool was
  called*, not exact wording.

### D2 — No RAG for the policy manual
- **Context:** manual is ~8 pages (≈3–4k tokens).
- **Options:** chunk + embed + retrieve · full text in the system prompt.
- **Decision:** **full text in the prompt** (static prefix → benefits from provider prompt caching).
- **Consequence:** zero retrieval errors (no "wrong chunk"); cost grows with manual size.
  **When to switch to RAG:** manual > ~30 pages, many documents, or per-store manuals.

### D3 — Model and provider: OpenAI `gpt-4o-mini` via OpenAI-compatible client
- **Context:** need reliable tool calling, low latency, low cost; I already run this model in
  production (StayBot) and know its behaviour.
- **Options:** OpenAI · Anthropic · Gemini free tier · local (Ollama).
- **Decision:** OpenAI SDK with `LLM_BASE_URL` + `LLM_MODEL` env vars; default `gpt-4o-mini`.
- **Consequence:** any OpenAI-compatible provider (DeepSeek, Groq, Ollama) works by config only.
  Evaluators need an OpenAI key (or a compatible endpoint) to chat; tests run without a key.

### D4 — Clean data in SQLite, built by a loader
- **Context:** small CSVs with quality issues; tools need filters and joins.
- **Options:** pandas in memory · SQLite · DuckDB.
- **Decision:** **SQLite** built by `data_loader.py` (pandas for the transform step).
- **Consequence:** tools use parameterised SQL (no injection); the DB can be inspected;
  rebuild is idempotent (`python -m emporio.data_loader`).

### D5 — Policies: PDF → reviewed Markdown, committed
- **Context:** PDF tables extract messily; the prompt needs clean text.
- **Decision:** `policies.py` extracts text once; the result is reviewed by hand and committed as
  `data/processed/policies.md`, with the known inconsistencies annotated (see 03_POLICY_NOTES).
- **Consequence:** deterministic prompt; a test checks the file exists and contains key facts.

### D6 — Interface: CLI (Streamlit as optional stretch)
- **Decision:** CLI with `rich` formatting and a `/debug` mode that shows tool calls — best for
  evaluators to *see* the reasoning. Streamlit only if E0–E7 are done early.

### D7 — Conversation memory: SQLite, sliding window
- **Context:** follow-ups like "e em 12x?" need history; sessions should survive restarts.
- **Decision:** persist every message (incl. tool calls/results) in `app.db`; send the last
  `HISTORY_WINDOW` messages, never splitting a tool-call group.
- **Consequence:** `--session <id>` resumes a conversation. Summarisation of old history = future work.

### D8 — Order privacy: verify e-mail or phone before showing an order
- **Context:** LGPD (manual §9); orders contain personal data.
- **Decision:** `get_order_status(order_id, email_or_phone)` compares normalised e-mail or phone
  digits with the order's customer. Unknown order and wrong contact return the **same** error.
- **Consequence:** no order enumeration; the LLM never receives the customer table.

### D9 — Promotion rule
- **Context:** promotions have no dates, only `is_active`; some products have several rows.
- **Decision:** only `is_active = 1` counts. If more than one active row exists for a product,
  use the **highest discount** and log a data-quality issue (today: no such case).
  Promotions never apply to `discontinued`/`coming_soon` products.
- **Consequence:** "Is the Black Friday promo valid?" → answered from `is_active`, never from the
  promotion name or calendar (manual §7.3).

### D10 — All money math in code
- **Decision:** `pricing.py` owns promotion price, PIX 5 % (not cumulative with promotions,
  manual §6.2), installment minimums (D11) and rounding (2 decimals, half-up).
- **Consequence:** the prompt forbids the model from computing values; tests cover every rule.

### D11 — Installment minimums (manual §3 vs §3.1 conflict)
- **Decision:** tiers — up to 3x: min R$ 50.00 per installment; 4x–6x: R$ 80.00; 7x–12x: R$ 100.00.
  `1x` always allowed. See 03_POLICY_NOTES A3.

### D12 — Language
- **Decision:** agent replies in **pt-BR** (Brazilian store and customers); code, docs, README,
  commit messages in **English** (recruiter requirement).

### D13 — Configurable "today"
- **Decision:** `EMPORIO_TODAY` env var overrides the clock (store hours, stale-order detection).
- **Consequence:** examples and tests are reproducible.

### D14 — Human hand-off as a tool
- **Decision:** `escalate_to_human` stores a ticket and returns a response window computed from
  store hours. Triggers are listed in epic E4.
- **Consequence:** hand-off is observable and testable; handoff rate becomes a business metric.

### D15 — Evaluation strategy
- **Decision:** three layers — (1) unit tests for pure logic and tools; (2) loop tests with a
  scripted fake LLM; (3) live scenario eval with behavioural checks (tools called, forbidden
  tools, numbers in reply ⊆ numbers in tool results, must/must-not contain).
- **Consequence:** CI runs (1)+(2) without secrets; (3) runs locally with a key and its report
  is committed.

### D16 — Order totals: keep as recorded
- **Context:** orders 3 and 20 totals differ from item prices (see 02_DATA_FINDINGS).
- **Decision:** the order total is what the customer was charged → show it as is; flag the
  mismatch in the data-quality report; never recompute it for the customer.

### D17 — Stale orders need attention
- **Decision:** `get_order_status` flags `needs_attention` when `status = shipped` and
  `estimated_delivery` < today, or `status in (pending, confirmed)` and `order_date` is older than
  15 days. It is **computed at query time** with `config.now()` (honours `EMPORIO_TODAY`), not
  stored by the loader, because "stale" depends on the current date. The agent must not say
  "it's on the way" for these; it explains and escalates (`data_inconsistency`).

### D18 — Minimal national holiday calendar
- **Context:** manual §2 says "Sundays **and holidays**: closed" but lists no holiday. Without a
  calendar the agent would tell a customer the store opens on 2026-11-02 (Finados), a national
  holiday — and that is the exact date used by the reproducible examples (D13).
- **Options:** ignore holidays and document the gap (original A9) · move the examples to a date
  without a holiday · **encode a minimal list of Brazilian national holidays**.
- **Weighs:** the manual explicitly names holidays as a closing rule, so ignoring them is not a
  missing feature — it is a rule we chose not to implement. A fixed-date list is ~15 lines.
- **Decision:** `store_hours.py` owns a list of **national** holidays (fixed dates: 01-01, 04-21,
  05-01, 09-07, 10-12, 11-02, 11-15, 11-20, 12-25) plus the Easter-derived ones computed with the
  anonymous Gregorian algorithm (Carnival Mon/Tue, Good Friday, Corpus Christi).
- **Consequence:** `status()` and `next_opening()` skip holidays; `expected_response()` (A13)
  counts business days correctly. **Still a limitation:** municipal/state holidays of Campo
  Grande/MS are not covered — documented in README. Supersedes 03_POLICY_NOTES A9.

### D19 — Shipping cost inside `quote_price`
- **Context:** manual §5.1 gives a computable rule for the Campo Grande metro area (free above
  R$ 500.00, otherwise a flat R$ 35.00). §5.2 says other cities depend on CEP, weight and size —
  not computable with the data we have.
- **Options:** leave shipping out of the quote (original design) · state the rule only in the
  prompt · **compute the metro-area case in `pricing.py` and refuse the rest**.
- **Weighs:** calling a number "final total" when it is not delivered is precisely the misleading
  information manual §7.1 warns about. The metro rule is deterministic, so it belongs in code.
- **Decision:** `quote_price` takes `delivery` enum(`pickup`, `metro_campo_grande`, `other_city`,
  defaults to `pickup`) and returns `shipping:{cost, free_reason|null, rule}` plus `grand_total`.
  For `other_city` it returns `cost: null` with a note that the quote depends on CEP/weight/size,
  and the agent offers `escalate_to_human(special_shipping_quote)`.
- **Consequence:** `final_total` keeps meaning "goods only" and `grand_total` means "delivered";
  the prompt forbids calling `final_total` the final price when delivery was mentioned.

### D20 — Customer first name returned after verification
- **Context:** manual §7.2 tells the attendant to greet the customer by name "if available", but
  D8 keeps the customer table away from the LLM, so the name is never available — an instruction
  the model can never satisfy.
- **Decision:** `get_order_status` returns `customer_first_name` **only after** the contact
  matched. Nothing else from the customer row is exposed.
- **Consequence:** §7.2 becomes satisfiable without weakening D8; the prompt says the name is
  only known after an order lookup.
