"""
webhook.py
Polls Telegram for incoming messages and routes them
based on conversation state.

Run with: python webhook.py

No ngrok needed — this polls Telegram's servers directly.
Telegram long-polling means no inbound HTTP server required.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
from dotenv import load_dotenv
from db.database import init_db, get_state
from tools.telegram import get_latest_message, clear_updates, send_message
from agents.crew import run_event_search, run_event_confirmation

load_dotenv()

# Track the last update_id we've processed so we don't re-handle messages
last_update_id = None


def handle_message(text: str):
    """Route incoming message based on current conversation state."""
    state_row = get_state()
    current_state = state_row.get("state", "idle")

    print(f"Incoming: '{text}' | State: {current_state}")

    if current_state == "waiting_for_preference":
        run_event_search(text)

    elif current_state == "waiting_for_selection":
        previous_results = state_row.get("search_results", "")
        run_event_confirmation(text, previous_results)

    else:
        send_message(
            "Got it! I'll check in again tomorrow morning at 6AM PT. "
            "Have a great rest of your day!"
        )


def poll():
    """Long-poll Telegram for new messages."""
    global last_update_id

    update = get_latest_message()

    if not update:
        return

    update_id = update.get("update_id")
    text = update.get("text", "").strip()

    # Skip if we've already handled this update
    if update_id == last_update_id:
        return

    # Skip bot commands like /start
    if text.startswith("/"):
        clear_updates(update_id)
        last_update_id = update_id
        return

    if text:
        handle_message(text)

    clear_updates(update_id)
    last_update_id = update_id


if __name__ == "__main__":
    init_db()
    print("✅ Telegram listener running.")
    print("   Polling for your replies every 2 seconds.")
    print("   Press Ctrl+C to stop.\n")

    while True:
        try:
            poll()
        except Exception as e:
            print(f"Poll error: {e}")
        time.sleep(2)
