"""Persistance SQLite des conversations et des tickets (données de démo)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    intent TEXT,
    status TEXT NOT NULL DEFAULT 'bot',
    summary TEXT,
    transcript TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    type TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normale',
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ouvert',
    suggested_response TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tickets_conversation ON tickets(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_transcript(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        transcript = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return transcript if isinstance(transcript, list) else []


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with _db() as connection:
        connection.executescript(SCHEMA)


def ensure_conversation(session_id: str) -> None:
    now = _now()
    with _db() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO conversations (id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, now, now),
        )


def append_message(session_id: str, role: str, text: str) -> None:
    ensure_conversation(session_id)
    now = _now()
    with _db() as connection:
        # BEGIN IMMEDIATE sérialise les écritures concurrentes : sans cela, deux
        # requêtes peuvent lire le même transcript et perdre un message.
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT transcript FROM conversations WHERE id = ?", (session_id,)
        ).fetchone()
        transcript = _load_transcript(row["transcript"] if row else None)
        transcript.append({"role": role, "text": text, "at": now})
        connection.execute(
            "UPDATE conversations SET transcript = ?, updated_at = ? WHERE id = ?",
            (json.dumps(transcript, ensure_ascii=False), now, session_id),
        )


def update_conversation(
    session_id: str,
    *,
    intent: str | None = None,
    status: str | None = None,
    summary: str | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if intent is not None:
        fields.append("intent = ?")
        values.append(intent)
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if summary is not None:
        fields.append("summary = ?")
        values.append(summary)
    if not fields:
        return
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(session_id)
    with _db() as connection:
        connection.execute(
            f"UPDATE conversations SET {', '.join(fields)} WHERE id = ?", values
        )


def _row_to_conversation(row: sqlite3.Row, connection: sqlite3.Connection) -> dict[str, Any]:
    transcript = _load_transcript(row["transcript"])
    ticket_row = connection.execute(
        "SELECT * FROM tickets WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    ticket = dict(ticket_row) if ticket_row else None
    last_message = transcript[-1].get("text", "") if transcript and isinstance(transcript[-1], dict) else ""
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "intent": row["intent"],
        "status": row["status"],
        "summary": row["summary"] or "",
        "transcript": transcript,
        "last_message": last_message,
        "ticket": ticket,
    }


def get_conversation(session_id: str) -> dict[str, Any] | None:
    with _db() as connection:
        row = connection.execute(
            "SELECT * FROM conversations WHERE id = ?", (session_id,)
        ).fetchone()
        return _row_to_conversation(row, connection) if row else None


def get_ticket(ticket_id: str) -> dict[str, Any] | None:
    with _db() as connection:
        row = connection.execute(
            "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        return dict(row) if row else None


def find_open_ticket(conversation_id: str, ticket_type: str | None = None) -> dict[str, Any] | None:
    query = "SELECT * FROM tickets WHERE conversation_id = ? AND status = 'ouvert'"
    values: list[Any] = [conversation_id]
    if ticket_type:
        query += " AND type = ?"
        values.append(ticket_type)
    query += " ORDER BY created_at DESC LIMIT 1"
    with _db() as connection:
        row = connection.execute(query, values).fetchone()
        return dict(row) if row else None


def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
    with _db() as connection:
        rows = connection.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_conversation(row, connection) for row in rows]


def create_ticket(
    conversation_id: str,
    ticket_type: str,
    summary: str,
    *,
    priority: str = "normale",
    suggested_response: str = "",
) -> dict[str, Any]:
    now = _now()
    year = datetime.now().year
    prefix = f"REC-{year}-"
    with _db() as connection:
        # Le verrou est pris avant de calculer le numéro pour éviter deux
        # tickets identiques lorsque deux appels arrivent en même temps.
        connection.execute("BEGIN IMMEDIATE")
        last_number = connection.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(id, ?) AS INTEGER)), 0) "
            "FROM tickets WHERE id LIKE ?",
            (len(prefix) + 1, f"{prefix}%"),
        ).fetchone()[0]
        ticket_id = f"{prefix}{int(last_number) + 1:03d}"
        connection.execute(
            """
            INSERT INTO tickets (id, conversation_id, type, priority, summary, status, suggested_response, created_at)
            VALUES (?, ?, ?, ?, ?, 'ouvert', ?, ?)
            """,
            (ticket_id, conversation_id, ticket_type, priority, summary, suggested_response, now),
        )
        row = connection.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return dict(row)


def list_tickets(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with _db() as connection:
        if status:
            rows = connection.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM tickets ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]


def resolve_ticket(ticket_id: str) -> bool:
    with _db() as connection:
        cursor = connection.execute(
            "UPDATE tickets SET status = 'resolu' WHERE id = ?", (ticket_id,)
        )
        return cursor.rowcount > 0


def stats() -> dict[str, Any]:
    with _db() as connection:
        total = connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        bot_handled = connection.execute(
            "SELECT COUNT(*) FROM conversations WHERE status = 'bot'"
        ).fetchone()[0]
        escalated = connection.execute(
            "SELECT COUNT(*) FROM conversations WHERE status = 'escalated'"
        ).fetchone()[0]
        open_tickets = connection.execute(
            "SELECT COUNT(*) FROM tickets WHERE status = 'ouvert'"
        ).fetchone()[0]
        resolved_tickets = connection.execute(
            "SELECT COUNT(*) FROM tickets WHERE status = 'resolu'"
        ).fetchone()[0]
        by_intent_rows = connection.execute(
            "SELECT COALESCE(intent, 'autre') AS intent, COUNT(*) AS count "
            "FROM conversations GROUP BY COALESCE(intent, 'autre') ORDER BY count DESC"
        ).fetchall()
        return {
            "total_conversations": total,
            "bot_handled": bot_handled,
            "escalated": escalated,
            "open_tickets": open_tickets,
            "resolved_tickets": resolved_tickets,
            "by_intent": [dict(row) for row in by_intent_rows],
        }
