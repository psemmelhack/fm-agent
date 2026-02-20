"""
tools/memory.py
Reads and writes user memory entries using the database layer.
"""

from db.database import write_memory_to_db, read_memories


def write_memory(event_type: str, summary: str, metadata: dict = None):
    """Write a memory entry."""
    write_memory_to_db(event_type, summary, metadata)


def read_recent_memories(limit: int = 10) -> str:
    """Read recent memories as a formatted string for agent context."""
    rows = read_memories(limit=limit)
    if not rows:
        return "No previous interactions on record."
    entries = []
    for row in rows:
        date = row["created_at"][:10]
        entries.append(f"[{date}] {row['event_type'].upper()}: {row['summary']}")
    return "\n".join(entries)


def read_preferences() -> str:
    """Read preference and activity memories."""
    rows = read_memories(limit=20, types=["preference", "feedback", "attended"])
    if not rows:
        return "No preferences recorded yet."
    entries = []
    for row in rows:
        date = row["created_at"][:10]
        entries.append(f"[{date}] {row['summary']}")
    return "\n".join(entries)
