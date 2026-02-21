# Family Matter

**A quiet, organized system for helping families navigate the distribution of a loved one's belongings — with care, clarity, and fairness.**

---

## Mission

When a family elder passes away or downsizes, the distribution of their belongings is one of the most practically and emotionally complex things a family faces. It happens at the worst possible time — when people are grieving, scattered across geographies, and operating with different memories of what things meant.

Family Matter exists to make this process humane.

It provides a guided, AI-assisted experience that takes a family from initial invitation through final distribution — tracking every item, every claim, every decision, and every story along the way. It doesn't rush anyone. It doesn't take sides. It keeps things fair and keeps everyone informed.

The system is built around **Morris** — a warm, expert personal assistant persona modeled on the owner of a trusted boutique. Morris doesn't feel like software. He feels like someone who genuinely knows what he's doing, cares about getting it right, and will never make you feel processed.

---

## Proposed User Experience

### The Executor's Journey

The person responsible for the estate (the executor) begins by telling Morris the basics: the name of the deceased, the family members to invite, and a rough sense of what needs to be distributed. Morris takes it from there.

Morris hands off to the **Host** agent, who sends each family member a warm, personalized email invitation from `morris@familymatter.co`. Each invitation contains a unique six-character join code and a link to `app.familymatter.co`.

As the inventory is catalogued (photos taken, items described), the **Tabulator** maintains the ledger — tracking what exists, what's been claimed, and whether the distribution is trending fairly.

When conflicts arise — two people wanting the same item — the **Mediator** (planned) steps in to surface options: a lottery, a buyout, shared custody, or a direct conversation.

Throughout the process, Morris keeps the executor informed via Telegram — a daily briefing on where things stand, what needs attention, and what's been resolved.

### The Family Member's Journey

A family member receives an email from Morris. It's warm and unhurried — it explains what Family Matter is, acknowledges the difficulty of the moment, and invites them to join when they're ready.

