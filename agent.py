"""
אפחד - AI conversation logic.
Handles message processing, conversation history, and LLM calls with Google Calendar tools.
"""

import json
import logging
from config import settings
from database import get_history, save_message
from openai import OpenAI
from calendar_service import list_events, create_event, update_event, delete_event

logger = logging.getLogger("אפחד")

client = OpenAI(api_key=settings.OPENAI_API_KEY)

calendar_tools = [
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "רשימת אירועים ביומן. אם מציינים תאריך (YYYY-MM-DD) מציג רק את אותו יום.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "תאריך בפורמט YYYY-MM-DD"},
                    "max_results": {"type": "integer", "description": "מספר מקסימלי של אירועים"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "יצירת אירוע חדש ביומן",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "שם האירוע"},
                    "start_time": {"type": "string", "description": "שעת התחלה ISO, למשל 2026-04-09T10:00:00"},
                    "end_time": {"type": "string", "description": "שעת סיום ISO"},
                    "description": {"type": "string", "description": "תיאור אופציונלי"}
                },
                "required": ["summary", "start_time", "end_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_event",
            "description": "עדכון אירוע קיים ביומן לפי מזהה",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "מזהה האירוע"},
                    "summary": {"type": "string", "description": "שם חדש"},
                    "start_time": {"type": "string", "description": "שעת התחלה חדשה ISO"},
                    "end_time": {"type": "string", "description": "שעת סיום חדשה ISO"}
                },
                "required": ["event_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": "מחיקת אירוע מהיומן לפי מזהה",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "מזהה האירוע למחיקה"}
                },
                "required": ["event_id"]
            }
        }
    }
]

TOOL_FUNCTIONS = {
    "list_events": list_events,
    "create_event": create_event,
    "update_event": update_event,
    "delete_event": delete_event,
}


def get_response(phone: str, message: str, sender_name: str = "") -> str:
    """Process a message and return an AI response."""

    history = get_history(phone, limit=settings.MAX_HISTORY)

    messages = [{"role": "system", "content": settings.SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        tools=calendar_tools,
        tool_choice="auto",
    )

    reply_message = response.choices[0].message

    while reply_message.tool_calls:
        messages.append(reply_message)

        for tool_call in reply_message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)
            func = TOOL_FUNCTIONS.get(func_name)
            try:
                result = func(**func_args) if func else f"פונקציה לא נמצאה: {func_name}"
                logger.info(f"Tool {func_name} result: {result}")
            except Exception as e:
                result = f"שגיאה: {str(e)}"
                logger.error(f"Tool {func_name} error: {e}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            tools=calendar_tools,
            tool_choice="auto",
        )
        reply_message = response.choices[0].message

    reply = reply_message.content

    save_message(phone, "user", message)
    save_message(phone, "assistant", reply)

    return reply
