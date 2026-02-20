# FM Agent — Daily Event Concierge (MVP)

Wakes up at 6AM PT, asks what you want to do, finds events near 
Shelter Island NY via Tavily, and reminds you 1 hour before anything 
you commit to. All via Telegram. No Twilio, no ngrok needed.

---

## Prerequisites

- Python 3.11+
- Anthropic API key: https://console.anthropic.com
- Tavily API key (free tier): https://tavily.com
- Telegram account + bot token (from @BotFather)

---

## Setup

### 1. Install dependencies

```bash
cd fm-agent
pip install -r requirements.txt
```

### 2. Configure your .env

```bash
cp .env.example .env
nano .env   # fill in your actual keys
```

```
ANTHROPIC_API_KEY=your_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=8540761734
TAVILY_API_KEY=your_key
MY_LOCATION=Shelter Island, NY
```

### 3. Initialize the database

```bash
python -c "from db.database import init_db; init_db()"
```

---

## Running

You need **two terminal windows** open:

**Terminal 1 — Scheduler (fires 6AM greeting + reminder checks)**
```bash
python scheduler.py
```

**Terminal 2 — Telegram listener (watches for your replies)**
```bash
python webhook.py
```

That's it. No ngrok. No webhook URL. Telegram polling handles everything.

---

## How it works

```
6:00 AM PT
  → Agent sends Telegram message: "Good morning! What would you 
    like to do today? — your FM assistant"

You reply: "I'd love to find a live music event tonight"

  → Agent searches locally, sends back 3-5 numbered options

You reply: "2"

  → Agent confirms your choice and saves the event
  → 1 hour before it starts: Telegram reminder sent automatically
```

---

## Testing without waiting for 6AM

Fire the morning greeting immediately:
```bash
python -c "from agents.crew import run_morning_greeting; run_morning_greeting()"
```

Test the reminder checker:
```bash
python -c "from scheduler import reminder_check_job; reminder_check_job()"
```

Test sending a Telegram message directly:
```bash
python -c "from tools.telegram import send_message; send_message('Hello from FM Agent!')"
```

---

## Project structure

```
fm-agent/
├── agents/
│   └── crew.py          # CrewAI agents (morning + events)
├── db/
│   └── database.py      # SQLite state + event storage
├── tools/
│   ├── telegram.py      # Telegram send/receive
│   └── search.py        # Tavily event search
├── webhook.py           # Telegram reply poller
├── scheduler.py         # 6AM greeting + reminder jobs
├── requirements.txt
└── .env.example
```

---

## Two terminals, always open

| Terminal | Command | Purpose |
|----------|---------|---------|
| 1 | `python scheduler.py` | 6AM greeting + reminders |
| 2 | `python webhook.py` | Watches for your Telegram replies |