They go to `app.familymatter.co`, enter their join code, and land on the estate portal. They can see who else is in the family group (and whether they've joined yet), browse the full inventory, and mark items they'd like to be considered for.

The portal shows photos where available, estimated values, and the location of each item within the home. Search, filter, and sort make it easy to find what they're looking for.

Claims are visible to the system but not to other family members — preventing the awkwardness of knowing who wants what before decisions are made.

---

## Architecture Overview

Family Matter is split into two repositories that share a single PostgreSQL database.

```
┌─────────────────────────────────────┐    ┌──────────────────────────────┐
│           fm-agent (Worker)          │    │       fm-web (Web App)        │
│                                     │    │                              │
│  Morris — orchestrator persona      │    │  Landing page                │
│  Host — email invitations           │    │  Join code entry             │
│  Tabulator — inventory & claims     │    │  Estate portal               │
│  Scheduler — 6AM briefings          │    │  Inventory grid              │
│  Webhook — Telegram polling         │    │  Claim management            │
│                                     │    │                              │
└──────────────┬──────────────────────┘    └──────────────┬───────────────┘
               │                                          │
               └──────────────┬───────────────────────────┘
                              │
               ┌──────────────▼───────────────┐
               │        PostgreSQL             │
               │   (Railway managed)           │
               │                              │
               │  estates                     │
               │  family_members              │
               │  inventory_items             │
               │  claims                      │
               │  distributions               │
               │  conversation_state          │
               │  saved_events                │
               │  memories                    │
               └──────────────────────────────┘
```

### External Services

| Service | Purpose |
|---|---|
| **Anthropic (Claude)** | Powers all AI agents — Morris, Host, Tabulator |
| **Resend** | Transactional email from `morris@familymatter.co` |
| **Telegram** | Two-way messaging between Morris and the executor |
| **Tavily** | Web search for Morris's daily event recommendations |
| **Railway** | Cloud hosting for both services + PostgreSQL |

### Deployment

Both services run on Railway as separate deployments connected to the same Postgres instance.

- `fm-agent` deploys as a **worker** (no public port) — runs the scheduler and Telegram polling loop continuously
- `fm-web` deploys as a **web** service — serves the Flask application at `app.familymatter.co`

---

## Repository: `fm-agent`

The agent worker. Runs continuously in the cloud. Contains all AI agent logic, the database layer, and all integration tools.

### `/agents`

**`crew.py`** — The core of the system. Defines Morris's character in a detailed system prompt and contains three runner functions:

- `run_morning_greeting()` — Fires at 6AM PT. Morris reads recent memories and preferences, then sends a warm, personalized Telegram message asking what Peter would like to do today.
- `run_event_search(user_message)` — Fires when the executor replies with a preference. Morris searches for real local events using Tavily and presents 3-5 curated options in his voice — not a data dump, but a thoughtful recommendation.
- `run_event_confirmation(user_selection, previous_results)` — Fires when the executor picks an option. Morris saves the event, writes a memory about the preference, and sends a warm confirmation with a reminder promise.

Morris's character is defined once in the `MORRIS_CHARACTER` constant and injected into every agent's backstory. Key rules: never says "Certainly!" or "Absolutely!", never uses bullet points in conversation, never starts a message with "I", never makes the user feel like they're talking to software.

**`host.py`** — The Host agent. Handles all family member communication. Contains three runner functions:

- `run_invite_family(deceased_name, executor_name, executor_email, family_members)` — Creates the estate record, generates unique join codes for each family member, and sends personalized HTML invitation emails via Resend.
- `run_nudge_pending(estate_id, deceased_name)` — Sends gentle reminder emails to family members who haven't joined yet. Tone is a quiet knock on the door, never a deadline notice.
- `run_group_announcement(estate_id, deceased_name, subject, message)` — Sends a message to all family members simultaneously.

The Host runs at temperature `0.6` — slightly warmer than the Tabulator, slightly cooler than Morris. It writes with care because its audience is grieving.

**`tabulator.py`** — The Tabulator agent. The ledger keeper. Tracks inventory, claims, conflicts, and distribution fairness. Contains three runner functions:

- `run_add_inventory(estate_id, items)` — Bulk-adds items to the inventory.
- `run_status_report(estate_id)` — Generates a complete status report: inventory summary, active conflicts, and fairness balance across family members.
- `run_record_claim(item_id, estate_id, member_id, member_name, claim_type, note)` — Records a family member's claim on an item and immediately flags if a conflict exists.

The Tabulator runs at temperature `0.1` — the lowest of any agent. It deals in facts. It never editorializes. When it says there's a conflict, it says so plainly.

### `/db`

**`database.py`** — The single source of truth for all data operations. Handles both PostgreSQL (production on Railway) and SQLite (local development) transparently — the code detects which is available via the `DATABASE_URL` environment variable and switches automatically.

Contains all table definitions and CRUD functions organized by domain:

- **State**: `get_state()`, `set_state()` — tracks the current conversation state (idle → waiting_for_preference → waiting_for_selection → confirmed)
- **Events**: `save_event()`, `get_unreminded_events()`, `mark_reminder_sent()` — manages Morris's daily event recommendations and reminders
- **Memories**: `write_memory_to_db()`, `read_memories()` — persistent memory layer across conversations
- **Family**: `create_estate()`, `add_family_member()`, `get_pending_members()`, `get_all_members()`, `mark_member_joined()`
- **Inventory**: `add_item()`, `get_estate_inventory()`
- **Claims**: `add_claim()`, `get_item_claims()`, `resolve_claim()`
- **Fairness**: `get_fairness_summary()` — returns total estimated value distributed per family member

### `/tools`

**`telegram.py`** — Thin wrapper around the Telegram Bot API. `send_message()` posts a message to the executor's chat. `get_latest_message()` polls for new replies. `clear_updates()` clears the update queue after processing.

**`search.py`** — Tavily search wrapper. `search_local_events(query)` takes a natural language query and returns structured event data from the web. Unlike Google, Tavily returns content suitable for AI consumption, not links for humans.

**`email.py`** — Resend email integration. Four functions:
- `send_email(to, subject, html)` — base sender from `Morris <morris@familymatter.co>`
- `send_invitation_email(...)` — renders the full HTML invitation with join code and link to `app.familymatter.co`
- `send_reminder_email(...)` — gentle nudge for non-responders
- `send_group_announcement(...)` — multi-recipient announcement with consistent styling

All emails share a visual identity: Georgia/serif body, warm cream tones, a gold left-border accent on the join code block, and Morris's signature at the bottom.

**`memory.py`** — Reads and writes the memory layer. `write_memory(event_type, summary)` saves a memory entry. `read_recent_memories(limit)` returns a formatted string of recent interactions for injection into agent prompts. `read_preferences()` filters for preference, feedback, and attended events specifically.

Memory types: `preference` (what the user asked for), `attended` (events committed to), `skipped` (options passed on), `feedback` (explicit likes/dislikes).

### Root Files

**`main.py`** — Combined entry point for Railway deployment. Runs the Telegram polling loop and the APScheduler in separate threads so a single Railway worker process handles both.

**`scheduler.py`** — APScheduler configuration. Fires `run_morning_greeting()` at 6AM Pacific every day. Also runs a reminder check every 5 minutes — fetches unreminded events within 65 minutes of their start time and sends a Telegram reminder.

**`webhook.py`** — Telegram polling loop. Checks for new messages every 2 seconds. Routes incoming messages based on the current conversation state: if waiting for a preference it calls `run_event_search()`, if waiting for a selection it calls `run_event_confirmation()`. Resets state to idle after confirmation or if the user sends a new message mid-flow.

**`requirements.txt`** — Python dependencies: `crewai`, `langchain-anthropic`, `anthropic`, `apscheduler`, `python-telegram-bot`, `tavily-python`, `resend`, `psycopg2-binary`, `python-dotenv`, `pytz`.

**`Procfile`** — Tells Railway to run `python main.py` as a worker process (no HTTP port).

**`test_host.py`** — Development test script. Creates a sample estate, adds a family member, and sends a real invitation email. Safe to run repeatedly — creates a new estate each time.

**`test_tabulator.py`** — Development test script. Adds 5 sample inventory items (furniture, jewelry, art, books) and records sample claims including a deliberate conflict on the grandfather clock.

---

## Repository: `fm-web`

The web application. A Flask app served at `app.familymatter.co`. Shares the same PostgreSQL database as the agent worker — no API layer between them, just direct database reads and writes.

### `app.py`

The entire Flask application in a single file. Contains:

- **`get_db()`** — Connects to Postgres if `DATABASE_URL` is set, SQLite otherwise
- **`query(sql, params, fetchone)`** — Unified query function that handles both database types and returns plain Python dicts
- **`execute(sql, params)`** — For writes (INSERT, UPDATE, DELETE)
- **`init_tables()`** — Creates all tables on startup if they don't exist. Safe to run repeatedly (`CREATE TABLE IF NOT EXISTS`)

Routes:
- `GET /` — Landing page
- `GET/POST /join` — Join code entry. On POST, looks up the code, marks the member as joined, stores session data, and redirects to the estate
- `GET /estate` — The main estate portal. Requires session. Loads family members, inventory, and the current user's claims
- `POST /claim/<item_id>` — Records a claim. Checks for duplicates before inserting
- `POST /unclaim/<item_id>` — Removes a claim
- `GET /logout` — Clears the session
- `GET /debug-env` — Development route that confirms `DATABASE_URL` is set (safe — only shows first 40 characters)

### `/templates`

**`base.html`** — The shared layout. Defines the full design system via CSS custom properties:

```css
--cream:      #FAF8F4   /* page background */
--ink:        #1A1814   /* primary text */
--gold:       #8B7355   /* accent color */
--serif:      'Playfair Display'
--sans:       'DM Sans'
```

Includes the navigation bar (logo + member name/logout when signed in), fade-up animations, button styles, and responsive breakpoints. Every page extends this template.

**`index.html`** — The landing page. Two-column layout: left side has the headline ("Together through what comes next"), a brief explanation, and a CTA button. Right side shows five feature pills describing what Family Matter does. A dark card at the bottom repeats the join code CTA. Designed to be the first thing a family member sees if they navigate directly to the domain rather than clicking the email link.

**`join.html`** — The join code entry page. Centered single-column layout. Large, monospaced input field styled for six-character codes. Autocapitalizes on mobile. Shows an inline error message if the code is invalid. Help text explains where to find the code if it's been misplaced.

**`estate.html`** — The main experience. Three sections:

1. **Estate header** — Deceased name and a welcome line with the member's name
2. **Family strip** — Horizontal row of avatar chips, one per family member. Green dot = joined, grey = still invited. The current user's chip is highlighted in gold. Stats (total items, joined count, your claims) sit at the right edge.
3. **Inventory grid** — Full-width responsive grid. Each card has:
   - A 4:3 photo area (placeholder shown until a photo is uploaded)
   - Category badge overlaid on the photo
   - "✓ Claimed" badge overlaid if claimed by the current user
   - Item name (Playfair Display), description, location, estimated value
   - "I'd like this" / "Remove claim" button

   Above the grid: live search input, sort dropdown (name, value high/low, category), category filter dropdown, "My claims" and "Available" quick-filter chips, and a live results count. All filtering and sorting happens client-side in JavaScript — no page reloads.

### Root Files

**`requirements.txt`** — `flask`, `psycopg2-binary`, `gunicorn`, `python-dotenv`

**`Procfile`** — `web: gunicorn app:app --bind 0.0.0.0:$PORT` — tells Railway this is a web service

**`runtime.txt`** — `python-3.12`

---

## Planned Agents

The following agents are designed but not yet built:

| Agent | Role |
|---|---|
| **Mediator** | Conflict resolution when multiple family members want the same item. Presents options (lottery, buyout, shared custody) without taking sides. |
| **Manager** | Timeline and deadline management. Tracks milestones, sends deadline reminders, interfaces with external calendar systems. |
| **Curator** | Digital asset management. Organizes photos, documents, and scanned materials associated with the estate. |
| **Assistant** | Helps family members capture and upload photos of items directly from their phones. |
| **Appraiser** | Research agent that estimates item values using comparable sales data and flags items that may need professional appraisal. |
| **Storyteller** | Prompts family members to record the provenance and memories attached to each item before it leaves the family. |
| **Liaison** | Interfaces with the external professional world — estate attorneys, appraisers, donation organizations, shipping companies. |
| **Reporter** | Generates clean status summaries for the executor, the attorney, or any family member who wants an overview. |

---

## Environment Variables

### fm-agent (worker)

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `TELEGRAM_BOT_TOKEN` | From @BotFather on Telegram |
| `TELEGRAM_CHAT_ID` | The executor's Telegram chat ID |
| `TAVILY_API_KEY` | For web search |
| `RESEND_API_KEY` | For sending email from `morris@familymatter.co` |
| `MY_LOCATION` | Executor's current location (e.g. "Shelter Island, NY") |
| `DATABASE_URL` | PostgreSQL connection string (public URL for local dev) |

### fm-web (web app)

| Variable | Description |
|---|---|
| `DATABASE_URL` | Same PostgreSQL connection string as the worker |
| `FLASK_SECRET_KEY` | Random string for session signing |

---

## Local Development

Both repos use SQLite when `DATABASE_URL` is not set in `.env`, so you can develop locally without a Postgres connection.

```bash
# fm-agent
cd ~/Development/fm-agent
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in your keys
python -c "from db.database import init_db; init_db()"
python test_host.py       # test invitations
python test_tabulator.py  # test inventory

# fm-web
cd ~/Development/fm-web
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py  # runs at localhost:5000
```

---

*Family Matter is in active development. The architecture is intentionally modular — each agent is independent, testable, and replaceable. Morris is the only constant.*
