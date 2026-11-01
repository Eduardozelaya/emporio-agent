# CLAUDE.md

Guidance for Claude Code in this repository. The human owner is Eduardo; he must be able to
explain every line in a technical interview, so **clarity beats cleverness**.

## What this project is

A Python prototype of a customer-service agent for "Empório da Música" (fictional instrument
store), built for the Artefact AI Engineer technical challenge. Agent replies in **pt-BR**; all
code, comments, docs and commit messages in **English**.

## Before doing anything

1. Read `specs/MAP.md`, then `specs/PAUSE_WORK.md`, then the active epic in `specs/epics/`.
2. Work on **one task ID at a time** (e.g. `E1-T3`). Do not start the next task without approval.
3. If a spec is ambiguous or wrong, stop and say so — propose a spec change; don't silently diverge.

## Workflow per task (spec-driven)

1. **Plan:** restate the task's acceptance criteria and list the files you will touch.
2. **Test first where practical:** write/extend tests from the epic's test table or oracle
   (`specs/02_DATA_FINDINGS.md` §7).
3. **Implement** the smallest code that passes.
4. **Verify:** `ruff check . && pytest` must be green.
5. **Explain back** (always): in ≤ 10 lines, what changed, why, and one thing Eduardo should
   understand or could be asked about in an interview.
6. **Commit** with the message given in the epic table (Conventional Commits). One task = one
   commit. Never `git push --force`. Never amend pushed commits.
7. **Update** the task status in the epic file and add a line to `specs/PAUSE_WORK.md`.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m emporio build-data          # raw CSV/PDF -> data/processed/emporio.db (+ report)
python -m emporio chat [--session ID] # interactive agent (needs OPENAI_API_KEY)
python -m emporio tool <name> '<json>' # call a tool directly (debug)
python -m emporio eval                # live scenario evaluation (needs key)
ruff check . && pytest                # must be green before every commit
```

## Architecture rules (see specs/01_ARCHITECTURE.md)

- The LLM **never** touches data directly; only tools in `tools.py` read data.
- **All money math in `pricing.py`**, all time rules in `store_hours.py` — pure functions, table tests.
- Tools return dicts; errors are `{"error": code, "message": hint}` — never raise into the loop.
- Order data only after e-mail/phone verification (`get_order_status`); same error for
  "not found" and "wrong contact".
- System prompt: static prefix first (persona, rules, scope, examples, policies), dynamic suffix last.
- `data/raw/` is read-only. Generated DBs are gitignored; `policies.md`, reports and eval results are committed.
- Use `config.now()` everywhere instead of `datetime.now()` (honours `EMPORIO_TODAY`).

## Style

- Python ≥ 3.11, type hints, small functions, docstrings on public functions (1–3 lines).
- Pydantic v2 for tool arguments and structured results.
- No frameworks for the agent (no LangChain/LlamaIndex) — DECISIONS D1.
- Prefer readable SQL with parameters (`?`), never f-strings with user input.
- Tests: pytest, table-driven (`@pytest.mark.parametrize`), no network (fake LLM in `tests/fakes.py`).

## Never

- Commit `.env`, keys, or `*.db` files. If a secret is ever printed in a diff, stop and tell Eduardo.
- Invent data facts in prompts or examples; facts come from the data or the manual.
- Edit example conversations' agent text by hand (they must come from real runs).
- Add dependencies without saying why in the explain-back.
