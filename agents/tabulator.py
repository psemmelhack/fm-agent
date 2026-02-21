"""
agents/tabulator.py
The Tabulator — FM's ledger keeper.
Tracks inventory, claims, conflicts, distributions, and fairness.
Morris calls this agent to manage the distribution process.
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
    init_tabulator_tables
)

load_dotenv()

TABULATOR_CHARACTER = """
You are the Tabulator — the keeper of the ledger for Family Matter.

Your role is precise, fair, and transparent. You track every item,
every claim, every decision, and every distribution. Nothing gets lost.
Nothing is decided without being recorded.

Your character:
- You are meticulous. Every item has a record. Every claim is logged.
- You are impartial. You have no favorites among family members.
- You surface conflicts clearly and without drama — two people want
  the same thing, and you present that fact without editorializing.
- You are the source of truth. When someone asks what's been claimed,
  what's been distributed, or whether things are fair, you know.
- You report to Morris, who translates your data into human conversations.
- You never make distribution decisions yourself — you present the facts
  and let Morris and the family decide.

What you always do:
- Record everything with timestamps
- Flag conflicts immediately when they arise
- Track fairness metrics so imbalances don't go unnoticed
- Provide clear summaries on request

What you never do:
- Never take sides in a dispute
- Never make a distribution decision without explicit instruction
- Never lose or overwrite a record
"""


def make_llm():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model="claude-sonnet-4-5",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.1  # Low temp — the Tabulator deals in facts
    )


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool("Add Inventory Item")
def add_item_tool(
    estate_id: int,
    name: str,
    description: str = "",
    location: str = "",
    category: str = "",
    estimated_value: float = 0
) -> str:
    """Add an item to the estate inventory."""
    init_tabulator_tables()
    item_id = add_item(estate_id, name, description, location, category, estimated_value)
    return f"Item '{name}' added to inventory. Item ID: {item_id}"


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
    claim_type: 'want' (would like it), 'need' (strong preference), 'memory' (sentimental only)
    priority: 1 (high) to 3 (low)
    """
    # Check for existing claims first
    existing = get_item_claims(item_id)
    claim_id = add_claim(item_id, estate_id, member_id, member_name, claim_type, priority, note)

    if existing:
        claimants = ", ".join([c["member_name"] for c in existing])
        return (
            f"Claim recorded for {member_name} on item {item_id}. "
            f"⚠️ CONFLICT: {claimants} also claimed this item. "
            f"Morris should be notified."
        )
    return f"Claim recorded for {member_name} on item {item_id}. No conflicts."


@tool("Get Item Claims")
def get_claims_tool(item_id: int) -> str:
    """Get all pending claims on a specific item."""
    claims = get_item_claims(item_id)
    if not claims:
        return f"No claims on item {item_id}."
    lines = []
    for c in claims:
        lines.append(
            f"- {c['member_name']}: {c['claim_type']} "
            f"(priority {c['priority']})"
            + (f" — \"{c['note']}\"" if c.get('note') else "")
        )
    return f"{len(claims)} claim(s) on item {item_id}:\n" + "\n".join(lines)


@tool("Get Estate Inventory")
def get_inventory_tool(estate_id: int, status: str = "") -> str:
    """
    Get all items in an estate inventory.
    status filter: 'unclaimed', 'claimed', 'disputed', 'distributed' or empty for all.
    """
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


@tool("Resolve Distribution")
def resolve_tool(
    item_id: int,
    winner_member_id: int,
    winner_name: str,
    method: str,
    value: float = 0
) -> str:
    """
    Record that an item has been distributed to a family member.
    method: 'unanimous', 'lottery', 'buyout', 'gifted', 'donated', 'sold'
    """
    resolve_claim(item_id, winner_member_id, winner_name, method, value)
    return f"Item {item_id} distributed to {winner_name} via {method}. Distribution recorded."


