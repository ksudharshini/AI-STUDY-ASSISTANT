"""
Conversation memory. Stored in SQLite (not just server RAM) so a student's
history survives a server restart -- it's keyed on the session_id kept in
their signed browser cookie.
"""

from datetime import datetime, timezone

from db import get_conn


def add_message(session_id, role, content):
    conn = get_conn()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_history(session_id, limit=20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    conn.close()
    history = [dict(r) for r in rows]
    return history[-limit:]


def clear_history(session_id):
    conn = get_conn()
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
