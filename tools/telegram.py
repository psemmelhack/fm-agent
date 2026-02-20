"""
tools/telegram.py
Send messages via Telegram Bot API.
Replaces the Twilio SMS helper.
"""

import os
import asyncio
import requests
from dotenv import load_dotenv

load_dotenv()


def send_message(message: str) -> str:
    """
    Send a Telegram message to your personal chat.
    Uses the synchronous requests library so it plays
    nicely inside CrewAI tasks.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }

    response = requests.post(url, json=payload, timeout=10)
    result = response.json()

    if result.get("ok"):
        print(f"Telegram message sent: {message[:60]}...")
        return "Message sent successfully."
    else:
        error = result.get("description", "Unknown error")
        print(f"Telegram error: {error}")
        return f"Failed to send message: {error}"


def get_latest_message() -> dict:
    """
    Poll for the most recent message from the user.
    Used by the webhook poller to check for replies.
    Returns dict with 'text' and 'update_id' or empty dict.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/getUpdates"

    response = requests.get(url, params={"limit": 10, "timeout": 5}, timeout=15)
    result = response.json()

    if not result.get("ok") or not result.get("result"):
        return {}

    # Return the most recent message
    updates = result["result"]
    latest = updates[-1]
    message = latest.get("message", {})
    return {
        "update_id": latest.get("update_id"),
        "text": message.get("text", ""),
        "from": message.get("from", {}).get("first_name", ""),
        "chat_id": message.get("chat", {}).get("id")
    }


def clear_updates(up_to_update_id: int):
    """
    Tell Telegram we've processed updates up to this ID
    so they don't show up again in getUpdates.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    requests.get(url, params={"offset": up_to_update_id + 1, "timeout": 1}, timeout=10)