@tool("Get Fairness Summary")
def fairness_tool(estate_id: int) -> str:
    """
    Get a summary of how much value each family member has received so far.
    Used to flag imbalances before they become problems.
    """
    summary = get_fairness_summary(estate_id)
    if not summary:
        return "No distributions recorded yet."
    lines = []
    for row in summary:
        lines.append(
            f"- {row['member_name']}: {row['item_count']} item(s), "
            f"~${float(row['total_value']):.0f} total value"
        )
    return "Distribution summary:\n" + "\n".join(lines)


@tool("Get Conflicts")
def get_conflicts_tool(estate_id: int) -> str:
    """Find all items that have more than one pending claim — active conflicts."""
    from db.database import get_connection, USE_POSTGRES
    conn = get_connection()
    c = conn.cursor()
    p = '%s' if USE_POSTGRES else '?'
    c.execute(f"""
        SELECT i.id, i.name, COUNT(cl.id) as claim_count
        FROM inventory_items i
        JOIN claims cl ON cl.item_id = i.id
        WHERE i.estate_id={p}
        AND cl.status='pending'
        AND i.status != 'distributed'
        GROUP BY i.id, i.name
        HAVING COUNT(cl.id) > 1
        ORDER BY claim_count DESC
    """, (estate_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        return "No conflicts found. All claimed items have a single claimant."

    lines = []
    for row in rows:
        lines.append(f"- Item [{row[0]}] '{row[1]}': {row[2]} claimants")
    return f"⚠️ {len(rows)} conflict(s) found:\n" + "\n".join(lines)


# ── Tabulator runners ─────────────────────────────────────────────────────────

def run_add_inventory(estate_id: int, items: list) -> str:
    """
    Morris calls this to bulk-add items to the inventory.
    items: [{"name": ..., "description": ..., "location": ...,
             "category": ..., "estimated_value": ...}, ...]
    """
    llm = make_llm()

    agent = Agent(
        role="Tabulator — FM Ledger",
        goal="Add all provided items to the estate inventory accurately.",
        backstory=TABULATOR_CHARACTER,
        tools=[add_item_tool],
        llm=llm,
        verbose=True
    )

    items_text = "\n".join([
        f"- {item['name']}: {item.get('description', '')} | "
        f"Location: {item.get('location', 'unknown')} | "
        f"Category: {item.get('category', 'general')} | "
        f"Est. value: ${item.get('estimated_value', 0)}"
        for item in items
    ])

    task = Task(
        description=(
            f"Add the following items to estate ID {estate_id}:\n\n"
            f"{items_text}\n\n"
            "Use the Add Inventory Item tool for each one. "
            "Record all details accurately."
        ),
        expected_output="All items added to inventory with their IDs recorded.",
        agent=agent
    )

    result = Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    return str(result)


def run_status_report(estate_id: int) -> str:
    """
    Morris calls this to get a full status report on an estate.
    Returns a plain-English summary of inventory, claims, conflicts, and fairness.
    """
    llm = make_llm()

    agent = Agent(
        role="Tabulator — FM Ledger",
        goal="Generate a complete, clear status report for this estate.",
        backstory=TABULATOR_CHARACTER,
        tools=[get_inventory_tool, get_conflicts_tool, fairness_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Generate a full status report for estate ID {estate_id}.\n\n"
            "Include:\n"
            "1. Inventory summary — total items, how many claimed, unclaimed, distributed\n"
            "2. Active conflicts — items with multiple claimants\n"
            "3. Fairness summary — distribution balance across family members\n\n"
            "Be precise and factual. This report goes to Morris who will "
            "translate it for the executor."
        ),
        expected_output="A complete estate status report.",
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
        goal="Record this claim accurately and flag any conflicts.",
        backstory=TABULATOR_CHARACTER,
        tools=[record_claim_tool, get_claims_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Record a claim from {member_name} (member ID {member_id}) "
            f"on item ID {item_id} in estate {estate_id}.\n"
            f"Claim type: {claim_type}\n"
            f"Note: {note}\n\n"
            "After recording, check if there are other claimants on this item. "
            "If so, flag the conflict clearly in your response."
        ),
        expected_output="Claim recorded. Conflict status reported.",
        agent=agent
    )

    result = Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    return str(result)
