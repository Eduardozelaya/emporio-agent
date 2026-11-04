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

### D3 — Model and provider: OpenAI-compatible client, provider chosen by config
- **Context:** need reliable tool calling, low latency, low cost.
- **Options:** OpenAI · Anthropic · Gemini free tier · Groq · local (Ollama).
- **Decision:** the OpenAI SDK pointed at `LLM_BASE_URL` with `LLM_MODEL`. The credential is
  `LLM_API_KEY` (`OPENAI_API_KEY` still accepted) because the client speaks the OpenAI
  *protocol*, not necessarily to OpenAI.
- **Consequence:** the provider is configuration, not code. Tests never need a key at all.

**This decision earned its keep twice, under pressure, in two days.**

1. **OpenAI → Groq.** The OpenAI account ran out of credits mid-build (429, "no credits
   remaining"). Groq `openai/gpt-oss-120b`: three lines of `.env`, no code change.
2. **Groq → DeepSeek.** Groq's free tier caps a single request at **8,000 tokens**. Our
   request is ~7,000 (≈5.5k prompt + ≈1.5k tool schemas), leaving ~1,000 for history and tool
   results — and one catalogue search result is ~1,200. Multi-turn conversations returned
   **HTTP 413, permanent**, not a rate limit. Three lines again, to `deepseek-flash`.

Measured, not assumed:

| | OpenAI `gpt-4o-mini` | Groq free | DeepSeek `deepseek-flash` |
|---|---|---|---|
| Tokens per minute | tens of thousands | **8,000** | no tight cap advertised |
| Turn with one tool call | ~3 s | **~100 s**, or 413 | ~4 s |
| Full 19-scenario evaluation | ~2 min | ~1 h, incomplete | **112 s, 19/19** |

**The lesson is about our design, not about Groq.** A ~7k-token request per call is the
agent's dominant operational cost, and it is what makes a tight free tier unusable. That is
the measured case for trimming the prompt — listed in the README as future work, and the
reason D2 (whole manual in the prompt) carries a real price rather than being free.

### D24 — Permanent provider errors are not retried
- **Context:** the 413 above was retried six times per turn. A request that exceeds the
  provider's per-minute ceiling will be refused identically in a minute and tomorrow.
- **Decision:** statuses 400, 401, 403, 404, 413 and 422 fail immediately; only rate limits and
  transport errors are retried (D21). A 413 carries a hint naming the three ways out: lower
  `HISTORY_WINDOW`, shorten the prompt, or change provider.
- **Consequence:** a permanent failure costs one request instead of six, and the operator is
  told what to do about it.

### D21 — Retry honours the provider's own retry hint
- **Context:** the first live run fell back on every turn. The fallback behaved perfectly, but
  the retry slept 0.5 s while the provider was explicitly saying "try again in 42s".
- **Decision:** parse the delay from `retry-after` / `x-ratelimit-reset-*` headers (or the error
  message) and wait that long, up to `MAX_RATE_LIMIT_WAIT_S` (75 s), with a separate and more
  patient retry budget than for ordinary errors.
- **Consequence:** a rate limit is no longer a failed turn, it is a slow one. Beyond the cap the
  agent still falls back rather than leaving a customer waiting indefinitely.
- **Also from that run:** `Reply.error` now carries the provider's reason to the operator and the
  turn log, while the customer still sees only the neutral fallback. The first version swallowed
  the one sentence that explained the outage.

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

### D22 — Don't give the model a knob it misuses
- **Context:** `search_products` took a `limit` argument, default 12. The answer style tells the
  agent to *show* at most five products per message. In live runs the model repeatedly sent
  `limit=5`, conflating what it writes with what it fetches — so when the customer then asked
  "which is best for a beginner?", it was recommending from five products out of thirty-three.
- **Options:** reword the prompt (tried twice, still ignored) · reword the argument description ·
  **remove the argument**.
- **Decision:** remove it. The function keeps a fixed `SEARCH_RESULT_LIMIT = 12`, and
  `total_found` has always reported the real count, so the knob bought nothing.
- **Consequence:** the failure mode is impossible rather than discouraged. General rule worth
  keeping: when the model misuses a parameter, the cheapest fix is often to stop exposing it.

### D23 — A complaint opens a ticket in the same turn
- **Context:** evaluation scenario S14 ("my guitar arrived with a cracked top") failed. The
  agent was empathetic and asked for the order number, which reads fine — but it ended the turn
  with **no ticket**, and the manual §7.3 says to register and forward, with a 24-business-hour
  reply. A conversation that drifts away never registers the complaint at all.
- **Decision:** a complaint calls `escalate_to_human` **before** replying, even with details
  missing; the summary carries what is known so far. Asking for the order number comes after,
  and the customer is told the ticket number and the deadline.
- **Consequence:** promoted from a bullet in the escalation list to a numbered golden rule,
  because the model treated the list as advice.

### D25 — Separate a provider outage from a behaviour failure
- **Context:** the stability harness marked any scenario that ended in the safe fallback as a
  failure. During a long run the provider started returning "Connection error", and the report
  turned into a measurement of the provider's uptime rather than of the agent.
- **Decision:** a scenario that fell back is reported **INCONCLUSIVE** and excluded from the
  pass rate, which is quoted over conclusive executions only. Behaviour failures are listed
  separately and are the only ones that count against the agent.
- **Consequence:** the published number means "of the runs where the model answered, this many
  behaved correctly" — a claim that survives a flaky afternoon.
- **Also from that run:** ordinary retries went from 1 to 3 with exponential backoff. Two
  attempts half a second apart is not a serious try at a transient network fault, and the
  customer was seeing a fallback for something that cleared on its own. Rate limits keep their
  own budget (D21) and permanent errors are still not retried (D24).

### D20 — Customer first name returned after verification
- **Context:** manual §7.2 tells the attendant to greet the customer by name "if available", but
  D8 keeps the customer table away from the LLM, so the name is never available — an instruction
  the model can never satisfy.
- **Decision:** `get_order_status` returns `customer_first_name` **only after** the contact
  matched. Nothing else from the customer row is exposed.
- **Consequence:** §7.2 becomes satisfiable without weakening D8; the prompt says the name is
  only known after an order lookup.
