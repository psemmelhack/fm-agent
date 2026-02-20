"""
agents/crew.py
CrewAI agents using Claude.
Morris — the FM Assistant persona.
"""

import os
from crewai import Agent, Task, Crew
from crewai.tools import tool
from dotenv import load_dotenv

from tools.search import search_local_events
from tools.telegram import send_message
from tools.memory import write_memory, read_recent_memories, read_preferences
from db.database import get_state, set_state, save_event

load_dotenv()

MORRIS_CHARACTER = """
You are Morris, a personal assistant with the warmth and expertise 
of a trusted boutique owner who has known their best customers for years.

Your character:
- You greet Peter as if he's just walked through the door of your shop 
  — genuinely glad to see him, never performatively so.
- You notice things. If it's a beautiful morning, you mention it. If 
  Peter has been busy lately, you acknowledge it. You make him feel 
  seen without making it feel like surveillance.
- You are an expert. Not just in what you're helping with today, but 
  in how it connects to everything else. You offer that expertise 
  naturally, never as a lecture.
- You have taste. When you suggest something, it's because you 
  genuinely think it's right for him — not because it was first on 
  the list.
- You never oversell. If something isn't right, you say so gently and 
  find something better.
- You can be disagreed with. If Peter says no, you don't flinch. You 
  simply course correct and keep looking for the right thing.
- You are unhurried. You never make Peter feel rushed or processed.
- You know when to be brief. This is Telegram — a few sentences, 
  never an essay.
- You sign off as Morris, never as "your FM assistant."

Your voice:
- Warm but not gushing
- Confident but not pushy
- Personal but not presumptuous
- Occasionally a light touch of wit, never at Peter's expense
- Never corporate, never robotic, never sycophantic

What Morris never does:
- Never says "Certainly!" or "Absolutely!" or "Great choice!"
- Never uses bullet points in conversation
- Never starts a message with "I"
- Never makes Peter feel like he's talking to software
"""


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool("Search Local Events")
def search_events_tool(query: str) -> str:
    """Search the web for local events or activities matching the user's interest."""
    return search_local_events(query)


@tool("Send Telegram Message")
def send_telegram_tool(message: str) -> str:
    """Send a Telegram message to the user."""
    return send_message(message)


@tool("Save Event")
def save_event_tool(event_name: str, event_location: str, event_start_time: str) -> str:
    """
    Save an event the user wants to attend so they receive a reminder 1 hour before.
    event_start_time must be ISO format: YYYY-MM-DDTHH:MM:SS
    """
    save_event(event_name, event_location, event_start_time)
    write_memory(
        "attended",
        f"Peter committed to attending '{event_name}' at {event_location} on {event_start_time}"
    )
    return f"Saved '{event_name}' at {event_start_time}. Reminder will fire 1 hour before."


@tool("Write Memory")
def write_memory_tool(event_type: str, summary: str) -> str:
    """
    Save something worth remembering about Peter's preferences or activity.
    event_type options: 'preference', 'skipped', 'attended', 'feedback'
    summary: plain English sentence describing what to remember.
    """
    write_memory(event_type, summary)
    return f"Memory saved: {summary}"


# ── LLM factory ───────────────────────────────────────────────────────────────

def make_llm():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model="claude-sonnet-4-5",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.7
    )


# ── Crew runners ──────────────────────────────────────────────────────────────

def run_morning_greeting():
    """Fires at 6AM — Morris's opening of the day."""
    location = os.getenv("MY_LOCATION", "Shelter Island, NY")
    recent_memory = read_recent_memories(limit=10)
    preferences = read_preferences()
    llm = make_llm()

    agent = Agent(
        role="Morris — Personal Assistant",
        goal="Send Peter a warm, personal good morning message and ask what he'd like to do today.",
        backstory=MORRIS_CHARACTER,
        tools=[send_telegram_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Good morning. Send Peter your opening message for the day.\n\n"
            f"He is currently in {location}.\n\n"
            f"Here is what you know about him from recent interactions:\n"
            f"{recent_memory}\n\n"
            f"His preferences and past activity:\n"
            f"{preferences}\n\n"
            "Craft a greeting that feels like the door of your shop just opened "
            "and Peter walked in. Acknowledge something real — the time of day, "
            "the location, something from his recent history if it fits naturally. "
            "Then ask, warmly and simply, what you can help him find today. "
            "Two or three sentences at most. Sign off as Morris."
        ),
        expected_output="A warm, personal Telegram morning greeting sent to Peter.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    set_state("waiting_for_preference")
    print("Morning greeting sent. State → waiting_for_preference")


def run_event_search(user_message: str):
    """Fires when Peter tells Morris what he's looking for."""
    location = os.getenv("MY_LOCATION", "Shelter Island, NY")
    preferences = read_preferences()
    write_memory("preference", f"Peter asked for: {user_message} in {location}")
    llm = make_llm()

    agent = Agent(
        role="Morris — Personal Assistant",
        goal=(
            "Find the right options for Peter — not just anything that matches, "
            "but things Morris would genuinely recommend."
        ),
        backstory=MORRIS_CHARACTER,
        tools=[search_events_tool, send_telegram_tool, save_event_tool, write_memory_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Peter has told you what he's looking for: '{user_message}'\n\n"
            f"He's in {location}. Search for 3-5 real options for today.\n\n"
            f"What you know about his taste:\n{preferences}\n\n"
            "Present the options the way Morris would — not as a data dump, "
            "but as a thoughtful recommendation. Each option gets a name, "
            "a time, and one sentence that tells Peter why it might be right for him. "
            "Number them so he can reply easily. "
            "End with a single, natural sentence inviting him to pick one — "
            "or tell you if none of these feel right. "
            "No bullet points. No headers. Just Morris talking."
        ),
        expected_output="A curated list of event options sent via Telegram in Morris's voice.",
        agent=agent
    )

    result = Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    set_state("waiting_for_selection", last_message=user_message, search_results=str(result))
    print("Options sent. State → waiting_for_selection")


def run_event_confirmation(user_selection: str, previous_results: str):
    """Fires when Peter makes his choice."""
    llm = make_llm()

    agent = Agent(
        role="Morris — Personal Assistant",
        goal="Confirm Peter's choice warmly, save the event, and note the preference.",
        backstory=MORRIS_CHARACTER,
        tools=[send_telegram_tool, save_event_tool, write_memory_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Peter was shown these options:\n{previous_results}\n\n"
            f"He chose: '{user_selection}'\n\n"
            "Save the event using the Save Event tool "
            "(format start time as YYYY-MM-DDTHH:MM:SS using today's date). "
            "Use Write Memory to capture what this choice tells you about his taste — "
            "something specific, like a good shopkeeper would note after a sale. "
            "Then send Peter a confirmation the way Morris would — "
            "warm, brief, confident. Confirm the event name and time. "
            "Let him know you'll remind him an hour before. "
            "Maybe one small thing that makes him look forward to it. "
            "Sign off as Morris."
        ),
        expected_output="Event saved, preference noted, warm confirmation sent via Telegram.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    set_state("confirmed")
    print("Confirmed. State → confirmed")
