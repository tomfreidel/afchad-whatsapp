"""
אפחד - WhatsApp AI Agent
Webhook server that receives messages from Green API and responds using AI.
"""

import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime
import pytz

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import settings
from agent import get_response
from database import init_db

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("אפחד")

# Simple deduplication: track recent message IDs
_seen_messages: dict[str, float] = {}
DEDUP_WINDOW = 60  # seconds


def _cleanup_seen():
    """Remove old entries from dedup cache."""
    now = time.time()
    expired = [k for k, v in _seen_messages.items() if now - v > DEDUP_WINDOW]
    for k in expired:
        del _seen_messages[k]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("אפחד is ready")
    yield


app = FastAPI(title="אפחד", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "אפחד"}


@app.post("/webhook/green-api")
async def webhook(request: Request):
    """Handle incoming messages from Green API."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    # Only process incoming text messages
    webhook_type = data.get("typeWebhook")
    if webhook_type != "incomingMessageReceived":
        return {"ok": True, "skipped": webhook_type}

    message_data = data.get("messageData", {})
    message_type = message_data.get("typeMessage")
    if message_type != "textMessage":
        return {"ok": True, "skipped": message_type}

    # Extract sender and message
    sender_data = data.get("senderData", {})
    chat_id = sender_data.get("chatId", "")
    sender_name = sender_data.get("senderName", "")
    text = message_data.get("textMessageData", {}).get("textMessage", "")
    message_id = data.get("idMessage", "")

    # Skip group messages (only respond to direct messages)
    if "@g.us" in chat_id:
        return {"ok": True, "skipped": "group_message"}

    # Skip empty messages
    if not text.strip():
        return {"ok": True, "skipped": "empty"}

    # Deduplication
    _cleanup_seen()
    if message_id in _seen_messages:
        return {"ok": True, "skipped": "duplicate"}
    _seen_messages[message_id] = time.time()

    # Extract phone number from chat_id (remove @c.us)
    phone = chat_id.replace("@c.us", "")

    logger.info(f"Message from {sender_name} ({phone}): {text[:50]}...")

    # Get AI response
    try:
        reply = get_response(phone, text, sender_name)
    except Exception as e:
        logger.error(f"Agent error: {e}")
        reply = "סליחה, משהו השתבש. נסה שוב בעוד רגע."

    # Send reply via Green API
    try:
        await send_whatsapp_message(chat_id, reply)
        logger.info(f"Reply sent to {phone}: {reply[:50]}...")
    except Exception as e:
        logger.error(f"Failed to send reply: {e}")

    return {"ok": True}


async def send_whatsapp_message(chat_id: str, message: str):
    """Send a text message via Green API."""
    url = (
        f"{settings.GREEN_API_URL}"
        f"/waInstance{settings.GREEN_API_INSTANCE}"
        f"/sendMessage/{settings.GREEN_API_TOKEN}"
    )
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={"chatId": chat_id, "message": message},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


@app.post("/cron/reminder")
async def cron_reminder(request: Request):
    """Called by cron-job.org to send proactive reminders to Tom."""
    # Verify secret token
    secret = request.headers.get("X-Cron-Secret", "")
    if not settings.CRON_SECRET or secret != settings.CRON_SECRET:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    israel_tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(israel_tz)
    weekday = now.weekday()  # 0=Monday, 4=Friday, 6=Sunday

    chat_id = f"{settings.TOM_PHONE}@c.us"
    message = None

    if weekday == 4:  # Friday
        message = "אחוי, שישי היום 🕍 דיברת עם סבתא? אם לא - עכשיו הזמן!"
    elif weekday == 6:  # Sunday
        message = "יא מלך, שבוע חדש מתחיל 💪 דיברת עם ההורים השבוע? אם לא - תקים אותם היום!"

    if not message:
        return {"ok": True, "skipped": "no reminder today"}

    try:
        await send_whatsapp_message(chat_id, message)
        logger.info(f"Cron reminder sent: {message}")
        return {"ok": True, "sent": message}
    except Exception as e:
        logger.error(f"Cron reminder failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
