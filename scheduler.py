"""
scheduler.py
FM Agent scheduled jobs.

Jobs:
  1. 9:00 AM PT daily — Morris morning estate briefing
  2. Every 10 min    — Check for new suggestions, notify executor
"""

import os
import time
import pytz
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from db.database import (
    init_db, init_family_tables, init_audit_tables,
    get_pending_suggestions, get_connection, USE_POSTGRES,
    init_schedule_tables, get_schedule
)
from agents.crew import run_morning_briefing, run_suggestion_notification
from agents.steward import run_steward
from agents.onboarding import start_onboarding

load_dotenv()

PT = pytz.timezone("America/Los_Angeles")

# Estate config — loaded from env
ESTATE_ID     = int(os.getenv("FM_ESTATE_ID", "1"))
ESTATE_NAME   = os.getenv("FM_ESTATE_NAME", "the estate")
EXECUTOR_NAME = os.getenv("FM_EXECUTOR_NAME", "the executor")

# Track which suggestions we've already notified about
# (stored in memory — resets on restart, which is fine;
#  suggestions have a 'notified' flag in the db)
_notified_suggestion_ids = set()


def morning_job():
    """9AM PT — Morris briefs the executor on the day."""
    print(f"⏰ 9AM PT — firing morning briefing for estate {ESTATE_ID}...")
    try:
        run_morning_briefing(ESTATE_ID, ESTATE_NAME, EXECUTOR_NAME)
    except Exception as e:
        print(f"Morning briefing error: {e}")


def suggestion_check_job():
    """
    Every 10 minutes — check for new pending suggestions.
    Notify the executor via Morris for any we haven't flagged yet.
    """
    try:
        pending = get_pending_suggestions(ESTATE_ID)
        for suggestion in pending:
            sid = suggestion.get('id')
            if sid and sid not in _notified_suggestion_ids:
                print(f"New suggestion: {suggestion['name']} from {suggestion['suggested_by_name']}")
                run_suggestion_notification(
                    estate_id=ESTATE_ID,
                    estate_name=ESTATE_NAME,
                    suggester_name=suggestion['suggested_by_name'],
                    item_name=suggestion['name']
                )
                _notified_suggestion_ids.add(sid)
    except Exception as e:
        print(f"Suggestion check error: {e}")


def steward_sweep_job():
    """Daily Steward sweep — runs after morning briefing to keep alerts fresh."""
    print(f"🔍 Daily Steward sweep for estate {ESTATE_ID}...")
    try:
        run_steward(ESTATE_ID)
    except Exception as e:
        print(f"Steward sweep error: {e}")


def onboarding_check_job():
    """
    On startup and daily — check if the estate needs schedule onboarding.
    If no schedule exists, Morris initiates the onboarding conversation.
    """
    try:
        schedule = get_schedule(ESTATE_ID)
        if not schedule or not schedule.get('onboarding_complete'):
            print("No schedule found — starting onboarding...")
            start_onboarding(ESTATE_ID, ESTATE_NAME, EXECUTOR_NAME)
    except Exception as e:
        print(f"Onboarding check error: {e}")


def init_all():
    """Initialize all database tables on startup."""
    for fn_name, fn in [
        ('init_db', init_db),
        ('init_family_tables', init_family_tables),
        ('init_audit_tables', init_audit_tables),
        ('init_schedule_tables', init_schedule_tables),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"{fn_name} warning: {e}")


if __name__ == "__main__":
    init_all()

    scheduler = BackgroundScheduler(timezone=PT)

    # 9:00 AM Pacific Time daily
    scheduler.add_job(
        morning_job,
        trigger=CronTrigger(hour=9, minute=0, timezone=PT),
        id="morning_briefing",
        name="Morning Estate Briefing",
        replace_existing=True
    )

    # Every 10 minutes — new suggestion check
    scheduler.add_job(
        suggestion_check_job,
        trigger="interval",
        minutes=10,
        id="suggestion_check",
        name="New Suggestion Check",
        replace_existing=True
    )

    # 9:30 AM — Steward daily sweep (after morning briefing)
    scheduler.add_job(
        steward_sweep_job,
        trigger=CronTrigger(hour=9, minute=30, timezone=PT),
        id="steward_sweep",
        name="Steward Daily Sweep",
        replace_existing=True
    )

    scheduler.start()
    print("✅ FM Scheduler running.")
    print(f"   Estate: {ESTATE_NAME} (ID: {ESTATE_ID})")
    print(f"   Executor: {EXECUTOR_NAME}")
    print("   Morning briefing fires at 9:00 AM PT")
    print("   Steward sweep fires at 9:30 AM PT")
    print("   Suggestion check runs every 10 minutes")
    print("   Press Ctrl+C to stop.\n")

    # Check if onboarding needed
    onboarding_check_job()

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("Scheduler stopped.")
