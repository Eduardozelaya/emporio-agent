---
type: epic
epic: E0
status: done
created: 2026-11-01
estimate: 1h
depends_on: []
---

# E0 — Foundation

## Goal
A public repository that installs, lints and tests from the first hour, with the raw data and the
specs in place, and **no secret ever committed**.

## Why first
The challenge evaluates commit history. Starting clean (gitignore, env template, CI) avoids the
worst mistake (leaking a key in a public repo) and gives every later epic a place to land.

## Scope
- Repo skeleton, `pyproject.toml`, `src/emporio/` package, `config.py`.
- Raw files copied to `data/raw/` with clean names ([02_DATA_FINDINGS](../02_DATA_FINDINGS.md) §1).
- `specs/`, `CLAUDE.md`, README stub.
- GitHub Actions: ruff + pytest.

**Out:** any business logic.

## Acceptance criteria
1. WHEN someone clones the repo and runs `pip install -e ".[dev]"` on Python ≥ 3.11 THEN install SHALL succeed.
2. WHEN `ruff check .` and `pytest` run THEN both SHALL pass (a placeholder test is fine).
3. WHEN `.env` exists locally THEN git SHALL ignore it (`.gitignore` covers `.env`, `*.db`, `logs/`, `.venv/`).
4. WHEN `config.py` is imported without `OPENAI_API_KEY` THEN it SHALL NOT fail (key is only required when the LLM is called).
5. WHEN a push reaches GitHub THEN CI SHALL run ruff + pytest without any secret.

## Design notes
- Dependencies: `openai`, `pydantic>=2`, `pandas`, `pypdf`, `rich`, `python-dotenv`, `pyyaml`.
  Dev: `pytest`, `ruff`.
- `config.py`: a frozen dataclass `Settings` loaded from env with defaults from
  [01_ARCHITECTURE](../01_ARCHITECTURE.md) §8; `now()` helper honours `EMPORIO_TODAY`
  (timezone `America/Campo_Grande`).
- Entry point: `python -m emporio` → subcommands added in later epics (`build-data`, `chat`, `eval`).

## Tasks

| ID | Task | Depends | Commit message | Done when |
|---|---|---|---|---|
| E0-T1 | Create public GitHub repo `emporio-agent`; add `.gitignore`, `.env.example`, README stub, MIT license | — | `chore: initial repository skeleton` | Repo public, first commit pushed |
| E0-T2 | Add `specs/` and `CLAUDE.md` from the kit | T1 | `docs: add spec-driven project documentation` | Files on GitHub |
| E0-T3 | `pyproject.toml`, `src/emporio/__init__.py`, `__main__.py` (argparse stub), `config.py` with `Settings` + `now()` | T1 | `chore: python package setup and settings module` | `python -m emporio --help` works |
| E0-T4 | Copy raw files to `data/raw/` with clean names | T1 | `data: add raw challenge files with normalized names` | 6 CSV + 1 PDF in `data/raw/` |
| E0-T5 | `tests/test_config.py` (defaults, `EMPORIO_TODAY` override) + GitHub Actions workflow | T3 | `ci: lint and test workflow` | CI green on GitHub |

## Independent test
Fresh clone in a new folder → `pip install -e ".[dev]" && ruff check . && pytest` → green.
