"""
agents/onboarding.py
Morris-led schedule onboarding conversation.

Morris asks the executor 3-4 natural questions via Telegram.
Extracts key dates and preferences.
Hands off to the Steward to build the milestone schedule.
"""

import os
import json
from datetime import datetime, timedelta
from crewai import Agent, Task, Crew
from crewai.tools import tool
from dotenv import load_dotenv

from tools.telegram import send_message
from db.database import (
    get_state, set_state, save_schedule, set_milestones,
    get_schedule, MILESTONE_KEYS, DEFAULT_DURATIONS_DAYS
)

load_dotenv()

ONBOARDING_SYSTEM = """
You are Morris, conducting a brief onboarding conversation with the executor
to establish the estate's timeline and schedule.

You are asking 3-4 focused questions to understand:
1. Whether there is a target completion date or deadline
2. Any legal or probate constraints
3. The family's pace — is urgency needed or does everyone need time?
4. Any individuals who need special accommodation

Your tone is the same as always — warm, professional, unhurried.
You are gathering information, not conducting an interrogation.
One question at a time. Listen carefully to the answers.
Keep each message to 2-4 sentences.
Sign off as Morris.
"""


def make_llm():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model="claude-sonnet-4-5",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.7
    )


def build_milestone_schedule(
    estate_id: int,
    target_end_date: str = None,
    urgency: str = 'normal',
) -> list:
    """
    Build milestone dates working backward from target_end_date (if given)
    or forward from today using default durations.
    Returns list of milestone dicts ready for set_milestones().
    """
    today = datetime.now()

    labels = {
        "onboarding_complete":    "Schedule established",
        "inventory_complete":     "Inventory complete",
        "family_joined":          "All family members joined",
        "claims_open":            "Claims period opens",
        "claims_closed":          "Claims period closes",
        "conflicts_resolved":     "All conflicts resolved",
        "distribution_complete":  "Distribution complete",
    }

    # Duration multiplier based on urgency
    multiplier = {"urgent": 0.6, "normal": 1.0, "relaxed": 1.5}.get(urgency, 1.0)

    if target_end_date:
        # Work backward from target
        try:
            end = datetime.fromisoformat(target_end_date)
        except Exception:
            end = today + timedelta(days=180)

        # Distribute phases proportionally
        total_days = (end - today).days
        if total_days < 30:
            total_days = 30  # minimum

        weights = {
            "distribution_complete":  0,
            "conflicts_resolved":     int(total_days * 0.10),
            "claims_closed":          int(total_days * 0.25),
            "claims_open":            int(total_days * 0.35),
            "family_joined":          int(total_days * 0.15),
            "inventory_complete":     int(total_days * 0.20),
            "onboarding_complete":    0,
        }

        milestones = []
        for key in MILESTONE_KEYS:
            if key == "onboarding_complete":
                target = today
            elif key == "distribution_complete":
                target = end
            else:
                days_back = weights.get(key, 30)
                target = end - timedelta(days=days_back)

            milestones.append({
                "key": key,
                "label": labels[key],
                "target_date": target.isoformat(),
                "status": "complete" if key == "onboarding_complete" else "pending",
            })
    else:
        # Work forward from today using defaults
        milestones = []
        cursor = today

        for key in MILESTONE_KEYS:
            if key == "onboarding_complete":
                target = today
                status = "complete"
            else:
                duration = int(
                    DEFAULT_DURATIONS_DAYS.get(key, 30) * multiplier
                )
                cursor = cursor + timedelta(days=duration)
                target = cursor
                status = "pending"

            milestones.append({
                "key": key,
                "label": labels[key],
                "target_date": target.isoformat(),
                "status": status,
            })

    return milestones


def start_onboarding(estate_id: int, estate_name: str, executor_name: str):
    """
    Send the first onboarding message.
    Sets state to 'onboarding_q1' so webhook routes follow-ups here.
    """
    llm = make_llm()

    @tool("Send Telegram Message")
    def send_telegram(message: str) -> str:
        """Send a Telegram message."""
        return send_message(message)

    agent = Agent(
        role="Morris — FM Estate Coordinator",
        goal="Open a warm, focused onboarding conversation about the estate timeline.",
        backstory=ONBOARDING_SYSTEM,
        tools=[send_telegram],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Begin the schedule onboarding conversation with {executor_name} "
            f"for the {estate_name} estate.\n\n"
            "Send a brief, warm introduction explaining that before you get into "
            "the day-to-day, you'd like to understand the timeline — it will help "
            "you know when to push and when to give people space.\n\n"
            "Then ask the first question: Is there a target date for completing "
            "distribution, or any legal or probate deadlines you're working toward?\n\n"
            "Keep it to 3-4 sentences. Natural, not clinical. Sign off as Morris."
        ),
        expected_output="Onboarding question 1 sent via Telegram.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    set_state("onboarding_q1", last_message="awaiting_deadline_answer")
    print("Onboarding started — state → onboarding_q1")


