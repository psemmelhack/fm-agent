"""
db/database.py
SQLite state management, event storage, and memory.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "fm_agent.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    # Conversation state machine
    c.execute("""
        CREATE TABLE IF NOT EXISTS conversation_state (
            id INTEGER PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'idle',
            last_message TEXT,
            search_results TEXT,
            updated_at TEXT
        )
    """)

    # Saved events for reminders
    c.execute("""
        CREATE TABLE IF NOT EXISTS saved_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            event_location TEXT,
            event_start_time TEXT,
            reminder_sent INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    # Memory — persistent log of preferences and activity
    c.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT
        )
    """)

    # Seed conversation state if empty
    c.execute("SELECT COUNT(*) FROM conversation_state")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO conversation_state (state, updated_at) VALUES ('idle', ?)",
            (datetime.now().isoformat(),)
        )

    conn.commit()
    conn.close()
    print("Database initialized.")


def get_state():
    conn = get_connection()
    row = conn.execute("SELECT * FROM conversation_state WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else {}


def set_state(state: str, last_message: str = None, search_results: str = None):
    conn = get_connection()
    conn.execute(
        "UPDATE conversation_state SET state=?, last_message=?, search_results=?, updated_at=? WHERE id=1",
        (state, last_message, search_results, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def save_event(event_name: str, event_location: str, event_start_time: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO saved_events (event_name, event_location, event_start_time, created_at) VALUES (?,?,?,?)",
        (event_name, event_location, event_start_time, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    print(f"Event saved: {event_name} at {event_start_time}")


def get_unreminded_events():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM saved_events WHERE reminder_sent = 0").fetchall()
    conn.close()

    upcoming = []
    now = datetime.now()
    for row in rows:
        row = dict(row)
        try:
            event_time = datetime.fromisoformat(row["event_start_time"])
            minutes_until = (event_time - now).total_seconds() / 60
            if 0 < minutes_until <= 65:
                upcoming.append(row)
        except Exception:
            pass
    return upcoming


def mark_reminder_sent(event_id: int):
    conn = get_connection()
    conn.execute("UPDATE saved_events SET reminder_sent=1 WHERE id=?", (event_id,))
    conn.commit()
    conn.close()
