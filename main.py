"""
main.py
Entry point for Railway deployment.
Runs the FM scheduler — morning briefings, steward sweep, suggestion checks.
"""

import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from scheduler import (
    init_all,
    morning_job,
    suggestion_check_job,
    steward_sweep_job,
    onboarding_check_job,
)

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

PT = pytz.timezone("America/Los_Angeles")

ESTATE_ID     = int(os.getenv("FM_ESTATE_ID", "1"))
ESTATE_NAME   = os.getenv("FM_ESTATE_NAME", "the estate")
EXECUTOR_NAME = os.getenv("FM_EXECUTOR_NAME", "the executor")


def run_scheduler():
    scheduler = BackgroundScheduler(timezone=PT)

    # 9:00 AM PT — Morris morning estate briefing
    scheduler.add_job(
        morning_job,
        trigger=CronTrigger(hour=9, minute=0, timezone=PT),
        id="morning_briefing",
        name="Morning Estate Briefing",
        replace_existing=True
    )

    # 9:30 AM PT — Steward daily sweep
    scheduler.add_job(
        steward_sweep_job,
        trigger=CronTrigger(hour=9, minute=30, timezone=PT),
        id="steward_sweep",
        name="Steward Daily Sweep",
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

    scheduler.start()
    print("✅ FM Scheduler started.")
    print(f"   Estate: {ESTATE_NAME} (ID: {ESTATE_ID})")
    print(f"   Executor: {EXECUTOR_NAME}")
    print("   Morning briefing: 9:00 AM PT")
    print("   Steward sweep:    9:30 AM PT")
    print("   Suggestion check: every 10 min")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    print("🚀 FM Agent starting...")

    # Init all database tables
    init_all()

    # Check if onboarding needed (runs once on startup)
    try:
        onboarding_check_job()
    except Exception as e:
        print(f"Onboarding check skipped: {e}")

    # Run scheduler in a daemon thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    print("FM Agent running.\n")

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        print("FM Agent stopped.")
