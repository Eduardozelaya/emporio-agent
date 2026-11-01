# Empório da Música — AI customer service agent

> Prototype of a text-message agent that answers customers of a (fictional) musical instrument
> store in Campo Grande/MS, using the store's operational data and its policy manual.
> Built for the Artefact AI Engineer technical challenge.

<!-- STATUS: skeleton written during planning (E0). Sections marked TODO are filled in E7. -->

**Highlights**
- Native **tool calling** with a small, transparent Python loop — no agent framework.
- The LLM decides and writes; **Python fetches facts and does all money math** (promotions,
  PIX discount, installment rules) — numbers are never invented.
- **Order privacy:** order status only after e-mail/phone verification.
- Knows when to **hand off to a human** (complaints, refunds, inconsistent data).
- **Behavioural evaluation** (19 scenarios) + unit tests that run without an API key.
- Full **spec-driven documentation** in [`specs/`](specs/MAP.md).

## Demo

TODO(E6): links to the 5 example conversations in [`examples/`](examples/) with one-line descriptions.

## Quickstart

Requirements: Python ≥ 3.11 and an OpenAI API key (or any OpenAI-compatible endpoint).

```bash
git clone https://github.com/<user>/emporio-agent.git && cd emporio-agent
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                    # set OPENAI_API_KEY
python -m emporio build-data                            # builds data/processed/emporio.db
python -m emporio chat                                  # type /debug to see tool calls
```

Other commands:

```bash
pytest                                   # unit + agent-loop tests (no API key needed)
python -m emporio eval                   # live behavioural evaluation -> eval/results.md
python -m emporio tool search_products '{"category": "Violões", "max_price": 1000}'
```

## Architecture

TODO(E7): paste the Mermaid diagram from [`specs/01_ARCHITECTURE.md`](specs/01_ARCHITECTURE.md) §2
and the turn sequence (§3), with a short paragraph.

## Technical decisions

Full rationale with alternatives: [`specs/DECISIONS.md`](specs/DECISIONS.md).

| Topic | Choice | Why (short) |
|---|---|---|
| Agent approach | Native tool calling, hand-written loop | Answers depend on data; the model must see results before writing. Six tools don't need a framework. |
| Retrieval | No RAG — full policy manual in the system prompt | ~8 pages; zero retrieval misses; benefits from prompt caching. RAG when docs grow. |
| Model / provider | `gpt-4o-mini` via OpenAI-compatible client (configurable) | Reliable tool calling, low cost/latency; swap provider via env. |
| Data | Raw CSV → cleaned SQLite (read-only at runtime) | Filters/joins with parameterised SQL; inspectable; reproducible. |
| Money & time rules | Pure Python (`pricing.py`, `store_hours.py`) | Deterministic and unit-tested; the LLM never does arithmetic. |
| Privacy | Verify e-mail/phone before order data | LGPD (manual §9); no enumeration. |
| Memory | SQLite sessions, sliding window | Follow-ups work; sessions survive restarts. |
| Interface | CLI with `/debug` | Fast for evaluators; shows decisions. |
| Prompt strategy | Static prefix (persona, rules, scope, few-shots, manual) + dynamic suffix (now, open/closed) | Cache-friendly, clear separation of behaviour vs context. |

## Data treatment and assumptions

TODO(E7): summary of [`reports/data_quality.md`](reports/data_quality.md) and the main
assumptions from [`specs/02_DATA_FINDINGS.md`](specs/02_DATA_FINDINGS.md) and
[`specs/03_POLICY_NOTES.md`](specs/03_POLICY_NOTES.md) (e.g. two phone numbers in the manual,
installment tiers, empty categories, stale orders). The customer data is fictitious and was
provided with the challenge.

## Evaluation

TODO(E6): pass rate, table of scenarios, cost per run, link to [`eval/results.md`](eval/results.md).

## Known limitations

TODO(E7). Starting list:
- No holiday calendar (manual lists none) — out-of-hours messages use weekday rules only.
- Shipping cost for other cities not computed (needs CEP/weight data).
- Prototype-level identity check (e-mail/phone match), not real authentication.
- English-only docs, Portuguese-only agent.

## What I would do with more time

TODO(E7). Starting list: WhatsApp channel (I've built one in production), summarised long-term
memory, RAG when documents grow, admin view of escalation tickets, CI-run evals on a cheap model,
streaming replies, observability dashboard (handoff rate, tool errors, cost per conversation).

## How I used AI coding assistants

TODO(E7): see the outline in [`specs/epics/E7_DOCS_DELIVERY.md`](specs/epics/E7_DOCS_DELIVERY.md).

## Project structure

```
data/raw/            original challenge files (renamed only)
data/processed/      policies.md (curated) + emporio.db (generated)
reports/             data quality report (generated)
src/emporio/         config, data_loader, policies, pricing, store_hours, tools, prompts, llm, agent, memory, cli, eval
tests/               unit tests + agent loop with a fake LLM
eval/                scenarios and results
examples/            example conversations from real runs
specs/               spec-driven documentation (start at specs/MAP.md)
```
