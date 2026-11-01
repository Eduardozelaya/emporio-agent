---
type: epic
epic: E4
status: todo
created: 2026-11-01
estimate: 3h
depends_on: [E3]
---

# E4 — Agent core (prompt + LLM client + tool loop)

## Goal
A function `run_turn(session_id, user_text) -> Reply` that applies the persona, decides between
answering, calling tools, refusing or escalating, and never hangs, loops forever or invents numbers.

## Why
This is the "AI" of the case and the part the interviews will dig into: how the model decides,
how it is constrained, how failures are handled.

## Scope
- `llm.py`: thin OpenAI-compatible client (base URL, model, timeout, 1 retry, usage capture).
- `prompts.py`: system prompt per [01_ARCHITECTURE](../01_ARCHITECTURE.md) §4.
- `agent.py`: tool loop, fallbacks, turn logging.
- `tests/fakes.py`: scripted fake LLM to test the loop without network.

## Behaviour spec (what the prompt + tools must produce)

| Situation | Expected behaviour |
|---|---|
| Greeting | Greet as the store assistant, offer help (manual §7.2) |
| Product/price/stock/promo question | Call tools; never state these facts without a tool result |
| Value by payment method | Call `quote_price`; never compute |
| Ambiguous product | Ask one clarifying question listing the options |
| Policy question | Answer from the manual in the prompt; no tool |
| Order question without contact | Ask for order number and e-mail/phone first |
| Order `needs_attention` | Do not say "a caminho"; explain and call `escalate_to_human` (`data_inconsistency`) |
| Out of stock / discontinued / coming soon | Say so and suggest available alternatives (§7.3) |
| Accessories | Instruments only; redirect politely; never invent partner stores |
| Empty category (wind, orchestral strings) | "Não temos no catálogo no momento"; suggest contacting the store |
| Unrelated topic | Short friendly refusal + what it can do |
| Prompt injection / request for discount | Refuse; only tool-provided prices exist |
| Complaint, cancel/refund/exchange request, policy edge case, special shipping, "quero um atendente" | Empathy + relevant rule + `escalate_to_human` + tell the ticket and response window |
| Store closed now | Mention when the team is back (dynamic context) when relevant |
| LLM failure / max steps | Fixed safe reply with phone (67) 3341-4444 and hours |

## Acceptance criteria
1. WHEN the fake LLM returns a tool call followed by text THEN `run_turn` SHALL execute the tool,
   append the result, call the LLM again and return the text.
2. WHEN the fake LLM keeps requesting tools THEN `run_turn` SHALL stop at `MAX_TOOL_STEPS` and
   return the safe fallback, logging `max_steps=true`.
3. WHEN the LLM client raises/times out twice THEN `run_turn` SHALL return the safe fallback
   within `2 × LLM_TIMEOUT_S` and log `fallback=true`.
4. WHEN a tool returns an error dict THEN the loop SHALL pass it to the LLM as the tool result (no crash).
5. WHEN the system prompt is built THEN the static part SHALL be byte-identical across turns and
   the dynamic part (now, open/closed) SHALL come last.
6. WHEN a turn ends THEN one JSON line SHALL be appended to `logs/turns.jsonl` with session,
   tools (name + args with e-mail/phone masked), tokens in/out, latency, model, fallback flags.
7. WHEN run against the live model THEN the behaviour table above SHALL hold for the scenarios
   in E6 (validated there).

## Design notes
- Message format: OpenAI chat messages; keep the assistant message with `tool_calls` and each
  `{"role":"tool","tool_call_id":...}` result — required by the API and by memory windowing.
- `Reply` = `{text, tool_calls: [...], usage, fallback: bool}` so the CLI `/debug` can show tools.
- Timeout: pass `timeout=` to the client call (OpenAI Python SDK covers the whole request);
  verify with a fake slow server in a test if time allows. Lesson from StayBot: a provider can
  return headers and never send the body — make sure the timeout covers the full response.
- Prompt few-shots: 3 tiny examples (accessory refusal, Takamine clarification, complaint escalation).
- Keep prompts in Python constants (versioned, diffable); note prompt changes in commit messages.

## Tasks

| ID | Task | Depends | Commit message | Done when |
|---|---|---|---|---|
| E4-T1 | `llm.py` client wrapper + settings + usage capture | E0 | `feat(llm): openai-compatible client with timeout and retry` | Unit test with mocked SDK |
| E4-T2 | `prompts.py` static sections + policies + dynamic suffix | E1, E2 | `feat(prompt): store persona, rules, scope and policies` | Test AC5; manual read-through |
| E4-T3 | `agent.run_turn` loop + fallbacks | T1, T2, E3 | `feat(agent): tool-calling loop with guards` | AC1–AC4 with fake LLM |
| E4-T4 | Turn logging with PII masking | T3 | `feat(agent): structured turn logs` | AC6 test |
| E4-T5 | Live smoke run (5 questions from the spec) and first prompt tuning | T3 | `chore(prompt): tune after first live run` | Notes in PAUSE_WORK |

## Independent test
`pytest tests/test_agent.py` green; then `python -m emporio chat` (after E5) or a tiny script
calling `run_turn` with "Quanto custa o Takamine GD20?".
