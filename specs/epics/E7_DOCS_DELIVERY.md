---
type: epic
epic: E7
status: todo
created: 2026-11-01
estimate: 2.5h
depends_on: [E6]
---

# E7 — Documentation and delivery

## Goal
A README that answers every item the challenge asks for, a submission PDF, and a frozen,
tagged repository before the deadline.

## Acceptance criteria
1. WHEN an evaluator follows README §Quickstart on a clean machine THEN they SHALL reach a working
   chat in ≤ 5 minutes (Python, venv, install, `.env`, build-data, chat).
2. WHEN the README is read THEN it SHALL contain: overview, demo links to `examples/`,
   quickstart, architecture (diagram), technical decisions (framework, LLM/provider, retrieval,
   prompt strategy, tools, memory, data treatment, interface), assumptions, evaluation results,
   known limitations, what I'd do with more time, **how I used AI coding assistants**, project
   structure, link to `specs/`.
3. WHEN the repo is scanned for secrets (gitleaks or `git log -p | grep -E "sk-|api_key"`) THEN
   nothing SHALL be found.
4. WHEN the PDF is generated THEN it SHALL be named
   `Eduardo Zelaya - AI Engineer – Full-Stack para Aplicações com IA Generativa.pdf`, be in
   English, and contain the repo link plus a one-page summary.
5. WHEN the deadline passes THEN no commit SHALL exist after tag `v1.0-submission`.

## The "How I used AI coding assistants" section (draft outline)
Be specific and honest — the challenge says it can count positively.
- **Tools:** Claude (chat) for analysis and planning; Claude Code for implementation.
- **Workflow:** spec-driven — (1) analysed the challenge, data and manual with Claude; (2) wrote
  specs (`specs/`: project spec, architecture, data findings, policy notes, decisions, 8 epics
  with EARS acceptance criteria); (3) implemented epic by epic with Claude Code, task by task,
  one commit per task; (4) reviewed every diff, ran tests, and asked for explanations of anything
  unclear before committing; (5) used live evaluation to drive prompt changes.
- **What I decided myself:** <list the decisions you own, e.g. tool calling vs intent JSON based
  on my production bot, no RAG, privacy verification, money in code>.
- **What the assistant did:** <boilerplate, test tables, first drafts of docs>.
- **Where I corrected it:** <real examples collected in PAUSE_WORK during the build>.
- **Prior experience:** production WhatsApp agent (StayBot) with provider fallback chain and
  timeouts — lessons reused here.

## Tasks

| ID | Task | Depends | Commit message | Done when |
|---|---|---|---|---|
| E7-T1 | Full README (replace stub; Mermaid diagram from 01_ARCHITECTURE) | E6 | `docs: complete README` | AC2 checklist ticked |
| E7-T2 | AI usage section with real examples from PAUSE_WORK | T1 | `docs: describe AI-assisted workflow` | Section reviewed by me |
| E7-T3 | Fresh-clone run-through + secret scan + `pytest` + `ruff` | T1 | `chore: final verification` (only if fixes) | AC1, AC3 |
| E7-T4 | Submission PDF (summary + link) | T3 | — (not committed) | AC4 |
| E7-T5 | Tag `v1.0-submission`, push, submit Google Form, reply to the e-mail | T4 | `git tag v1.0-submission` | Confirmation received |

## Final checklist
- [ ] Repo public, default branch up to date, tag pushed
- [ ] `examples/` has 5 files; README links them
- [ ] `eval/results.md` committed
- [ ] `reports/data_quality.md` committed
- [ ] `.env.example` complete; no `.env` in history
- [ ] PDF uploaded via Google Forms (logged in with a Gmail account)
- [ ] E-mail reply to Tatielle with the repo link
- [ ] No commits after the deadline
