"""
main.py
Entry point for cloud deployment.
Runs both the scheduler and Telegram listener in parallel threads.
"""

import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from db.database import init_db
from scheduler import morning_job, reminder_check_job
from tools.telegram import get_latest_message, clear_updates, send_message
from agents.crew import run_event_search, run_event_confirmation
from db.database import get_state

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

PT = pytz.timezone("America/Los_Angeles")

# ── Telegram polling state ────────────────────────────────────────────────────

last_update_id = None


def handle_message(text: str):
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
    global last_update_id
    update = get_latest_message()
    if not update:
        return
    update_id = update.get("update_id")
    text = update.get("text", "").strip()
    if update_id == last_update_id:
        return
    if text.startswith("/"):
        clear_updates(update_id)
        last_update_id = update_id
        return
    if text:
        handle_message(text)
    clear_updates(update_id)
    last_update_id = update_id


def run_telegram_listener():
    print("✅ Telegram listener started.")
    while True:
        try:
            poll()
        except Exception as e:
            print(f"Poll error: {e}")
        time.sleep(2)


# ── Scheduler ─────────────────────────────────────────────────────────────────

def run_scheduler():
    scheduler = BackgroundScheduler(timezone=PT)

    scheduler.add_job(
        morning_job,
        trigger=CronTrigger(hour=6, minute=0, timezone=PT),
        id="morning_greeting",
        replace_existing=True
    )

    scheduler.add_job(
        reminder_check_job,
        trigger="interval",
        minutes=5,
        id="reminder_check",
        replace_existing=True
    )

    scheduler.start()
    print("✅ Scheduler started. Morning greeting at 6AM PT.")

    while True:
        time.sleep(60)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("🚀 FM Agent starting...")

    # Run scheduler and Telegram listener in parallel threads
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    telegram_thread = threading.Thread(target=run_telegram_listener, daemon=True)

    scheduler_thread.start()
    telegram_thread.start()

    print("FM Agent running. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        print("FM Agent stopped.")
