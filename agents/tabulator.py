"""
agents/tabulator.py
The Tabulator — FM's ledger keeper.
Every write to the ledger produces a corresponding audit entry.
"""

import os
from crewai import Agent, Task, Crew
from crewai.tools import tool
from dotenv import load_dotenv

from db.database import (
    add_item,
    add_claim,
    get_item_claims,
    get_estate_inventory,
    resolve_claim,
    get_fairness_summary,
    get_audit_log,
    write_audit,
    init_tabulator_tables,
    init_audit_tables
)

load_dotenv()

TABULATOR_CHARACTER = """
You are the Tabulator — the keeper of the ledger for Family Matter.

Your role is precise, fair, and transparent. You track every item,
every claim, every decision, and every distribution. Nothing gets lost.
Nothing is decided without being recorded. Every action is audited.

Your character:
- You are meticulous. Every item has a record. Every claim is logged.
  Every change produces an audit entry that any family member can read.
- You are impartial. You have no favorites among family members.
- You surface conflicts clearly and without drama.
- You are the source of truth. When someone asks what happened to an
  item, you can tell them the complete story — who added it, who claimed
  it, how it was resolved, and when each step occurred.
- You write audit summaries in plain English. A family member with no
  technical background should be able to read the audit log and
  understand exactly what happened.
- You never expose private intent notes. You acknowledge they exist
  in the audit log but never reveal their content.

What you always do:
- Write an audit entry for every action
- Surface conflicts immediately
- Track fairness so imbalances don't go unnoticed

What you never do:
- Take sides in a dispute
- Make a distribution decision without explicit instruction
- Reveal the content of private notes
- Lose or overwrite a record
"""


def make_llm():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model="claude-sonnet-4-5",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.1
    )


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool("Add Inventory Item")
def add_item_tool(
    estate_id: int,
    name: str,
    description: str = "",
    location: str = "",
    category: str = "",
    estimated_value: float = 0,
    added_by: str = "Morris"
) -> str:
    """Add an item to the estate inventory and write an audit entry."""
    init_tabulator_tables()
    init_audit_tables()
    item_id = add_item(estate_id, name, description, location, category, estimated_value)
    write_audit(
        estate_id=estate_id,
        item_id=item_id,
        actor_name=added_by,
        action_type='item_added',
        public_summary=f"{added_by} added \"{name}\" to the inventory.",
        metadata={"category": category, "location": location, "estimated_value": estimated_value}
    )
    return f"Item '{name}' added. Item ID: {item_id}. Audit entry written."


@tool("Record Claim")
def record_claim_tool(
    item_id: int,
    estate_id: int,
    member_id: int,
    member_name: str,
    claim_type: str = "want",
    priority: int = 1,
    note: str = ""
) -> str:
    """
    Record a family member's claim on an item.
    The note is part of the public claim record — visible to all.
    For private context, members use intent notes separately.
    claim_type: 'want' | 'need' | 'memory'
    """
    existing = get_item_claims(item_id)
    add_claim(item_id, estate_id, member_id, member_name, claim_type, priority, note)

    summary = f"{member_name} recorded a claim on item {item_id}."
    if note:
        summary += f" Note: \"{note}\""

    write_audit(
        estate_id=estate_id,
        item_id=item_id,
        actor_id=member_id,
        actor_name=member_name,
        action_type='claim_recorded',
        public_summary=summary,
        metadata={"claim_type": claim_type, "priority": priority}
    )

    if existing:
        claimants = ", ".join([c["member_name"] for c in existing])
        conflict_summary = f"Conflict detected on item {item_id}: {claimants} and {member_name} both have claims."
        write_audit(
            estate_id=estate_id,
            item_id=item_id,
            actor_name="Tabulator",
            action_type='conflict_flagged',
            public_summary=conflict_summary,
            metadata={"claimants": [c["member_name"] for c in existing] + [member_name]}
        )
        return f"Claim recorded. ⚠️ CONFLICT: {claimants} also claimed this item."

    return f"Claim recorded for {member_name} on item {item_id}. No conflicts."


@tool("Resolve Distribution")
def resolve_tool(
    item_id: int,
    estate_id: int,
    winner_member_id: int,
    winner_name: str,
    method: str,
    value: float = 0,
    resolved_by: str = "Morris"
) -> str:
    """
    Record that an item has been distributed to a family member.
    method: 'unanimous' | 'lottery' | 'buyout' | 'gifted' | 'donated' | 'sold'
    """
    resolve_claim(item_id, winner_member_id, winner_name, method, value)
    write_audit(
        estate_id=estate_id,
        item_id=item_id,
        actor_name=resolved_by,
        action_type='distribution_recorded',
        public_summary=f"Item distributed to {winner_name} via {method}.",
        metadata={"method": method, "estimated_value": value}
    )
    return f"Item {item_id} distributed to {winner_name} via {method}. Audit entry written."


@tool("Get Item History")
def get_item_history_tool(estate_id: int, item_id: int) -> str:
    """Get the complete public audit history for a specific item."""
    entries = get_audit_log(estate_id=estate_id, item_id=item_id)
    if not entries:
        return f"No history found for item {item_id}."
    lines = []
    for e in entries:
        date = e['created_at'][:16].replace('T', ' ')
        lines.append(f"[{date}] {e['public_summary']}")
    return "\n".join(lines)


