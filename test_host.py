"""
test_host.py
Quick test to send a real invitation email via the Host agent.
Run with: python test_host.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from db.database import init_db, init_family_tables
from agents.host import run_invite_family

# Initialize database tables
init_db()
init_family_tables()

# Test — replace with your real email to receive the invitation
run_invite_family(
    deceased_name="Margaret Semmelhack",
    executor_name="Peter Semmelhack",
    executor_email="peter@familymatter.co",
    family_members=[
        {"name": "Peter Semmelhack", "email": "psemme@gmail.com"}
    ]
)

print("Done — check your inbox.")
