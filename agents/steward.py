"""
agents/steward.py
The Steward — FM's timeline manager.

Runs on a schedule. Watches the estate against its milestone plan.
Writes alerts to timeline_alerts for Morris to surface each morning.
Never talks to the executor directly — reports to Morris.
"""

from datetime import datetime, timedelta
from db.database import (
    get_connection, USE_POSTGRES,
    get_schedule, get_milestones, complete_milestone,
    write_alert, resolve_alert_type, get_active_alerts,
    get_pending_suggestions, get_all_members
)


# ── Thresholds ────────────────────────────────────────────────────────────────

THRESHOLDS = {
    "member_invite_warning_days":    7,    # warn if invited but not joined
    "member_invite_critical_days":   14,   # escalate
    "suggestion_review_warning_days": 2,   # pending suggestion not reviewed
    "suggestion_review_critical_days": 5,
    "conflict_warning_days":          5,   # conflict sitting unresolved
    "conflict_critical_days":         10,
    "milestone_warning_days":         5,   # milestone due soon
    "milestone_overdue_days":         0,   # milestone past target date
}


# ── Estate state reader ───────────────────────────────────────────────────────

def read_estate_state(estate_id: int) -> dict:
    """Pull all time-relevant estate facts into one dict."""
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    now_str = datetime.now().isoformat()

    # Members
    c.execute(f"""
        SELECT name, email, role, status, invited_at, joined_at
        FROM family_members WHERE estate_id={p}
    """, (estate_id,))
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    members = [dict(zip(cols, r)) for r in rows]

    # Inventory
    c.execute(f"""
        SELECT COUNT(*) FROM inventory_items WHERE estate_id={p}
    """, (estate_id,))
    total_items = c.fetchone()[0]

    # Conflicts (items with 2+ pending claims)
    if USE_POSTGRES:
        c.execute(f"""
            SELECT i.id, i.name, MIN(cl.created_at) as oldest_claim
            FROM inventory_items i
            JOIN claims cl ON cl.item_id = i.id
            WHERE i.estate_id={p} AND cl.status='pending' AND i.status != 'distributed'
            GROUP BY i.id, i.name HAVING COUNT(cl.id) > 1
        """, (estate_id,))
    else:
        c.execute(f"""
            SELECT i.id, i.name, MIN(cl.created_at) as oldest_claim
            FROM inventory_items i
            JOIN claims cl ON cl.item_id = i.id
            WHERE i.estate_id={p} AND cl.status='pending' AND i.status != 'distributed'
            GROUP BY i.id, i.name HAVING COUNT(cl.id) > 1
        """, (estate_id,))
    rows = c.fetchall()
    conflicts = [{'id': r[0], 'name': r[1], 'oldest_claim': r[2]} for r in rows]

    # Pending suggestions
    c.execute(f"""
        SELECT id, name, suggested_by_name, created_at
        FROM item_suggestions WHERE estate_id={p} AND status='pending'
    """, (estate_id,))
    rows = c.fetchall()
    pending_suggestions = [
        {'id': r[0], 'name': r[1], 'by': r[2], 'created_at': r[3]}
        for r in rows
    ]

    conn.close()

    return {
        'members': members,
        'total_items': total_items,
        'conflicts': conflicts,
        'pending_suggestions': pending_suggestions,
        'now': datetime.now(),
    }


# ── Individual checks ─────────────────────────────────────────────────────────

