---
type: epic
epic: E5
status: todo
created: 2026-11-01
estimate: 1.5h
depends_on: [E4]
---

# E5 — Interface and conversation memory

## Goal
A pleasant CLI chat with persistent sessions and a debug view of tool calls.

## Why
Evaluators will run it. Follow-ups ("e em 12x?") need history. `/debug` makes the agent's
decisions visible — the strongest way to show "it knows when to query data vs policies".

## Acceptance criteria
1. WHEN `python -m emporio chat` starts THEN it SHALL create a new session id, show a short
   banner (store name, how to exit, `/debug`) and wait for input.
2. WHEN `--session <id>` is given THEN previous messages SHALL be loaded and the conversation continues.
3. WHEN `/debug` is toggled on THEN each reply SHALL be preceded by the tools called and their
   arguments (and a short result summary).
4. WHEN `/new` is typed THEN a new session starts; `/exit` or Ctrl+C exits cleanly.
5. WHEN the history exceeds `HISTORY_WINDOW` THEN only the most recent messages SHALL be sent,
   **never** starting the window on a `tool` message or splitting a tool-call group.
6. WHEN the database is missing THEN the CLI SHALL print how to build it
   (`python -m emporio build-data`) instead of a stack trace. Same for a missing API key.

## Design notes
- `memory.py`: `append(session_id, messages)`, `load_window(session_id, n)`; stores
  `tool_calls_json` and `tool_call_id` so the exact OpenAI message list can be rebuilt.
- Window algorithm: take last n; while the first message is `tool` or an assistant with
  `tool_calls` whose results are cut, drop from the front.
- `rich` for formatting; replies rendered as Markdown.

## Tasks

| ID | Task | Depends | Commit message | Done when |
|---|---|---|---|---|
| E5-T1 | `memory.py` persistence + windowing | E3-T1 | `feat(memory): persistent sessions with safe history window` | AC5 tests incl. tool-group edge case |
| E5-T2 | `cli.py` chat loop, commands, friendly errors | T1, E4 | `feat(cli): interactive chat with session and debug mode` | AC1–AC4, AC6 by hand |
| E5-T3 | (stretch) Streamlit UI reusing `run_turn` | T2 | `feat(ui): optional streamlit chat` | Only if ahead of schedule |

## Independent test
Chat: "Quanto custa o Yamaha C40?" → "E em 6x?" → the second answer uses the C40 without asking again.
Restart with `--session` and ask "qual era o produto?".
