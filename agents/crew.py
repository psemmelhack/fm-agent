"""
agents/crew.py
Morris — FM's estate coordinator.
Speaks with the executor via Telegram.
Knows the full state of the estate at all times.
"""

import os
from datetime import datetime, timedelta
from crewai import Agent, Task, Crew
from crewai.tools import tool
from dotenv import load_dotenv

from tools.telegram import send_message
from tools.memory import write_memory, read_recent_memories
from agents.steward import run_steward, format_alerts_for_morris
from db.database import (
    get_state, set_state,
    get_pending_suggestions,
    get_all_members,
    get_audit_log,
    get_connection, USE_POSTGRES,
    get_schedule, get_milestones, get_active_alerts,
    init_schedule_tables
)

load_dotenv()

MORRIS_CHARACTER = """
You are Morris, the estate coordinator for Family Matter.

You work closely with the executor — the person responsible for shepherding
the estate through distribution. You are their trusted advisor and daily
briefer. You know everything happening across the estate: who has joined,
what's been claimed, what's in dispute, what needs the executor's attention.

Your character:
- You greet the executor as if they've just walked into your office —
  genuinely glad to see them, never performatively so.
- You are expert and organized. You've read the ledger. You know what's
  outstanding. You surface the right things without overwhelming.
- You are specific. Not "there are some disputes" but "the grandfather clock
  has two claimants — Jane and Peter — and it's been sitting unresolved for
  three days."
- You have judgment. You know what's urgent, what can wait, and what you can
  handle yourself without bothering the executor.
- You never oversell a problem. If something is minor, you say so. If
  something needs a decision today, you're clear about that too.
- You can be disagreed with. If the executor says "leave it for now," you
  accept that and move on.
- You are unhurried but efficient. This is Telegram — brief and purposeful.
- You sign off as Morris, never as "your FM assistant."

Your voice:
- Warm but professional
- Confident and direct
- Personal — you know this family's story
- Occasionally a light touch of dry wit, never at anyone's expense
- Never corporate, never robotic, never sycophantic

What Morris never does:
- Never says "Certainly!" or "Absolutely!" or "Great choice!"
- Never uses bullet points — use plain sentences instead
- Never starts a message with "I"
- Never makes the executor feel like they're talking to software
- Never writes more than 8-10 sentences in a single message
"""


def make_llm():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model="claude-sonnet-4-5",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.7
    )


# ── Estate context builder ────────────────────────────────────────────────────

def build_estate_context(estate_id: int) -> dict:
    """
    Pull the full current state of the estate into a structured dict.
    Morris reads this before every briefing or conversation.
    """
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'

    # Family members
    c.execute(f"""
        SELECT name, email, role, status, invited_at, joined_at
        FROM family_members WHERE estate_id={p}
        ORDER BY role, name
    """, (estate_id,))
    rows = c.fetchall()
    if USE_POSTGRES:
        cols = [d[0] for d in c.description]
        members = [dict(zip(cols, r)) for r in rows]
    else:
        members = [dict(r) for r in rows]

    not_joined = [m for m in members if m['status'] == 'invited']
    joined = [m for m in members if m['status'] == 'joined']

    # Inventory
    c.execute(f"""
        SELECT id, name, status, category, estimated_value
        FROM inventory_items WHERE estate_id={p}
    """, (estate_id,))
    rows = c.fetchall()
    if USE_POSTGRES:
        cols = [d[0] for d in c.description]
        items = [dict(zip(cols, r)) for r in rows]
    else:
        items = [dict(r) for r in rows]

    total_items = len(items)
    distributed = sum(1 for i in items if i['status'] == 'distributed')
    unclaimed = sum(1 for i in items if i['status'] == 'unclaimed')

    # Active conflicts (items with 2+ pending claims)
    c.execute(f"""
        SELECT i.id, i.name,
               array_agg(cl.member_name) as claimants
        FROM inventory_items i
        JOIN claims cl ON cl.item_id = i.id
        WHERE i.estate_id={p} AND cl.status='pending' AND i.status != 'distributed'
        GROUP BY i.id, i.name
        HAVING COUNT(cl.id) > 1
        ORDER BY COUNT(cl.id) DESC
    """ if USE_POSTGRES else f"""
        SELECT i.id, i.name,
               GROUP_CONCAT(cl.member_name, ', ') as claimants
        FROM inventory_items i
        JOIN claims cl ON cl.item_id = i.id
        WHERE i.estate_id={p} AND cl.status='pending' AND i.status != 'distributed'
        GROUP BY i.id, i.name
        HAVING COUNT(cl.id) > 1
        ORDER BY COUNT(cl.id) DESC
    """, (estate_id,))
    rows = c.fetchall()
    conflicts = [
        {'id': r[0], 'name': r[1], 'claimants': r[2]}
        for r in rows
    ]

    # Pending suggestions
    c.execute(f"""
        SELECT name, suggested_by_name, created_at
        FROM item_suggestions
        WHERE estate_id={p} AND status='pending'
        ORDER BY created_at ASC
    """, (estate_id,))
    rows = c.fetchall()
    pending_suggestions = [
        {'name': r[0], 'suggested_by': r[1], 'created_at': r[2]}
        for r in rows
    ]

    # Recent audit activity (last 24 hours)
    yesterday = (datetime.now() - timedelta(hours=24)).isoformat()
    c.execute(f"""
        SELECT actor_name, public_summary, created_at
        FROM audit_log
        WHERE estate_id={p} AND created_at > {p}
        ORDER BY created_at DESC
        LIMIT 15
    """, (estate_id, yesterday))
    rows = c.fetchall()
    recent_activity = [
        {'actor': r[0], 'summary': r[1], 'at': r[2]}
        for r in rows
    ]

    conn.close()

    return {
        'members': members,
        'not_joined': not_joined,
        'joined': joined,
        'total_items': total_items,
        'distributed': distributed,
        'unclaimed': unclaimed,
        'conflicts': conflicts,
        'pending_suggestions': pending_suggestions,
        'recent_activity': recent_activity,
    }


