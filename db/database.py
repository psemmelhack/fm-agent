"""
db/database.py
PostgreSQL state management, event storage, and memory.
Uses DATABASE_URL from Railway environment.
Falls back to SQLite for local development if DATABASE_URL is not set.
"""

import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = DATABASE_URL is not None

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    print("Using PostgreSQL")
else:
    import sqlite3
    print("Using SQLite (local dev)")


# ── Connection ────────────────────────────────────────────────────────────────

def get_connection():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        DB_PATH = os.path.join(os.path.dirname(__file__), "fm_agent.db")
        conn = __import__('sqlite3').connect(DB_PATH)
        conn.row_factory = __import__('sqlite3').Row
        return conn


def fetchone_as_dict(cursor, row):
    """Convert a postgres row to a dict."""
    if row is None:
        return None
    cols = [desc[0] for desc in cursor.description]
    return dict(zip(cols, row))


def fetchall_as_dict(cursor, rows):
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db():
    conn = get_connection()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversation_state (
                id SERIAL PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'idle',
                last_message TEXT,
                search_results TEXT,
                updated_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS saved_events (
                id SERIAL PRIMARY KEY,
                event_name TEXT NOT NULL,
                event_location TEXT,
                event_start_time TEXT,
                reminder_sent INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id SERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT
            )
        """)
        c.execute("SELECT COUNT(*) FROM conversation_state")
        if c.fetchone()[0] == 0:
            c.execute(
                "INSERT INTO conversation_state (state, updated_at) VALUES ('idle', %s)",
                (datetime.now().isoformat(),)
            )
    else:
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversation_state (
                id INTEGER PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'idle',
                last_message TEXT,
                search_results TEXT,
                updated_at TEXT
            )
        """)
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
        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT
            )
        """)
        c.execute("SELECT COUNT(*) FROM conversation_state")
        if c.fetchone()[0] == 0:
            c.execute(
                "INSERT INTO conversation_state (state, updated_at) VALUES ('idle', ?)",
                (datetime.now().isoformat(),)
            )

    conn.commit()
    conn.close()
    print("Database initialized.")


# ── State ─────────────────────────────────────────────────────────────────────

def get_state():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM conversation_state WHERE id = 1")
    row = c.fetchone()
    conn.close()
    if row is None:
        return {}
    if USE_POSTGRES:
        return fetchone_as_dict(c, row)
    return dict(row)


def set_state(state: str, last_message: str = None, search_results: str = None):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute(
            "UPDATE conversation_state SET state=%s, last_message=%s, search_results=%s, updated_at=%s WHERE id=1",
            (state, last_message, search_results, now)
        )
    else:
        c.execute(
            "UPDATE conversation_state SET state=?, last_message=?, search_results=?, updated_at=? WHERE id=1",
            (state, last_message, search_results, now)
        )
    conn.commit()
    conn.close()


# ── Events ────────────────────────────────────────────────────────────────────

def save_event(event_name: str, event_location: str, event_start_time: str):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute(
            "INSERT INTO saved_events (event_name, event_location, event_start_time, created_at) VALUES (%s,%s,%s,%s)",
            (event_name, event_location, event_start_time, now)
        )
    else:
        c.execute(
            "INSERT INTO saved_events (event_name, event_location, event_start_time, created_at) VALUES (?,?,?,?)",
            (event_name, event_location, event_start_time, now)
        )
    conn.commit()
    conn.close()
    print(f"Event saved: {event_name}")


def get_unreminded_events():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM saved_events WHERE reminder_sent = 0")
    rows = c.fetchall()
    conn.close()

    if USE_POSTGRES:
        rows = fetchall_as_dict(c, rows)
    else:
        rows = [dict(r) for r in rows]

    upcoming = []
    now = datetime.now()
    for row in rows:
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
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("UPDATE saved_events SET reminder_sent=1 WHERE id=%s", (event_id,))
    else:
        c.execute("UPDATE saved_events SET reminder_sent=1 WHERE id=?", (event_id,))
    conn.commit()
    conn.close()


# ── Memories ──────────────────────────────────────────────────────────────────

def write_memory_to_db(event_type: str, summary: str, metadata: dict = None):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    meta = json.dumps(metadata or {})
    if USE_POSTGRES:
        c.execute(
            "INSERT INTO memories (event_type, summary, metadata, created_at) VALUES (%s,%s,%s,%s)",
            (event_type, summary, meta, now)
        )
    else:
        c.execute(
            "INSERT INTO memories (event_type, summary, metadata, created_at) VALUES (?,?,?,?)",
            (event_type, summary, meta, now)
        )
    conn.commit()
    conn.close()


def read_memories(limit: int = 10, types: list = None) -> list:
    conn = get_connection()
    c = conn.cursor()
    if types:
        placeholders = ','.join(['%s' if USE_POSTGRES else '?' for _ in types])
        query = f"SELECT event_type, summary, created_at FROM memories WHERE event_type IN ({placeholders}) ORDER BY created_at DESC LIMIT {'%s' if USE_POSTGRES else '?'}"
        c.execute(query, types + [limit])
    else:
        param = '%s' if USE_POSTGRES else '?'
        c.execute(f"SELECT event_type, summary, created_at FROM memories ORDER BY created_at DESC LIMIT {param}", (limit,))

    rows = c.fetchall()
    conn.close()

    if USE_POSTGRES:
        return fetchall_as_dict(c, rows)
    return [dict(r) for r in rows]


# ── Family Members ────────────────────────────────────────────────────────────

def init_family_tables(conn=None):
    """Add family member and estate tables. Call after init_db()."""
    close = conn is None
    if conn is None:
        conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'

    if USE_POSTGRES:
        c.execute("""
            CREATE TABLE IF NOT EXISTS estates (
                id SERIAL PRIMARY KEY,
                deceased_name TEXT NOT NULL,
                executor_name TEXT NOT NULL,
                executor_email TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS family_members (
                id SERIAL PRIMARY KEY,
                estate_id INTEGER REFERENCES estates(id),
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                role TEXT DEFAULT 'member',
                join_code TEXT UNIQUE,
                status TEXT DEFAULT 'invited',
                invited_at TEXT,
                joined_at TEXT,
                last_nudge_at TEXT
            )
        """)
    else:
        c.execute("""
            CREATE TABLE IF NOT EXISTS estates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deceased_name TEXT NOT NULL,
                executor_name TEXT NOT NULL,
                executor_email TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS family_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estate_id INTEGER REFERENCES estates(id),
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                role TEXT DEFAULT 'member',
                join_code TEXT UNIQUE,
                status TEXT DEFAULT 'invited',
                invited_at TEXT,
                joined_at TEXT,
                last_nudge_at TEXT
            )
        """)

    conn.commit()
    if close:
        conn.close()


def create_estate(deceased_name: str, executor_name: str, executor_email: str) -> int:
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute(
            "INSERT INTO estates (deceased_name, executor_name, executor_email, created_at) VALUES (%s,%s,%s,%s) RETURNING id",
            (deceased_name, executor_name, executor_email, now)
        )
        estate_id = c.fetchone()[0]
    else:
        c.execute(
            "INSERT INTO estates (deceased_name, executor_name, executor_email, created_at) VALUES (?,?,?,?)",
            (deceased_name, executor_name, executor_email, now)
        )
        estate_id = c.lastrowid
    conn.commit()
    conn.close()
    return estate_id


def add_family_member(estate_id: int, name: str, email: str, role: str = "member") -> str:
    """Add a family member and generate their unique join code."""
    import random
    import string
    join_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    now = datetime.now().isoformat()
    conn = get_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute(
            "INSERT INTO family_members (estate_id, name, email, role, join_code, invited_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (estate_id, name, email, role, join_code, now)
        )
    else:
        c.execute(
            "INSERT INTO family_members (estate_id, name, email, role, join_code, invited_at) VALUES (?,?,?,?,?,?)",
            (estate_id, name, email, role, join_code, now)
        )
    conn.commit()
    conn.close()
    return join_code


def get_pending_members(estate_id: int) -> list:
    """Get family members who haven't joined yet."""
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    c.execute(f"SELECT * FROM family_members WHERE estate_id={p} AND status='invited'", (estate_id,))
    rows = c.fetchall()
    conn.close()
    if USE_POSTGRES:
        cols = [desc[0] for desc in c.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]


def get_all_members(estate_id: int) -> list:
    """Get all family members for an estate."""
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    c.execute(f"SELECT * FROM family_members WHERE estate_id={p}", (estate_id,))
    rows = c.fetchall()
    conn.close()
    if USE_POSTGRES:
        cols = [desc[0] for desc in c.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]


def mark_member_joined(join_code: str):
    """Mark a family member as having joined."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    p = '%s' if USE_POSTGRES else '?'
    c.execute(
        f"UPDATE family_members SET status='joined', joined_at={p} WHERE join_code={p}",
        (now, join_code)
    )
    conn.commit()
    conn.close()
