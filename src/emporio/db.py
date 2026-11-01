"""Database access.

Two databases with opposite permissions, on purpose:

  * `emporio.db`  — the store's operational data, opened **read-only**. A prototype has no
    business writing to it, and the mode is enforced by SQLite rather than by discipline.
  * `app.db`      — what this application produces: chat history and escalation tickets.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from emporio.config import Settings, get_settings


class DatabaseMissingError(RuntimeError):
    """Raised with the command that creates the database, never a bare stack trace."""


APP_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    session_id      TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT,
    tool_calls_json TEXT,
    tool_call_id    TEXT,
    name            TEXT,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    reason     TEXT NOT NULL,
    summary    TEXT NOT NULL,
    order_id   INTEGER,
    created_at TEXT NOT NULL
);
"""


def connect_store(settings: Settings | None = None) -> sqlite3.Connection:
    """Read-only connection to the store data. Writes fail at the SQLite level."""
    settings = settings or get_settings()
    path = settings.db_path
    if not path.exists():
        raise DatabaseMissingError(
            f"{path} does not exist. Build it with:\n\n    python -m emporio build-data\n"
        )
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def connect_app(settings: Settings | None = None) -> sqlite3.Connection:
    """Read-write connection to our own data, creating the schema on first use."""
    settings = settings or get_settings()
    path: Path = settings.app_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(APP_SCHEMA)
    connection.commit()
    return connection
