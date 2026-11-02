"""Conversation history, persisted per session.

Follow-ups are the whole point: "e em 12x?" only means something if the previous turn is
still there. Sessions live in `app.db`, so they survive a restart (DECISIONS D7).

The subtle part is the window. Tool calls travel as a **group**: one assistant message that
requests them, then one `tool` message per result. Cutting a window in the middle of a group
leaves an orphan `tool` message, and the API rejects the whole request. `load_window` never
returns one.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from emporio.config import Settings, get_settings, now
from emporio.db import connect_app


def new_session_id() -> str:
    """Short, readable, unique enough for a prototype's sessions."""
    return uuid.uuid4().hex[:12]


def append(
    session_id: str, messages: list[dict[str, Any]], settings: Settings | None = None
) -> None:
    """Store the messages of one turn, keeping their order."""
    if not messages:
        return
    settings = settings or get_settings()
    created = now().isoformat()
    with connect_app(settings) as connection:
        row = connection.execute(
            "SELECT COALESCE(MAX(seq), 0) AS last FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        seq = row["last"]
        for message in messages:
            seq += 1
            tool_calls = message.get("tool_calls")
            connection.execute(
                "INSERT INTO messages "
                "(session_id, seq, role, content, tool_calls_json, tool_call_id, name, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    seq,
                    message["role"],
                    message.get("content"),
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    message.get("tool_call_id"),
                    message.get("name"),
                    created,
                ),
            )
        connection.commit()


def _row_to_message(row: Any) -> dict[str, Any]:
    message: dict[str, Any] = {"role": row["role"], "content": row["content"]}
    if row["tool_calls_json"]:
        message["tool_calls"] = json.loads(row["tool_calls_json"])
    if row["tool_call_id"]:
        message["tool_call_id"] = row["tool_call_id"]
    if row["name"] and row["role"] == "tool":
        message["name"] = row["name"]
    return message


def trim_to_valid_window(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop any half tool-call group at either end of a window.

    A `tool` message whose requesting assistant message was cut is an orphan, and the API
    rejects the request outright. The same goes for an assistant that asks for tools whose
    results are not there.
    """
    window = list(messages)

    # Front: orphan results whose request was cut off.
    while window and window[0].get("role") == "tool":
        window.pop(0)

    # Back: a request whose results were cut off.
    while window:
        last = window[-1]
        if last.get("role") == "assistant" and last.get("tool_calls"):
            window.pop()
            continue
        break

    return window


def load_window(
    session_id: str, limit: int | None = None, settings: Settings | None = None
) -> list[dict[str, Any]]:
    """The most recent messages of a session, in wire format, safe to send as-is."""
    settings = settings or get_settings()
    limit = settings.history_window if limit is None else limit
    if limit <= 0:
        return []
    with connect_app(settings) as connection:
        rows = connection.execute(
            "SELECT * FROM (SELECT * FROM messages WHERE session_id = ? ORDER BY seq DESC "
            "LIMIT ?) ORDER BY seq ASC",
            (session_id, limit),
        ).fetchall()
    return trim_to_valid_window([_row_to_message(row) for row in rows])


def message_count(session_id: str, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    with connect_app(settings) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()
    return row["n"]


def list_sessions(settings: Settings | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Recent sessions, newest first, for `--session` to be usable at all."""
    settings = settings or get_settings()
    with connect_app(settings) as connection:
        rows = connection.execute(
            "SELECT session_id, COUNT(*) AS messages, MAX(created_at) AS last_at "
            "FROM messages GROUP BY session_id ORDER BY last_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
