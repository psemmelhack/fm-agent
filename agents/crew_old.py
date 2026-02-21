"""
agents/crew.py
CrewAI agents using Claude. Now with memory —
the agent reads past preferences before each interaction
and writes new memories after each one.
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

# ── LLM ──────────────────────────────────────────────────────────────────────

from langchain_anthropic import ChatAnthropic

_llm = None

def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(
            model="claude-sonnet-4-5",
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0.3
        )
    return _llm

location = os.getenv("MY_LOCATION", "Shelter Island, NY")


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
    Examples:
      - preference: "Peter enjoys live jazz music"
      - skipped: "Peter skipped a wine tasting event"
      - feedback: "Peter said he prefers outdoor evening events"
    """
    write_memory(event_type, summary)
    return f"Memory saved: {summary}"


# ── Agents ────────────────────────────────────────────────────────────────────

morning_agent = Agent(
    role="Daily Concierge",
    goal=(
        "Send a warm, personalized good morning message via Telegram "
        "that reflects what you know about Peter's past preferences. "
        "Ask what he'd like to do today."
    ),
    backstory=(
        "You're a warm, organized personal assistant with a great memory. "
        "You start Peter's day with a friendly, personalized check-in. "
        "You keep messages concise — this is Telegram, not an essay. "
        f"Peter is currently in {location}. "
        "You subtly reference his past activity when relevant — "
        "for example, if he went to jazz last week, you might mention it. "
        "But you never make it feel like you're reading from a file."
    ),
    tools=[send_telegram_tool],
    llm=get_llm(),
    verbose=True
)

events_agent = Agent(
    role="Local Events Finder",
    goal=(
        "Find 3-5 specific local events matching what Peter asked for, "
        "biased toward his known preferences. Present as a numbered Telegram list. "
        "When he selects one, save it and write a memory about his choice. "
        "When he skips options, note what he passed on."
    ),
    backstory=(
        f"You're a knowledgeable local guide for {location}. "
        "You find real, specific events — not generic suggestions. "
        "You know Peter's preferences from past interactions and use them "
        "to rank and filter results. You present options as a short numbered "
        "list, easy to read on a phone. You remember what he chooses and what "
        "he skips so you can do better next time."
    ),
    tools=[search_events_tool, send_telegram_tool, save_event_tool, write_memory_tool],
    llm=get_llm(),
    verbose=True
)


# ── Crew runners ──────────────────────────────────────────────────────────────

def run_morning_greeting():
    """Fires at 6AM — personalized based on memory."""
    recent_memory = read_recent_memories(limit=10)
    preferences = read_preferences()

    task = Task(
        description=(
            f"Send Peter a warm good morning message via Telegram. "
            f"He is currently in {location}.\n\n"
            f"Here is what you know about him from past interactions:\n"
            f"{recent_memory}\n\n"
            f"His preferences and past activity:\n"
            f"{preferences}\n\n"
            "Use this context to make the greeting feel personal — "
            "reference something relevant if it fits naturally. "
            "Ask what he'd like to do today. "
            "Keep it to 1-2 sentences. Sign off as 'your FM assistant'."
        ),
        expected_output="A personalized Telegram morning greeting was sent.",
        agent=morning_agent
    )
    Crew(agents=[morning_agent], tasks=[task], verbose=True).kickoff()
    set_state("waiting_for_preference")
    print("Morning greeting sent. State → waiting_for_preference")


def run_event_search(user_message: str):
    """Fires when user replies with what they want to do."""
    preferences = read_preferences()

    # Write a memory about today's preference
    write_memory("preference", f"Peter asked for: {user_message} in {location}")

    task = Task(
        description=(
            f"Peter said: '{user_message}'\n\n"
            f"Search for 3-5 real local events or activities matching his request "
            f"in the {location} area for today.\n\n"
            f"Here are his known preferences to help you rank results:\n"
            f"{preferences}\n\n"
            "Format as a numbered Telegram list: event name, time, one-line description. "
            "Prioritize options that align with his preferences. "
            "End with: 'Reply with the number of anything you'd like to attend!'"
        ),
        expected_output="A Telegram message with a numbered list of event options.",
        agent=events_agent
    )
    result = Crew(agents=[events_agent], tasks=[task], verbose=True).kickoff()
    set_state("waiting_for_selection", last_message=user_message, search_results=str(result))
    print("Event options sent. State → waiting_for_selection")


def run_event_confirmation(user_selection: str, previous_results: str):
    """Fires when user selects an event."""
    task = Task(
        description=(
            f"Peter was shown these event options:\n{previous_results}\n\n"
            f"He replied: '{user_selection}'\n\n"
            "Identify which event he selected. Save it using the Save Event tool "
            "(parse name, location, and start time — format as YYYY-MM-DDTHH:MM:SS). "
            "Use the Write Memory tool to note what he chose and anything notable "
            "about his preference (e.g. 'Peter chose a sunset beach concert over "
            "an indoor art show — prefers outdoor events'). "
            "Then send a warm Telegram confirmation with event name, time, and "
            "that he'll get a reminder 1 hour before."
        ),
        expected_output="Event saved, memory written, confirmation sent via Telegram.",
        agent=events_agent
    )
    Crew(agents=[events_agent], tasks=[task], verbose=True).kickoff()
    set_state("confirmed")
    print("Event confirmed and saved. State → confirmed")