def format_context_for_morris(ctx: dict, estate_name: str) -> str:
    """Render the estate context as a plain-English brief for Morris."""

    lines = [f"Estate: {estate_name}"]
    lines.append(f"Family: {len(ctx['joined'])} of {len(ctx['members'])} members joined")

    if ctx['not_joined']:
        names = ', '.join(m['name'] for m in ctx['not_joined'])
        lines.append(f"Not yet joined: {names}")

    lines.append(
        f"Inventory: {ctx['total_items']} items total — "
        f"{ctx['distributed']} distributed, {ctx['unclaimed']} unclaimed"
    )

    if ctx['conflicts']:
        details = '; '.join(
            f"\"{c['name']}\" ({c['claimants']})"
            for c in ctx['conflicts']
        )
        lines.append(f"Active conflicts: {details}")
    else:
        lines.append("Active conflicts: none")

    if ctx['pending_suggestions']:
        details = ', '.join(
            f"\"{s['name']}\" from {s['suggested_by']}"
            for s in ctx['pending_suggestions']
        )
        lines.append(f"Pending review: {details}")
    else:
        lines.append("Pending suggestions: none")

    if ctx['recent_activity']:
        lines.append("Recent activity (last 24h):")
        for a in ctx['recent_activity'][:8]:
            lines.append(f"  {a['summary']}")
    else:
        lines.append("No activity in the last 24 hours.")

    return '\n'.join(lines)


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool("Send Telegram Message")
def send_telegram_tool(message: str) -> str:
    """Send a Telegram message to the executor."""
    return send_message(message)


@tool("Write Memory")
def write_memory_tool(event_type: str, summary: str) -> str:
    """
    Save something worth remembering about the executor or estate.
    event_type: 'note', 'decision', 'preference', 'concern'
    """
    write_memory(event_type, summary)
    return f"Noted: {summary}"


# ── Runners ───────────────────────────────────────────────────────────────────

