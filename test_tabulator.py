"""
test_tabulator.py
Test the Tabulator agent with sample inventory and claims.
Run with: python test_tabulator.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from db.database import init_db, init_family_tables, init_tabulator_tables
from agents.tabulator import run_add_inventory, run_status_report, run_record_claim

# Initialize all tables
init_db()
init_family_tables()
init_tabulator_tables()

ESTATE_ID = 1  # Use the estate created by test_host.py

print("=== Adding inventory items ===")
run_add_inventory(ESTATE_ID, [
    {"name": "Grandfather clock", "description": "Antique walnut, circa 1880",
     "location": "Living room", "category": "furniture", "estimated_value": 2000},
    {"name": "Pearl necklace", "description": "Single strand, 18 inch",
     "location": "Jewelry box", "category": "jewelry", "estimated_value": 800},
    {"name": "Oil painting — seascape", "description": "Unsigned, gilt frame",
     "location": "Dining room", "category": "art", "estimated_value": 500},
    {"name": "Rocking chair", "description": "Oak, hand carved",
     "location": "Bedroom", "category": "furniture", "estimated_value": 300},
    {"name": "First edition books (set of 4)", "description": "Hemingway collection",
     "location": "Study", "category": "books", "estimated_value": 1200},
])

print("\n=== Recording claims ===")
# Two people want the grandfather clock — conflict!
run_record_claim(1, ESTATE_ID, 1, "Peter Semmelhack", "want", "It was always in the front hall")
run_record_claim(1, ESTATE_ID, 2, "Jane Smith", "need", "I grew up with this clock")

# One person wants the necklace
run_record_claim(2, ESTATE_ID, 3, "Mary Jones", "want", "Mom always said this would be mine")

print("\n=== Status report ===")
report = run_status_report(ESTATE_ID)
print(report)
