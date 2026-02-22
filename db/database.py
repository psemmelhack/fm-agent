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


# ── Tabulator Tables ──────────────────────────────────────────────────────────

def init_tabulator_tables():
    """Add inventory and claims tables."""
    conn = get_connection()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            CREATE TABLE IF NOT EXISTS inventory_items (
                id SERIAL PRIMARY KEY,
                estate_id INTEGER REFERENCES estates(id),
                name TEXT NOT NULL,
                description TEXT,
                location TEXT,
                category TEXT,
                estimated_value NUMERIC DEFAULT 0,
                appraised_value NUMERIC,
                status TEXT DEFAULT 'unclaimed',
                photo_url TEXT,
                notes TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id SERIAL PRIMARY KEY,
                item_id INTEGER REFERENCES inventory_items(id),
                estate_id INTEGER REFERENCES estates(id),
                member_id INTEGER REFERENCES family_members(id),
                member_name TEXT,
                claim_type TEXT DEFAULT 'want',
                priority INTEGER DEFAULT 1,
                note TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                resolved_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS distributions (
                id SERIAL PRIMARY KEY,
                item_id INTEGER REFERENCES inventory_items(id),
                estate_id INTEGER REFERENCES estates(id),
                member_id INTEGER REFERENCES family_members(id),
                member_name TEXT,
                estimated_value NUMERIC DEFAULT 0,
                distribution_method TEXT,
                distributed_at TEXT
            )
        """)
    else:
        c.execute("""
            CREATE TABLE IF NOT EXISTS inventory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estate_id INTEGER,
                name TEXT NOT NULL,
                description TEXT,
                location TEXT,
                category TEXT,
                estimated_value NUMERIC DEFAULT 0,
                appraised_value NUMERIC,
                status TEXT DEFAULT 'unclaimed',
                photo_url TEXT,
                notes TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                estate_id INTEGER,
                member_id INTEGER,
                member_name TEXT,
                claim_type TEXT DEFAULT 'want',
                priority INTEGER DEFAULT 1,
                note TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                resolved_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS distributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                estate_id INTEGER,
                member_id INTEGER,
                member_name TEXT,
                estimated_value NUMERIC DEFAULT 0,
                distribution_method TEXT,
                distributed_at TEXT
            )
        """)

    conn.commit()
    conn.close()


def add_item(estate_id: int, name: str, description: str = None,
             location: str = None, category: str = None,
             estimated_value: float = 0) -> int:
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute("""
            INSERT INTO inventory_items
            (estate_id, name, description, location, category, estimated_value, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (estate_id, name, description, location, category, estimated_value, now, now))
        item_id = c.fetchone()[0]
    else:
        c.execute("""
            INSERT INTO inventory_items
            (estate_id, name, description, location, category, estimated_value, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (estate_id, name, description, location, category, estimated_value, now, now))
        item_id = c.lastrowid
    conn.commit()
    conn.close()
    return item_id


def add_claim(item_id: int, estate_id: int, member_id: int,
              member_name: str, claim_type: str = "want",
              priority: int = 1, note: str = None) -> int:
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute("""
            INSERT INTO claims
            (item_id, estate_id, member_id, member_name, claim_type, priority, note, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (item_id, estate_id, member_id, member_name, claim_type, priority, note, now))
        claim_id = c.fetchone()[0]
    else:
        c.execute("""
            INSERT INTO claims
            (item_id, estate_id, member_id, member_name, claim_type, priority, note, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (item_id, estate_id, member_id, member_name, claim_type, priority, note, now))
        claim_id = c.lastrowid
    conn.commit()
    conn.close()
    return claim_id


def get_item_claims(item_id: int) -> list:
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    c.execute(f"SELECT * FROM claims WHERE item_id={p} AND status='pending'", (item_id,))
    rows = c.fetchall()
    conn.close()
    if USE_POSTGRES:
        cols = [desc[0] for desc in c.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]


def get_estate_inventory(estate_id: int, status: str = None) -> list:
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    if status:
        c.execute(f"SELECT * FROM inventory_items WHERE estate_id={p} AND status={p}", (estate_id, status))
    else:
        c.execute(f"SELECT * FROM inventory_items WHERE estate_id={p}", (estate_id,))
    rows = c.fetchall()
    conn.close()
    if USE_POSTGRES:
        cols = [desc[0] for desc in c.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]


def resolve_claim(item_id: int, winner_member_id: int,
                  winner_name: str, method: str, value: float = 0):
    """Mark an item as distributed to a specific family member."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    p = '%s' if USE_POSTGRES else '?'

    # Update item status
    c.execute(f"UPDATE inventory_items SET status='distributed', updated_at={p} WHERE id={p}", (now, item_id))

    # Mark all claims resolved
    c.execute(f"UPDATE claims SET status='resolved', resolved_at={p} WHERE item_id={p}", (now, item_id))

    # Get estate_id
    c.execute(f"SELECT estate_id FROM inventory_items WHERE id={p}", (item_id,))
    row = c.fetchone()
    estate_id = row[0] if row else None

    # Record distribution
    if estate_id:
        if USE_POSTGRES:
            c.execute("""
                INSERT INTO distributions
                (item_id, estate_id, member_id, member_name, estimated_value, distribution_method, distributed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (item_id, estate_id, winner_member_id, winner_name, value, method, now))
        else:
            c.execute("""
                INSERT INTO distributions
                (item_id, estate_id, member_id, member_name, estimated_value, distribution_method, distributed_at)
                VALUES (?,?,?,?,?,?,?)
            """, (item_id, estate_id, winner_member_id, winner_name, value, method, now))

    conn.commit()
    conn.close()


def get_fairness_summary(estate_id: int) -> list:
    """Return total estimated value distributed per family member."""
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    c.execute(f"""
        SELECT member_name,
               COUNT(*) as item_count,
               COALESCE(SUM(estimated_value), 0) as total_value
        FROM distributions
        WHERE estate_id={p}
        GROUP BY member_name
        ORDER BY total_value DESC
    """, (estate_id,))
    rows = c.fetchall()
    conn.close()
    if USE_POSTGRES:
        cols = [desc[0] for desc in c.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]


# ── Audit Log & Intent Notes ──────────────────────────────────────────────────

def init_audit_tables():
    """Add audit_log and intent_notes tables."""
    conn = get_connection()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                estate_id INTEGER,
                item_id INTEGER,
                action_type TEXT NOT NULL,
                actor_id INTEGER,
                actor_name TEXT NOT NULL,
                public_summary TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS intent_notes (
                id SERIAL PRIMARY KEY,
                item_id INTEGER NOT NULL,
                estate_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                member_name TEXT NOT NULL,
                content TEXT NOT NULL,
                visibility TEXT NOT NULL DEFAULT 'private',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
    else:
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estate_id INTEGER,
                item_id INTEGER,
                action_type TEXT NOT NULL,
                actor_id INTEGER,
                actor_name TEXT NOT NULL,
                public_summary TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS intent_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                estate_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                member_name TEXT NOT NULL,
                content TEXT NOT NULL,
                visibility TEXT NOT NULL DEFAULT 'private',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

    conn.commit()
    conn.close()


def write_audit(
    estate_id: int,
    actor_name: str,
    action_type: str,
    public_summary: str,
    item_id: int = None,
    actor_id: int = None,
    metadata: dict = None
):
    """
    Write an audit log entry.
    public_summary is always visible to all family members.
    metadata is JSON — structured data about the action (never sensitive).
    """
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    meta = json.dumps(metadata or {})
    if USE_POSTGRES:
        c.execute("""
            INSERT INTO audit_log
            (estate_id, item_id, action_type, actor_id, actor_name, public_summary, metadata, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (estate_id, item_id, action_type, actor_id, actor_name, public_summary, meta, now))
    else:
        c.execute("""
            INSERT INTO audit_log
            (estate_id, item_id, action_type, actor_id, actor_name, public_summary, metadata, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (estate_id, item_id, action_type, actor_id, actor_name, public_summary, meta, now))
    conn.commit()
    conn.close()


def get_audit_log(estate_id: int, item_id: int = None, limit: int = 50) -> list:
    """
    Get audit log entries for an estate or a specific item.
    Always returns only public_summary — never metadata contents that are private.
    """
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    if item_id:
        c.execute(f"""
            SELECT actor_name, action_type, public_summary, created_at
            FROM audit_log
            WHERE estate_id={p} AND item_id={p}
            ORDER BY created_at ASC
            LIMIT {p}
        """, (estate_id, item_id, limit))
    else:
        c.execute(f"""
            SELECT actor_name, action_type, public_summary, created_at
            FROM audit_log
            WHERE estate_id={p}
            ORDER BY created_at DESC
            LIMIT {p}
        """, (estate_id, limit))
    rows = c.fetchall()
    conn.close()
    if USE_POSTGRES:
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]


def add_intent_note(
    item_id: int,
    estate_id: int,
    member_id: int,
    member_name: str,
    content: str
) -> int:
    """
    Add a private intent note. Always starts as 'private'.
    Content is never written to the audit log.
    The audit log only records that a note was added.
    """
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute("""
            INSERT INTO intent_notes
            (item_id, estate_id, member_id, member_name, content, visibility, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,'private',%s,%s) RETURNING id
        """, (item_id, estate_id, member_id, member_name, content, now, now))
        note_id = c.fetchone()[0]
    else:
        c.execute("""
            INSERT INTO intent_notes
            (item_id, estate_id, member_id, member_name, content, visibility, created_at, updated_at)
            VALUES (?,?,?,?,'private',?,?)
        """, (item_id, estate_id, member_id, member_name, content, now, now))
        note_id = c.lastrowid
    conn.commit()
    conn.close()

    # Audit: records existence only — never content
    write_audit(
        estate_id=estate_id,
        item_id=item_id,
        actor_id=member_id,
        actor_name=member_name,
        action_type='note_added',
        public_summary=f"{member_name} added a private note."
    )

    return note_id


def set_note_visibility(
    note_id: int,
    member_id: int,
    member_name: str,
    estate_id: int,
    item_id: int,
    new_visibility: str
):
    """
    Change the visibility of an intent note.
    Only the author (member_id) can change visibility.
    new_visibility: 'private' | 'mediator' | 'morris' | 'public'
    Visibility changes are always audited.
    """
    valid = {'private', 'mediator', 'morris', 'public'}
    if new_visibility not in valid:
        raise ValueError(f"Invalid visibility: {new_visibility}")

    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    p = '%s' if USE_POSTGRES else '?'

    # Verify ownership
    c.execute(f"SELECT member_id FROM intent_notes WHERE id={p}", (note_id,))
    row = c.fetchone()
    if not row or row[0] != member_id:
        conn.close()
        raise PermissionError("Only the author can change note visibility.")

    c.execute(
        f"UPDATE intent_notes SET visibility={p}, updated_at={p} WHERE id={p}",
        (new_visibility, now, note_id)
    )
    conn.commit()
    conn.close()

    # Audit the visibility change — no content revealed
    labels = {
        'private': 'made their note private',
        'mediator': 'shared their note with the Mediator',
        'morris': 'shared their note with Morris',
        'public': 'shared their note publicly'
    }
    write_audit(
        estate_id=estate_id,
        item_id=item_id,
        actor_id=member_id,
        actor_name=member_name,
        action_type='visibility_changed',
        public_summary=f"{member_name} {labels[new_visibility]}.",
        metadata={"note_id": note_id, "new_visibility": new_visibility}
    )


def get_intent_notes(
    item_id: int,
    member_id: int,
    is_morris: bool = False,
    is_mediator: bool = False
) -> list:
    """
    Get intent notes for an item, filtered by what this viewer is allowed to see.
    - member sees: their own notes (all visibilities) + public notes from others
    - morris sees: own notes + public + morris-visible notes
    - mediator sees: own notes + public + mediator-visible notes
    Content is never returned for notes the viewer isn't authorized to see.
    """
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    c.execute(f"""
        SELECT id, member_id, member_name, content, visibility, created_at
        FROM intent_notes
        WHERE item_id={p}
        ORDER BY created_at ASC
    """, (item_id,))
    rows = c.fetchall()
    conn.close()

    if USE_POSTGRES:
        cols = [d[0] for d in c.description]
        notes = [dict(zip(cols, r)) for r in rows]
    else:
        notes = [dict(r) for r in rows]

    result = []
    for note in notes:
        is_author = note['member_id'] == member_id
        vis = note['visibility']

        can_read = (
            is_author or
            vis == 'public' or
            (is_morris and vis == 'morris') or
            (is_mediator and vis == 'mediator')
        )

        if can_read:
            result.append(note)
        # If not authorized, don't include — not even a redacted version
        # The audit log already surfaces that a note exists

    return result


# ── Item Suggestions ──────────────────────────────────────────────────────────

def init_suggestions_table():
    """Add item_suggestions table for executor review workflow."""
    conn = get_connection()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            CREATE TABLE IF NOT EXISTS item_suggestions (
                id SERIAL PRIMARY KEY,
                estate_id INTEGER NOT NULL,
                suggested_by_id INTEGER NOT NULL,
                suggested_by_name TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                location TEXT,
                category TEXT,
                estimated_value NUMERIC DEFAULT 0,
                photo_url TEXT,
                suggester_note TEXT,
                status TEXT DEFAULT 'pending',
                reviewed_by TEXT,
                reviewer_note TEXT,
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            )
        """)
    else:
        c.execute("""
            CREATE TABLE IF NOT EXISTS item_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estate_id INTEGER NOT NULL,
                suggested_by_id INTEGER NOT NULL,
                suggested_by_name TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                location TEXT,
                category TEXT,
                estimated_value NUMERIC DEFAULT 0,
                photo_url TEXT,
                suggester_note TEXT,
                status TEXT DEFAULT 'pending',
                reviewed_by TEXT,
                reviewer_note TEXT,
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            )
        """)

    conn.commit()
    conn.close()


def add_suggestion(
    estate_id: int,
    suggested_by_id: int,
    suggested_by_name: str,
    name: str,
    description: str = None,
    location: str = None,
    category: str = None,
    estimated_value: float = 0,
    photo_url: str = None,
    suggester_note: str = None
) -> int:
    """Add an item suggestion for executor review."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute("""
            INSERT INTO item_suggestions
            (estate_id, suggested_by_id, suggested_by_name, name, description,
             location, category, estimated_value, photo_url, suggester_note, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (estate_id, suggested_by_id, suggested_by_name, name, description,
              location, category, estimated_value, photo_url, suggester_note, now))
        suggestion_id = c.fetchone()[0]
    else:
        c.execute("""
            INSERT INTO item_suggestions
            (estate_id, suggested_by_id, suggested_by_name, name, description,
             location, category, estimated_value, photo_url, suggester_note, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (estate_id, suggested_by_id, suggested_by_name, name, description,
              location, category, estimated_value, photo_url, suggester_note, now))
        suggestion_id = c.lastrowid
    conn.commit()
    conn.close()
    return suggestion_id


def get_pending_suggestions(estate_id: int) -> list:
    """Get all pending suggestions for an estate."""
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    c.execute(f"""
        SELECT * FROM item_suggestions
        WHERE estate_id={p} AND status='pending'
        ORDER BY created_at ASC
    """, (estate_id,))
    rows = c.fetchall()
    conn.close()
    if USE_POSTGRES:
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]


def approve_suggestion(
    suggestion_id: int,
    reviewed_by: str,
    name: str,
    description: str,
    location: str,
    category: str,
    estimated_value: float,
    reviewer_note: str = None
) -> int:
    """
    Approve a suggestion — updates the suggestion record and
    creates the item in inventory. Returns the new item_id.
    """
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    p = '%s' if USE_POSTGRES else '?'

    # Get suggestion
    c.execute(f"SELECT * FROM item_suggestions WHERE id={p}", (suggestion_id,))
    row = c.fetchone()
    if USE_POSTGRES:
        cols = [d[0] for d in c.description]
        suggestion = dict(zip(cols, row))
    else:
        suggestion = dict(row)

    # Mark approved
    c.execute(f"""
        UPDATE item_suggestions
        SET status='approved', reviewed_by={p}, reviewer_note={p}, reviewed_at={p}
        WHERE id={p}
    """, (reviewed_by, reviewer_note, now, suggestion_id))

    conn.commit()
    conn.close()

    # Add to inventory
    item_id = add_item(
        estate_id=suggestion['estate_id'],
        name=name,
        description=description,
        location=location,
        category=category,
        estimated_value=estimated_value
    )

    # Update photo_url if present
    if suggestion.get('photo_url'):
        conn2 = get_connection()
        c2 = conn2.cursor()
        c2.execute(f"UPDATE inventory_items SET photo_url={p} WHERE id={p}",
                   (suggestion['photo_url'], item_id))
        conn2.commit()
        conn2.close()

    # Audit entries
    write_audit(
        estate_id=suggestion['estate_id'],
        item_id=item_id,
        actor_name=suggestion['suggested_by_name'],
        action_type='item_suggested',
        public_summary=f"{suggestion['suggested_by_name']} suggested '{name}' for the inventory.",
        metadata={"suggestion_id": suggestion_id}
    )
    write_audit(
        estate_id=suggestion['estate_id'],
        item_id=item_id,
        actor_name=reviewed_by,
        action_type='item_approved',
        public_summary=f"{reviewed_by} approved '{name}' — added to the inventory.",
        metadata={"suggestion_id": suggestion_id, "reviewer_note": reviewer_note}
    )

    return item_id


def reject_suggestion(
    suggestion_id: int,
    reviewed_by: str,
    reviewer_note: str = None
):
    """Reject a suggestion with an optional note."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    p = '%s' if USE_POSTGRES else '?'

    c.execute(f"SELECT estate_id, suggested_by_name, name FROM item_suggestions WHERE id={p}",
              (suggestion_id,))
    row = c.fetchone()
    estate_id, suggested_by_name, name = row[0], row[1], row[2]

    c.execute(f"""
        UPDATE item_suggestions
        SET status='rejected', reviewed_by={p}, reviewer_note={p}, reviewed_at={p}
        WHERE id={p}
    """, (reviewed_by, reviewer_note, now, suggestion_id))
    conn.commit()
    conn.close()

    write_audit(
        estate_id=estate_id,
        actor_name=reviewed_by,
        action_type='suggestion_rejected',
        public_summary=f"{reviewed_by} did not add '{name}' to the inventory.",
        metadata={"suggestion_id": suggestion_id, "suggested_by": suggested_by_name}
    )