def check_uninvited_members(estate_id: int, state: dict):
    """Flag members who were invited but haven't joined."""
    now = state['now']
    warning_days  = THRESHOLDS['member_invite_warning_days']
    critical_days = THRESHOLDS['member_invite_critical_days']

    for m in state['members']:
        if m['status'] != 'invited' or not m.get('invited_at'):
            continue

        try:
            invited = datetime.fromisoformat(m['invited_at'])
        except Exception:
            continue

        days_waiting = (now - invited).days

        if days_waiting >= critical_days:
            write_alert(
                estate_id=estate_id,
                alert_type='member_not_joined',
                severity='warning',
                message=f"{m['name']} has not joined after {days_waiting} days.",
                detail=f"Invited: {m['invited_at'][:10]}. Email: {m['email']}. "
                       f"Consider a personal call or checking if the email is correct."
            )
        elif days_waiting >= warning_days:
            write_alert(
                estate_id=estate_id,
                alert_type='member_not_joined',
                severity='info',
                message=f"{m['name']} has not joined yet ({days_waiting} days since invitation).",
                detail=f"Invited: {m['invited_at'][:10]}. A gentle reminder may help."
            )


def check_conflicts(estate_id: int, state: dict):
    """Flag conflicts that have been sitting unresolved too long."""
    now = state['now']
    warning_days  = THRESHOLDS['conflict_warning_days']
    critical_days = THRESHOLDS['conflict_critical_days']

    for conflict in state['conflicts']:
        if not conflict.get('oldest_claim'):
            continue
        try:
            since = datetime.fromisoformat(conflict['oldest_claim'])
        except Exception:
            continue

        days_open = (now - since).days

        if days_open >= critical_days:
            write_alert(
                estate_id=estate_id,
                alert_type='conflict_unresolved',
                severity='critical',
                message=f"Conflict on \"{conflict['name']}\" has been unresolved for {days_open} days.",
                detail="Multiple claimants are waiting for a decision. This needs attention soon."
            )
        elif days_open >= warning_days:
            write_alert(
                estate_id=estate_id,
                alert_type='conflict_unresolved',
                severity='warning',
                message=f"Conflict on \"{conflict['name']}\" has been open for {days_open} days.",
                detail="Consider initiating a resolution — lottery, mediation, or executor decision."
            )


def check_pending_suggestions(estate_id: int, state: dict):
    """Flag suggestions sitting in the review queue too long."""
    now = state['now']
    warning_days  = THRESHOLDS['suggestion_review_warning_days']
    critical_days = THRESHOLDS['suggestion_review_critical_days']

    for s in state['pending_suggestions']:
        try:
            created = datetime.fromisoformat(s['created_at'])
        except Exception:
            continue

        days_waiting = (now - created).days

        if days_waiting >= critical_days:
            write_alert(
                estate_id=estate_id,
                alert_type='suggestion_unreviewed',
                severity='warning',
                message=f"\"{s['name']}\" (suggested by {s['by']}) has been waiting {days_waiting} days for review.",
                detail="Family members may be waiting on this before they can make claims."
            )
        elif days_waiting >= warning_days:
            write_alert(
                estate_id=estate_id,
                alert_type='suggestion_unreviewed',
                severity='info',
                message=f"\"{s['name']}\" suggested by {s['by']} is awaiting your review.",
                detail=f"Submitted {s['created_at'][:10]}."
            )


def check_milestones(estate_id: int):
    """Flag upcoming or overdue milestones."""
    now = datetime.now()
    warning_days = THRESHOLDS['milestone_warning_days']
    milestones = get_milestones(estate_id)

    for m in milestones:
        if m['status'] == 'complete' or not m.get('target_date'):
            continue

        try:
            target = datetime.fromisoformat(m['target_date'])
        except Exception:
            continue

        days_until = (target - now).days

        if days_until < 0:
            write_alert(
                estate_id=estate_id,
                alert_type='milestone_overdue',
                severity='critical',
                message=f"Milestone overdue: \"{m['label']}\" was due {abs(days_until)} days ago.",
                detail=f"Target date was {m['target_date'][:10]}."
            )
        elif days_until <= warning_days:
            write_alert(
                estate_id=estate_id,
                alert_type='milestone_upcoming',
                severity='info',
                message=f"Milestone due in {days_until} day{'s' if days_until != 1 else ''}: \"{m['label']}\".",
                detail=f"Target date: {m['target_date'][:10]}."
            )


