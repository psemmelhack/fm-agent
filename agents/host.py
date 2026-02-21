"""
agents/host.py
The Host agent — handles family member invitations,
onboarding, nudges, and group announcements.
Morris calls this agent when family coordination is needed.
"""

import os
from crewai import Agent, Task, Crew
from crewai.tools import tool
from dotenv import load_dotenv

from tools.email import (
    send_invitation_email,
    send_reminder_email,
    send_group_announcement
)
from db.database import (
    create_estate,
    add_family_member,
    get_pending_members,
    get_all_members,
    mark_member_joined,
    init_family_tables
)

load_dotenv()

HOST_CHARACTER = """
You are the Host — a specialist working alongside Morris at Family Matter.

Your role is to welcome family members into the process with warmth and clarity.
You handle invitations, onboarding, nudges, and group communications.

Your character:
- You write with the same warmth and care as Morris, but your focus is 
  on the family as a group rather than the executor one-on-one.
- You are sensitive. People receiving these emails may be grieving. 
  Every word is chosen with that in mind.
- You never rush anyone. An invitation is an invitation, not a demand.
- You are clear about what Family Matter is and what it asks of people —
  no surprises, no fine print.
- When you send a group announcement, you speak to the family as a whole
  with respect and transparency.
- You track who has and hasn't responded, and you nudge gently — 
  never more than once a week, never with urgency or guilt.

What you never do:
- Never use corporate language ("Please be advised...", "As per...")
- Never make people feel processed or managed
- Never reveal one family member's actions to another without cause
- Never send a reminder that feels like a threat
"""


def make_llm():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model="claude-sonnet-4-5",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.6
    )


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool("Send Invitation Email")
def send_invitation_tool(
    to_email: str,
    family_member_name: str,
    deceased_name: str,
    executor_name: str,
    join_code: str
) -> str:
    """Send a Family Matter invitation email to a family member."""
    return send_invitation_email(
        to=to_email,
        family_member_name=family_member_name,
        deceased_name=deceased_name,
        executor_name=executor_name,
        join_code=join_code
    )


@tool("Send Reminder Email")
def send_reminder_tool(
    to_email: str,
    family_member_name: str,
    deceased_name: str,
    join_code: str,
    days_since_invite: int
) -> str:
    """Send a gentle reminder to a family member who hasn't joined yet."""
    return send_reminder_email(
        to=to_email,
        family_member_name=family_member_name,
        deceased_name=deceased_name,
        join_code=join_code,
        days_since_invite=days_since_invite
    )


@tool("Send Group Announcement")
def send_announcement_tool(
    recipient_emails: str,
    subject: str,
    message: str,
    deceased_name: str
) -> str:
    """
    Send a group announcement to all family members.
    recipient_emails: comma-separated list of email addresses.
    """
    emails = [e.strip() for e in recipient_emails.split(",")]
    return send_group_announcement(
        recipients=emails,
        subject=subject,
        message=message,
        deceased_name=deceased_name
    )


@tool("Create Estate")
def create_estate_tool(
    deceased_name: str,
    executor_name: str,
    executor_email: str
) -> str:
    """Create a new estate record and return its ID."""
    init_family_tables()
    estate_id = create_estate(deceased_name, executor_name, executor_email)
    return f"Estate created for {deceased_name}. Estate ID: {estate_id}"


@tool("Add Family Member")
def add_family_member_tool(
    estate_id: int,
    name: str,
    email: str,
    role: str = "member"
) -> str:
    """
    Add a family member to an estate and generate their join code.
    Returns the join code to use in their invitation email.
    """
    join_code = add_family_member(estate_id, name, email, role)
    return f"Added {name} ({email}) with join code: {join_code}"


@tool("Get Pending Members")
def get_pending_tool(estate_id: int) -> str:
    """Get a list of family members who haven't joined yet."""
    members = get_pending_members(estate_id)
    if not members:
        return "All family members have joined."
    lines = [f"- {m['name']} ({m['email']}) — invited {m['invited_at'][:10]}" for m in members]
    return f"{len(members)} pending:\n" + "\n".join(lines)


@tool("Get All Members")
def get_all_members_tool(estate_id: int) -> str:
    """Get all family members and their status for an estate."""
    members = get_all_members(estate_id)
    if not members:
        return "No family members found."
    lines = [f"- {m['name']} ({m['email']}) — {m['status']}" for m in members]
    return "\n".join(lines)


# ── Host runners ──────────────────────────────────────────────────────────────

def run_invite_family(
    deceased_name: str,
    executor_name: str,
    executor_email: str,
    family_members: list  # [{"name": "Jane", "email": "jane@example.com"}, ...]
) -> str:
    """
    Morris calls this to onboard a new estate and invite all family members.
    """
    llm = make_llm()

    agent = Agent(
        role="Host — Family Matter",
        goal=(
            "Create the estate, add all family members, and send each one "
            "a warm, personal invitation email."
        ),
        backstory=HOST_CHARACTER,
        tools=[
            create_estate_tool,
            add_family_member_tool,
            send_invitation_tool
        ],
        llm=llm,
        verbose=True
    )

    members_text = "\n".join([f"- {m['name']}: {m['email']}" for m in family_members])

    task = Task(
        description=(
            f"A new estate needs to be set up for {deceased_name}.\n"
            f"Executor: {executor_name} ({executor_email})\n\n"
            f"Family members to invite:\n{members_text}\n\n"
            "Steps:\n"
            "1. Create the estate using the Create Estate tool\n"
            "2. For each family member, use Add Family Member to get their join code\n"
            "3. Send each person a warm invitation email using Send Invitation Email\n\n"
            "Each invitation should feel personal — address them by name. "
            "The tone is warm, unhurried, and sensitive. These people are grieving."
        ),
        expected_output="Estate created and invitation emails sent to all family members.",
        agent=agent
    )

    result = Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    return str(result)


def run_nudge_pending(estate_id: int, deceased_name: str):
    """
    Morris calls this to send gentle reminders to family members
    who haven't joined yet.
    """
    llm = make_llm()

    agent = Agent(
        role="Host — Family Matter",
        goal="Send gentle, warm reminders to family members who haven't joined yet.",
        backstory=HOST_CHARACTER,
        tools=[get_pending_tool, send_reminder_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Check who hasn't joined the {deceased_name} estate (ID: {estate_id}) yet "
            "and send each of them a gentle reminder email. "
            "The reminder should feel like a quiet knock on the door, "
            "not a deadline notice. Never guilt, never urgency."
        ),
        expected_output="Reminder emails sent to all pending family members.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()


def run_group_announcement(
    estate_id: int,
    deceased_name: str,
    subject: str,
    message: str
):
    """Morris calls this to send an announcement to all family members."""
    llm = make_llm()

    agent = Agent(
        role="Host — Family Matter",
        goal="Send a group announcement to all family members.",
        backstory=HOST_CHARACTER,
        tools=[get_all_members_tool, send_announcement_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Send the following announcement to all members of estate ID {estate_id}:\n\n"
            f"Subject: {subject}\n"
            f"Message: {message}\n\n"
            f"Deceased: {deceased_name}\n\n"
            "First get all member emails using Get All Members, "
            "then send the announcement. Write in Morris's voice — "
            "warm, clear, respectful."
        ),
        expected_output="Group announcement sent to all family members.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