def handle_onboarding_reply(
    user_message: str,
    estate_id: int,
    estate_name: str,
    executor_name: str
):
    """
    Routes onboarding replies through a 3-question sequence.
    Uses Claude to extract structured answers and decide when to finalize.
    """
    state_row = get_state()
    current_state = state_row.get("state", "idle")
    context = state_row.get("last_message", "")

    # Accumulate answers in state
    answers_raw = state_row.get("search_results", "{}")
    try:
        answers = json.loads(answers_raw) if answers_raw else {}
    except Exception:
        answers = {}

    llm = make_llm()

    if current_state == "onboarding_q1":
        # Extract deadline/target date from answer
        answers["q1_deadline"] = user_message
        next_q = (
            f"Thank {executor_name} for that, acknowledge what they said, "
            "then ask the second question: How would you describe the pace — "
            "is there urgency to wrap this up, or does the family need time to "
            "process and move carefully?"
        )
        next_state = "onboarding_q2"

    elif current_state == "onboarding_q2":
        answers["q2_urgency"] = user_message
        next_q = (
            f"Acknowledge their answer, then ask the third question: "
            "Are there any family members who might need extra time or "
            "a lighter touch — someone who lives far away, is elderly, "
            "or is having a particularly hard time with the loss?"
        )
        next_state = "onboarding_q3"

    elif current_state == "onboarding_q3":
        answers["q3_accommodation"] = user_message
        # Final question
        next_q = (
            "Acknowledge what they've shared. Then ask one last thing: "
            "Is there anything else about this family or this estate that "
            "you think I should know before we get started? "
            "No obligation — just anything that would help me do this right."
        )
        next_state = "onboarding_q4"

    elif current_state == "onboarding_q4":
        answers["q4_other"] = user_message
        # All answers collected — finalize schedule
        _finalize_schedule(
            answers=answers,
            estate_id=estate_id,
            estate_name=estate_name,
            executor_name=executor_name,
            llm=llm
        )
        return

    else:
        return

    # Send next question
    @tool("Send Telegram Message")
    def send_telegram(message: str) -> str:
        return send_message(message)

    agent = Agent(
        role="Morris — FM Estate Coordinator",
        goal="Continue the onboarding conversation naturally.",
        backstory=ONBOARDING_SYSTEM,
        tools=[send_telegram],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"The executor said: \"{user_message}\"\n\n"
            f"Conversation so far: {json.dumps(answers, indent=2)}\n\n"
            + next_q +
            "\n\nKeep it to 2-4 sentences. Sign off as Morris."
        ),
        expected_output="Next onboarding question sent via Telegram.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    set_state(next_state, last_message=next_state,
              search_results=json.dumps(answers))


def _finalize_schedule(
    answers: dict,
    estate_id: int,
    estate_name: str,
    executor_name: str,
    llm
):
    """
    Extract structured data from conversational answers,
    build the milestone schedule, and send a confirmation.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Use Claude to extract structured data from the conversational answers
    extraction_prompt = f"""
Extract schedule information from this onboarding conversation.

Q1 (deadline/target date): {answers.get('q1_deadline', '')}
Q2 (urgency/pace): {answers.get('q2_urgency', '')}
Q3 (special accommodations): {answers.get('q3_accommodation', '')}
Q4 (other notes): {answers.get('q4_other', '')}

Return a JSON object with these fields:
- target_end_date: ISO date string (YYYY-MM-DD) if mentioned, null if not
- urgency: one of "urgent", "normal", "relaxed"
- legal_deadlines: string describing any legal constraints, or null
- special_notes: any accommodation or other notes worth remembering

Return ONLY valid JSON, no other text.
"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": extraction_prompt}]
    )

    try:
        extracted = json.loads(response.content[0].text.strip())
    except Exception:
        extracted = {
            "target_end_date": None,
            "urgency": "normal",
            "legal_deadlines": None,
            "special_notes": None
        }

    # Save schedule config
    save_schedule(
        estate_id=estate_id,
        target_end_date=extracted.get("target_end_date"),
        urgency=extracted.get("urgency", "normal"),
        legal_deadlines=extracted.get("legal_deadlines"),
        notes=extracted.get("special_notes"),
        onboarding_complete=True
    )

    # Build and save milestones
    milestones = build_milestone_schedule(
        estate_id=estate_id,
        target_end_date=extracted.get("target_end_date"),
        urgency=extracted.get("urgency", "normal"),
    )
    set_milestones(estate_id, milestones)

    # Send confirmation in Morris's voice
    @tool("Send Telegram Message")
    def send_telegram(message: str) -> str:
        return send_message(message)

    agent = Agent(
        role="Morris — FM Estate Coordinator",
        goal="Confirm the schedule has been set and summarize key dates.",
        backstory=ONBOARDING_SYSTEM,
        tools=[send_telegram],
        llm=llm,
        verbose=True
    )

    milestone_summary = "\n".join(
        f"  {m['label']}: {m['target_date'][:10] if m.get('target_date') else 'TBD'}"
        for m in milestones if m['key'] != 'onboarding_complete'
    )

    task = Task(
        description=(
            f"You have just finished the schedule onboarding conversation "
            f"with {executor_name} for the {estate_name} estate.\n\n"
            f"Extracted schedule:\n"
            f"  Target end date: {extracted.get('target_end_date') or 'not set'}\n"
            f"  Urgency: {extracted.get('urgency', 'normal')}\n"
            f"  Legal deadlines: {extracted.get('legal_deadlines') or 'none mentioned'}\n\n"
            f"Milestone plan:\n{milestone_summary}\n\n"
            "Send a warm, concise confirmation. Summarize the key dates in "
            "plain English — not as a list, as sentences. Let the executor know "
            "you'll be watching these and will flag anything that's at risk. "
            "Keep it to 4-5 sentences. Sign off as Morris."
        ),
        expected_output="Schedule confirmation sent via Telegram.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    set_state("idle")
    print("Onboarding complete — schedule saved, state → idle")
