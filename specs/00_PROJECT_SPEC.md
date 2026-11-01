---
type: spec
status: approved
phase: meta
created: 2026-11-01
updated: 2026-11-01
---

# 00 — Project Spec: Empório da Música customer service agent

> Source of truth for **what** we build and **why**. Architecture (the **how**) lives in
> [01_ARCHITECTURE](01_ARCHITECTURE.md). Each epic in `specs/epics/` refines one slice of this spec.

## Problem Statement

Empório da Música is a (fictional) musical instrument store in Campo Grande/MS. All customer
service is done by a small team that is overloaded with repetitive questions: opening hours,
order status, product price and availability, return rules. The store wants a **prototype of a
text-message agent** that helps the team by answering these questions with accurate data and the
store's own policies, while handing off to a human what it should not resolve alone.

The store provided operational tables (`data/raw/*.csv`) and an internal customer-service
policy manual (`data/raw/store_policies.pdf`).

## Goals

- [ ] Customers get correct answers about **products, prices, availability, promotions and
      order status**, always sourced from the data (never invented).
- [ ] Customers get correct answers about **store policies** (hours, payments, returns,
      shipping, warranty), consistent with the manual.
- [ ] The agent speaks with the **store's persona and tone** (manual §7.1).
- [ ] The agent **handles out-of-scope requests** gracefully and **escalates** to a human when
      the manual says so.
- [ ] The solution is **simple, reproducible and explainable**: one command to build the data,
      one command to chat, one command to test.
- [ ] Every technical decision is **justified** in the README and in [DECISIONS](DECISIONS.md).

## Case requirements → traceability

Every requirement from the challenge PDF maps to an epic and to evidence an evaluator can check.

| # | Requirement (challenge PDF) | Epic | Evidence |
|---|---|---|---|
| R1 | Python as main language | E0 | `pyproject.toml`, `src/emporio/` |
| R2 | Persona aligned with the store's identity and tone | E4 | `src/emporio/prompts.py`, examples |
| R3 | Receive and answer messages based on the provided context | E4, E5 | `agent.py`, `cli.py` |
| R4 | Know when to query **data** (availability, prices, order status) | E3, E4 | `tools.py`, scenario tests |
| R5 | Know when to query **policies** (returns, hours, payments) | E1, E4 | `data/processed/policies.md` in prompt, scenario tests |
| R6 | Handle out-of-scope questions properly | E4, E6 | prompt scope section, out-of-scope scenarios |
| D1 | Framework / agent approach — justified | E4 | README §Technical decisions, DECISIONS D1 |
| D2 | Model and provider — justified | E4 | README, DECISIONS D3 |
| D3 | Interaction interface — justified | E5 | README, DECISIONS D6 |
| D4 | Conversation history persistence (if it makes sense) | E5 | `memory.py`, DECISIONS D7 |
| D5 | Data treatment as judged necessary | E1 | `data_loader.py`, `reports/data_quality.md`, [02_DATA_FINDINGS](02_DATA_FINDINGS.md) |
| X1 | Public Git repo with **real commit history**, no single force-push, frozen after deadline | E0–E7 | git log, tag `v1.0-submission` |
| X2 | README: how to run (env, provider, commands) | E7 | README §Quickstart |
| X3 | README: technical decision rationale | E7 | README §Technical decisions |
| X4 | README: known limitations + what with more time | E7 | README §Limitations |
| X5 | README: AI coding assistant usage and workflow | E7 | README §How I used AI assistants |
| X6 | 3–5 example conversations (.md/.txt/image), varied, ≥1 non-trivial | E6 | `examples/*.md` |
| X7 | Ambiguities: assume, document, move on | all | [03_POLICY_NOTES](03_POLICY_NOTES.md), [02_DATA_FINDINGS](02_DATA_FINDINGS.md), README §Assumptions |

Submission (from the recruiter e-mail): PDF named
`Eduardo Zelaya - AI Engineer – Full-Stack para Aplicações com IA Generativa.pdf`, **in English**,
via Google Forms, containing the repository link. Also reply to the e-mail with the link (the
challenge PDF asks for that). Deadline target: **Tue 2026-11-03 23:59 BRT** (safe reading; see
DECISIONS D0).

## Users and scenarios

| Actor | Need |
|---|---|
| Customer (end user) | Ask about products, prices, promotions, orders, policies in Portuguese via text |
| Store team (indirect) | Receive escalated cases with a summary; spend less time on repetitive questions |
| Evaluator (Artefact) | Run the project quickly, read the reasoning, see the agent handle varied scenarios |

Reference scenarios (from the challenge PDF + our analysis):

1. "Quais opções de violões disponíveis custando até R$1000?" — catalog query
2. "Qual o endereço da loja?" — general store info (policy)
3. "Quanto custa o Takamine GD20?" — price query
4. "Me arrependi da minha compra, posso devolver meu pedido?" — policy + order data
5. "Vocês vendem cabo/encordoamento?" — out of scope (accessories, manual §1 and §7.1)
6. "Cadê meu pedido 8?" — order status with identity verification and stale-status detection
7. "Quero falar com um atendente" / complaint — human escalation (manual §7.3)

## Out of Scope

| Feature | Reason |
|---|---|
| Real channel integration (WhatsApp, web widget) | Challenge says the interface is free; focus is the agent working correctly. Listed as future work. |
| Placing, cancelling or refunding orders | No such data or authority given; the agent informs and escalates. |
| Shipping cost calculation for other cities | Manual says it depends on CEP, weight and dimensions — no data for it. Agent explains the rule. |
| Writing to the operational data | Read-only prototype. Only tickets and chat history are written. |
| Multi-store / multi-tenant | Single store. Mentioned as future work. |
| RAG / vector store | Manual is ~8 pages and fits in the prompt (DECISIONS D2). |
| Authentication of customers beyond order e-mail/phone match | Prototype-level verification is enough to show the privacy concern. |
| Holiday calendar | Manual lists none; documented limitation. |

## Non-functional requirements

- **Accuracy over fluency:** any price, stock, discount, installment or order fact in a reply
  must come from a tool result. Money math lives in code (`pricing.py`).
- **Privacy (LGPD, manual §9):** order data is only shown after the requester matches the order's
  e-mail or phone; the LLM never receives the customer table.
- **Resilience:** LLM call has a total timeout; on failure the user gets a safe fixed message
  with the store phone and hours. The tool loop has a max-steps limit.
- **Reproducibility:** `make`-style commands (or documented `python -m` commands) rebuild the
  database from raw files idempotently. A configurable "today" date makes examples and tests
  deterministic.
- **Cost awareness:** tokens per turn are logged.
- **Language:** the agent talks to customers in **Brazilian Portuguese**; all repository
  documentation is in **English** (recruiter requirement).

## Success criteria (definition of done for the whole project)

- [ ] `pytest` green without any API key (LLM mocked).
- [ ] Live scenario evaluation (`python -m emporio.eval`) passes the core scenarios with a real key.
- [ ] 5 example conversations committed, generated from real runs.
- [ ] README answers every X2–X5 item; an evaluator can run the agent in < 5 minutes.
- [ ] Repo public, history shows incremental progress, tag `v1.0-submission` before the deadline.