@tool("Get Estate Activity")
def get_estate_activity_tool(estate_id: int) -> str:
    """Get recent activity across the entire estate."""
    entries = get_audit_log(estate_id=estate_id, limit=30)
    if not entries:
        return "No activity recorded yet."
    lines = []
    for e in entries:
        date = e['created_at'][:16].replace('T', ' ')
        lines.append(f"[{date}] {e['public_summary']}")
    return "\n".join(lines)


@tool("Get Item Claims")
def get_claims_tool(item_id: int) -> str:
    """Get all pending claims on a specific item."""
    claims = get_item_claims(item_id)
    if not claims:
        return f"No claims on item {item_id}."
    lines = [
        f"- {c['member_name']}: {c['claim_type']} (priority {c['priority']})"
        + (f" — \"{c['note']}\"" if c.get('note') else "")
        for c in claims
    ]
    return f"{len(claims)} claim(s):\n" + "\n".join(lines)


@tool("Get Estate Inventory")
def get_inventory_tool(estate_id: int, status: str = "") -> str:
    """Get all items in an estate inventory."""
    items = get_estate_inventory(estate_id, status if status else None)
    if not items:
        return f"No items found for estate {estate_id}."
    lines = []
    for item in items:
        val = f"~${item['estimated_value']:.0f}" if item['estimated_value'] else "unvalued"
        lines.append(
            f"[{item['id']}] {item['name']} — {item['status']} — {val}"
            + (f" ({item['location']})" if item.get('location') else "")
        )
    return f"{len(items)} item(s):\n" + "\n".join(lines)


@tool("Get Fairness Summary")
def fairness_tool(estate_id: int) -> str:
    """Get distribution balance across family members."""
    summary = get_fairness_summary(estate_id)
    if not summary:
        return "No distributions recorded yet."
    lines = [
        f"- {row['member_name']}: {row['item_count']} item(s), ~${float(row['total_value']):.0f} total"
        for row in summary
    ]
    return "Distribution summary:\n" + "\n".join(lines)


@tool("Get Conflicts")
def get_conflicts_tool(estate_id: int) -> str:
    """Find all items with more than one pending claim."""
    from db.database import get_connection, USE_POSTGRES
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    c.execute(f"""
        SELECT i.id, i.name, COUNT(cl.id) as claim_count
        FROM inventory_items i
        JOIN claims cl ON cl.item_id = i.id
        WHERE i.estate_id={p} AND cl.status='pending' AND i.status != 'distributed'
        GROUP BY i.id, i.name
        HAVING COUNT(cl.id) > 1
        ORDER BY claim_count DESC
    """, (estate_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        return "No conflicts found."
    lines = [f"- Item [{row[0]}] '{row[1]}': {row[2]} claimants" for row in rows]
    return f"⚠️ {len(rows)} conflict(s):\n" + "\n".join(lines)


# ── Runners ───────────────────────────────────────────────────────────────────

def run_add_inventory(estate_id: int, items: list) -> str:
    """Morris calls this to bulk-add items. Each addition is audited."""
    llm = make_llm()
    agent = Agent(
        role="Tabulator — FM Ledger",
        goal="Add all items to the estate inventory. Write an audit entry for each.",
        backstory=TABULATOR_CHARACTER,
        tools=[add_item_tool],
        llm=llm,
        verbose=True
    )
    items_text = "\n".join([
        f"- {item['name']}: {item.get('description','')} | "
        f"Location: {item.get('location','unknown')} | "
        f"Category: {item.get('category','general')} | "
        f"Est. value: ${item.get('estimated_value',0)}"
        for item in items
    ])
    task = Task(
        description=(
            f"Add these items to estate ID {estate_id}:\n\n{items_text}\n\n"
            "Use Add Inventory Item for each. An audit entry is written automatically."
        ),
        expected_output="All items added with audit entries.",
        agent=agent
    )
    result = Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    return str(result)


def run_status_report(estate_id: int) -> str:
    """Full estate status: inventory, conflicts, fairness, recent activity."""
    llm = make_llm()
    agent = Agent(
        role="Tabulator — FM Ledger",
        goal="Generate a complete, clear status report for this estate.",
        backstory=TABULATOR_CHARACTER,
        tools=[get_inventory_tool, get_conflicts_tool, fairness_tool, get_estate_activity_tool],
        llm=llm,
        verbose=True
    )
    task = Task(
        description=(
            f"Generate a full status report for estate ID {estate_id}.\n\n"
            "Include: inventory summary, active conflicts, fairness summary, "
            "and the 10 most recent audit entries. Be precise and factual."
        ),
        expected_output="Complete estate status report.",
        agent=agent
    )
    result = Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    return str(result)


def run_record_claim(
    item_id: int,
    estate_id: int,
    member_id: int,
    member_name: str,
    claim_type: str = "want",
    note: str = ""
) -> str:
    """Morris calls this when a family member submits a claim."""
    llm = make_llm()
    agent = Agent(
        role="Tabulator — FM Ledger",
        goal="Record this claim and flag any conflicts. Write audit entries.",
        backstory=TABULATOR_CHARACTER,
        tools=[record_claim_tool, get_claims_tool],
        llm=llm,
        verbose=True
    )
    task = Task(
        description=(
            f"Record a claim from {member_name} (member ID {member_id}) "
            f"on item ID {item_id} in estate {estate_id}.\n"
            f"Claim type: {claim_type}\nNote: {note}\n\n"
            "After recording, check for other claimants. Flag any conflict."
        ),
        expected_output="Claim recorded. Conflict status reported.",
        agent=agent
    )
    result = Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    return str(result)
