"""
agents/crew.py
CrewAI agents using Claude. Agents are created inside runner
functions so nothing touches env vars at import time.
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


# ── LLM factory (called at runtime, not import time) ─────────────────────────

def make_llm():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model="claude-sonnet-4-5",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.3
    )


# ── Crew runners ──────────────────────────────────────────────────────────────

def run_morning_greeting():
    """Fires at 6AM — personalized based on memory."""
    location = os.getenv("MY_LOCATION", "Shelter Island, NY")
    recent_memory = read_recent_memories(limit=10)
    preferences = read_preferences()
    llm = make_llm()

    agent = Agent(
        role="Daily Concierge",
        goal=(
            "Send a warm, personalized good morning message via Telegram "
            "that reflects what you know about Peter's past preferences."
        ),
        backstory=(
            "You're a warm, organized personal assistant with a great memory. "
            "You start Peter's day with a friendly, personalized check-in. "
            "You keep messages concise — this is Telegram, not an essay. "
            f"Peter is currently in {location}. "
            "You subtly reference his past activity when relevant, "
            "but never make it feel like you're reading from a file."
        ),
        tools=[send_telegram_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Send Peter a warm good morning message via Telegram. "
            f"He is currently in {location}.\n\n"
            f"Recent history:\n{recent_memory}\n\n"
            f"Preferences:\n{preferences}\n\n"
            "Use this context to make the greeting feel personal. "
            "Ask what he'd like to do today. "
            "Keep it to 1-2 sentences. Sign off as 'your FM assistant'."
        ),
        expected_output="A personalized Telegram morning greeting was sent.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    set_state("waiting_for_preference")
    print("Morning greeting sent. State → waiting_for_preference")


def run_event_search(user_message: str):
    """Fires when user replies with what they want to do."""
    location = os.getenv("MY_LOCATION", "Shelter Island, NY")
    preferences = read_preferences()
    write_memory("preference", f"Peter asked for: {user_message} in {location}")
    llm = make_llm()

    agent = Agent(
        role="Local Events Finder",
        goal=(
            "Find 3-5 specific local events matching what Peter asked for, "
            "biased toward his known preferences."
        ),
        backstory=(
            f"You're a knowledgeable local guide for {location}. "
            "You find real, specific events — not generic suggestions. "
            "You present options as a short numbered list, easy to read on a phone."
        ),
        tools=[search_events_tool, send_telegram_tool, save_event_tool, write_memory_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Peter said: '{user_message}'\n\n"
            f"Search for 3-5 real local events in the {location} area for today.\n\n"
            f"Known preferences:\n{preferences}\n\n"
            "Format as a numbered Telegram list: event name, time, one-line description. "
            "End with: 'Reply with the number of anything you'd like to attend!'"
        ),
        expected_output="A Telegram message with a numbered list of event options.",
        agent=agent
    )

    result = Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    set_state("waiting_for_selection", last_message=user_message, search_results=str(result))
    print("Event options sent. State → waiting_for_selection")


def run_event_confirmation(user_selection: str, previous_results: str):
    """Fires when user selects an event."""
    llm = make_llm()

    agent = Agent(
        role="Local Events Finder",
        goal="Confirm the user's event selection, save it, and write a memory.",
        backstory=(
            "You're a helpful assistant who confirms event choices, "
            "saves them for reminders, and remembers preferences for next time."
        ),
        tools=[send_telegram_tool, save_event_tool, write_memory_tool],
        llm=llm,
        verbose=True
    )

    task = Task(
        description=(
            f"Peter was shown these options:\n{previous_results}\n\n"
            f"He replied: '{user_selection}'\n\n"
            "Identify which event he selected. Save it using the Save Event tool "
            "(format start time as YYYY-MM-DDTHH:MM:SS using today's date). "
            "Use Write Memory to note what he chose and any preference insight. "
            "Send a warm Telegram confirmation with event name, time, and "
            "that he'll get a reminder 1 hour before."
        ),
        expected_output="Event saved, memory written, confirmation sent via Telegram.",
        agent=agent
    )

    Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
    set_state("confirmed")
    print("Event confirmed and saved. State → confirmed")