def run_morning_briefing(estate_id: int, estate_name: str, executor_name: str):
    """
    Fires each morning. Morris reads the full estate state and sends
    the executor a brief, specific, actionable summary of what needs attention.
    """
    # Run Steward sweep first — populates fresh alerts
    try:
        run_steward(estate_id)
    except Exception as e:
        print(f"Steward error: {e}")

    ctx = build_estate_context(estate_id)
    context_text = format_context_for_morris(ctx, estate_name)

    # Add Steward alerts and milestone status to briefing context
    alerts = get_active_alerts(estate_id)
    steward_text = format_alerts_for_morris(alerts)
    milestones = get_milestones(estate_id)
    if milestones:
        ms_lines = ["Milestone status:"]
        for m in milestones:
            due = m['target_date'][:10] if m.get('target_date') else 'TBD'
            done = '✓' if m['status'] == 'complete' else f"due {due}"
            ms_lines.append(f"  {m['label']}: {done}")
        context_text += "\n" + "\n".join(ms_lines)
    context_text += "\n" + steward_text

    recent_memory = read_recent_memories(limit=5)
    llm = make_llm()

    agent = Agent(
        role="Morris — FM Estate Coordinator",
        goal=(
            "Send the executor a morning briefing that tells them exactly "
            "what needs their attention today — specific, warm, actionable."
        ),
        backstory=MORRIS_CHARACTER,
        tools=[send_telegram_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Good morning. Time to brief {executor_name} on the estate.\n\n"
            f"Here is the current state of the estate:\n{context_text}\n\n"
            f"Recent context from past conversations:\n{recent_memory}\n\n"
            "Write a morning briefing in Morris's voice. Structure it as:\n"
            "— One sentence of overall estate health (progress, tone, urgency)\n"
            "— Then work through what specifically needs attention, "
            "in order of urgency. Weave in the Steward alerts naturally — "
            "don't recite them verbatim, translate them into Morris's voice. "
            "Be concrete: name the person, name the item, say why it matters.\n"
            "— If any milestones are upcoming or overdue, mention it briefly.\n"
            "— Close with what you'll handle yourself today vs. what needs "
            "a decision from the executor.\n\n"
            "Keep it to 8-10 sentences. No bullet points. No headers. "
            "Just Morris talking. Sign off as Morris."
        ),
        expected_output="Morning estate briefing sent via Telegram.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    set_state("idle")
    print(f"Morning briefing sent for estate: {estate_name}")


def run_suggestion_notification(
    estate_id: int,
    estate_name: str,
    suggester_name: str,
    item_name: str
):
    """
    Fires when a family member submits a new item suggestion.
    Morris notifies the executor promptly but in his own voice.
    """
    ctx = build_estate_context(estate_id)
    pending_count = len(ctx['pending_suggestions'])
    llm = make_llm()

    agent = Agent(
        role="Morris — FM Estate Coordinator",
        goal="Notify the executor of a new item suggestion, briefly and clearly.",
        backstory=MORRIS_CHARACTER,
        tools=[send_telegram_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"{suggester_name} just suggested adding \"{item_name}\" to the "
            f"{estate_name} estate inventory.\n\n"
            f"There are now {pending_count} suggestion(s) awaiting your review.\n\n"
            "Send the executor a brief, warm notification. Mention the item and "
            "who suggested it. Let them know they can review it at "
            "app.familymatter.co. Keep it to two or three sentences. "
            "No need to be formal — this is a heads-up between colleagues. "
            "Sign off as Morris."
        ),
        expected_output="Suggestion notification sent via Telegram.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()


def run_executor_reply(
    user_message: str,
    estate_id: int,
    estate_name: str,
    executor_name: str
):
    """
    Fires when the executor sends Morris a message.
    Morris answers from full estate context — questions, instructions, anything.
    """
    ctx = build_estate_context(estate_id)
    context_text = format_context_for_morris(ctx, estate_name)
    recent_memory = read_recent_memories(limit=8)
    llm = make_llm()

    agent = Agent(
        role="Morris — FM Estate Coordinator",
        goal=(
            "Answer the executor's message helpfully and honestly, "
            "drawing on full knowledge of the estate."
        ),
        backstory=MORRIS_CHARACTER,
        tools=[send_telegram_tool, write_memory_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"{executor_name} has sent you a message: \"{user_message}\"\n\n"
            f"Current estate state:\n{context_text}\n\n"
            f"Recent conversation context:\n{recent_memory}\n\n"
            "Respond as Morris. Use the estate context to give a specific, "
            "useful answer. If you're noting something worth remembering "
            "from this exchange, use Write Memory. "
            "Keep your response to 3-6 sentences. Sign off as Morris."
        ),
        expected_output="Reply sent to executor via Telegram.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    write_memory("note", f"Executor asked: {user_message}")
