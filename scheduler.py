"""
scheduler.py
Two jobs:
  1. 6:00 AM PT — fire morning greeting
  2. Every 5 min — check for events needing a 1-hour reminder

Run with: python scheduler.py
"""

import time
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from db.database import init_db, get_unreminded_events, mark_reminder_sent
from agents.crew import run_morning_greeting
from tools.telegram import send_message

load_dotenv()

PT = pytz.timezone("America/Los_Angeles")


def morning_job():
    print("⏰ 6AM PT — firing morning greeting...")
    run_morning_greeting()


def reminder_check_job():
    """Check every 5 minutes for events starting within 65 minutes."""
    events = get_unreminded_events()
    for event in events:
        message = (
            f"⏰ *Reminder:* _{event['event_name']}_ starts in about 1 hour!\n"
            f"📍 {event['event_location']}\n"
            f"🕐 {event['event_start_time']}\n\n"
            f"Have a great time!"
        )
        send_message(message)
        mark_reminder_sent(event["id"])
        print(f"Reminder sent for: {event['event_name']}")


if __name__ == "__main__":
    init_db()

    scheduler = BackgroundScheduler(timezone=PT)

    # 6:00 AM Pacific Time daily
    scheduler.add_job(
        morning_job,
        trigger=CronTrigger(hour=6, minute=0, timezone=PT),
        id="morning_greeting",
        name="Morning Greeting",
        replace_existing=True
    )

    # Every 5 minutes
    scheduler.add_job(
        reminder_check_job,
        trigger="interval",
        minutes=5,
        id="reminder_check",
        name="Event Reminder Check",
        replace_existing=True
    )

    scheduler.start()
    print("✅ Scheduler running.")
    print("   Morning greeting fires at 6:00 AM PT")
    print("   Reminder check runs every 5 minutes")
    print("   Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("Scheduler stopped.")