def check_inactivity(estate_id: int):
    """Flag if the estate has gone quiet for too long."""
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'

    c.execute(f"""
        SELECT created_at FROM audit_log
        WHERE estate_id={p}
        ORDER BY created_at DESC LIMIT 1
    """, (estate_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return

    try:
        last_activity = datetime.fromisoformat(row[0])
    except Exception:
        return

    days_quiet = (datetime.now() - last_activity).days
    if days_quiet >= 7:
        write_alert(
            estate_id=estate_id,
            alert_type='inactivity',
            severity='info',
            message=f"No estate activity for {days_quiet} days.",
            detail="It may be worth reaching out to the family to keep things moving."
        )


# ── Auto-complete milestones based on real data ───────────────────────────────

def auto_complete_milestones(estate_id: int, state: dict):
    """
    Automatically mark milestones complete when the data shows they are.
    """
    milestones = {m['key']: m for m in get_milestones(estate_id)}

    # family_joined — all members have joined
    if 'family_joined' in milestones and milestones['family_joined']['status'] != 'complete':
        all_joined = all(
            m['status'] == 'joined'
            for m in state['members']
            if m['role'] != 'executor'
        )
        if all_joined and state['members']:
            complete_milestone(estate_id, 'family_joined',
                               notes="All family members joined automatically detected.")

    # inventory_complete — executor manually marks this; no auto-complete

    # conflicts_resolved — no active conflicts
    if 'conflicts_resolved' in milestones and milestones['conflicts_resolved']['status'] != 'complete':
        if not state['conflicts']:
            # Only auto-complete if claims period has closed
            claims_closed = milestones.get('claims_closed', {}).get('status') == 'complete'
            if claims_closed:
                complete_milestone(estate_id, 'conflicts_resolved',
                                   notes="No active conflicts detected.")


# ── Main entry point ──────────────────────────────────────────────────────────

def run_steward(estate_id: int):
    """
    Full Steward sweep for one estate.
    Resolves stale alerts, checks current state, writes fresh alerts.
    Called daily by scheduler and on-demand.
    """
    print(f"Steward sweeping estate {estate_id}...")

    # Clear stale resolved alert types before re-evaluating
    # (prevents duplicate alerts piling up across runs)
    for alert_type in [
        'member_not_joined', 'conflict_unresolved',
        'suggestion_unreviewed', 'milestone_overdue',
        'milestone_upcoming', 'inactivity'
    ]:
        resolve_alert_type(estate_id, alert_type)

    state = read_estate_state(estate_id)

    check_uninvited_members(estate_id, state)
    check_conflicts(estate_id, state)
    check_pending_suggestions(estate_id, state)
    check_milestones(estate_id)
    check_inactivity(estate_id)
    auto_complete_milestones(estate_id, state)

    alerts = get_active_alerts(estate_id)
    print(f"Steward complete — {len(alerts)} active alert(s).")
    return alerts


def format_alerts_for_morris(alerts: list) -> str:
    """
    Render active alerts as a plain-English block for Morris's briefing context.
    Morris reads this and decides how to surface each item in his own voice.
    """
    if not alerts:
        return "No time-sensitive alerts from the Steward."

    critical = [a for a in alerts if a['severity'] == 'critical']
    warnings  = [a for a in alerts if a['severity'] == 'warning']
    info      = [a for a in alerts if a['severity'] == 'info']

    lines = ["Steward alerts:"]

    if critical:
        lines.append("URGENT:")
        for a in critical:
            lines.append(f"  ⚠ {a['message']}")
            if a.get('detail'):
                lines.append(f"    → {a['detail']}")

    if warnings:
        lines.append("Needs attention:")
        for a in warnings:
            lines.append(f"  • {a['message']}")
            if a.get('detail'):
                lines.append(f"    → {a['detail']}")

    if info:
        lines.append("FYI:")
        for a in info:
            lines.append(f"  – {a['message']}")

    return '\n'.join(lines)
