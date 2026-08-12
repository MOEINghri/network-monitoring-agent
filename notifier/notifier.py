"""
Notifier Service
-----------------
یک سرویس ساده که هشدارها را از سایر بخش‌های سیستم (Agent، Guardrail)
دریافت می‌کند و بر اساس سطح اهمیت به تکنسین از طریق تلگرام اطلاع می‌دهد.

بخش‌های دیگر با یک POST ساده به /alert هشدار می‌فرستند؛ این جداسازی
باعث می‌شود بعداً بشه به‌راحتی Slack یا ایمیل هم اضافه کرد بدون
دست‌زدن به Agent یا Guardrail.
"""

import os
import logging
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Literal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [notifier] %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SEVERITY_EMOJI = {
    "informational": "ℹ️",
    "warning": "⚠️",
    "critical": "🚨",
}

app = FastAPI(title="Network Agent Notifier")


class Alert(BaseModel):
    severity: Literal["informational", "warning", "critical"]
    title: str
    message: str


def send_telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured; skipping send. Message was:\n%s", text)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error("Failed to send Telegram message: %s", e)
        return False


@app.post("/alert")
def alert(a: Alert):
    emoji = SEVERITY_EMOJI.get(a.severity, "")
    text = f"{emoji} [{a.severity.upper()}] {a.title}\n\n{a.message}"
    log.info("Dispatching alert: %s", text)
    sent = send_telegram_message(text)
    return {"sent": sent}


@app.get("/health")
def health():
    return {"status": "ok"}
