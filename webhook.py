"""
webhook.py
Polls Telegram for incoming messages from the executor.
Routes everything to Morris, who answers from full estate context.

No complex state machine needed — Morris is always in conversation mode.
"""

import os
import time
from dotenv import load_dotenv

from db.database import init_db
from tools.telegram import get_latest_message, clear_updates, send_message
from agents.crew import run_executor_reply
from agents.onboarding import handle_onboarding_reply
from db.database import get_schedule

load_dotenv()

ESTATE_ID     = int(os.getenv("FM_ESTATE_ID", "1"))
ESTATE_NAME   = os.getenv("FM_ESTATE_NAME", "the estate")
EXECUTOR_NAME = os.getenv("FM_EXECUTOR_NAME", "the executor")

last_update_id = None


def handle_message(text: str):
    """Route executor message — onboarding if in progress, otherwise Morris Q&A."""
    from db.database import get_state
    state_row = get_state()
    current_state = state_row.get("state", "idle")

    print(f"Executor → Morris: '{text}' | State: {current_state}")

    # Route onboarding replies
    if current_state in ("onboarding_q1", "onboarding_q2",
                         "onboarding_q3", "onboarding_q4"):
        try:
            handle_onboarding_reply(
                user_message=text,
                estate_id=ESTATE_ID,
                estate_name=ESTATE_NAME,
                executor_name=EXECUTOR_NAME
            )
        except Exception as e:
            print(f"Onboarding reply error: {e}")
            send_message("Something went wrong — let me try that again. — Morris")
        return

    # Normal Morris conversation
    try:
        run_executor_reply(
            user_message=text,
            estate_id=ESTATE_ID,
            estate_name=ESTATE_NAME,
            executor_name=EXECUTOR_NAME
        )
    except Exception as e:
        print(f"Reply error: {e}")
        send_message(
            "Something went wrong on my end. Give me a moment and try again. — Morris"
        )


def poll():
    global last_update_id

    update = get_latest_message()
    if not update:
        return

    update_id = update.get("update_id")
    text = update.get("text", "").strip()

    if update_id == last_update_id:
        return

    # Skip bot commands
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
    print("✅ FM Telegram listener running.")
    print(f"   Estate: {ESTATE_NAME} (ID: {ESTATE_ID})")
    print(f"   Executor: {EXECUTOR_NAME}")
    print("   All executor messages routed to Morris.")
    print("   Press Ctrl+C to stop.\n")

    while True:
        try:
            poll()
        except Exception as e:
            print(f"Poll error: {e}")
        time.sleep(2)
