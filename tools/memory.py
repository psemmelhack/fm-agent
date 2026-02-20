"""
tools/memory.py
Reads and writes user memory entries.
Keeps a running log of Peter's preferences and past activity.
"""

import os
import json
from datetime import datetime
from db.database import get_connection


def write_memory(event_type: str, summary: str, metadata: dict = None):
    """
    Write a memory entry to the database.
    
    event_type: 'preference', 'attended', 'skipped', 'feedback'
    summary:    plain English description of what happened
    metadata:   optional dict with extra details (event name, location, etc.)
    """
    conn = get_connection()
    conn.execute("""
        INSERT INTO memories (event_type, summary, metadata, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        event_type,
        summary,
        json.dumps(metadata or {}),
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def read_recent_memories(limit: int = 10) -> str:
    """
    Read the most recent memory entries as a formatted string
    suitable for injecting into an agent's context.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT event_type, summary, created_at 
        FROM memories 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    if not rows:
        return "No previous interactions on record."

    entries = []
    for row in rows:
        date = row["created_at"][:10]  # just the date part
        entries.append(f"[{date}] {row['event_type'].upper()}: {row['summary']}")

    return "\n".join(entries)


def read_preferences() -> str:
    """
    Read only 'preference' and 'feedback' memories —
    the ones that reflect what Peter actually likes.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT summary, created_at 
        FROM memories 
        WHERE event_type IN ('preference', 'feedback', 'attended')
        ORDER BY created_at DESC 
        LIMIT 20
    """).fetchall()
    conn.close()

    if not rows:
        return "No preferences recorded yet."

    entries = []
    for row in rows:
        date = row["created_at"][:10]
        entries.append(f"[{date}] {row['summary']}")

    return "\n".join(entries)
