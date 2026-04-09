"""
אפחד - AI conversation logic.
Handles message processing, conversation history, and LLM calls with Google Calendar tools.
"""

import json
import logging
from datetime import datetime
import pytz
from config import settings
from database import get_history, save_message, save_note, get_notes, delete_note, complete_note
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
                    "description": {"type": "string", "description": "תיאור אופציונלי"},
                    "color": {"type": "string", "description": "צבע האירוע בעברית או אנגלית (כחול, ירוק, אדום, כתום, ורוד, סגול, צהוב, תכלת)"},
                    "attendees": {"type": "string", "description": "אימיילים של מוזמנים מופרדים בפסיק, למשל: a@gmail.com,b@gmail.com"}
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
            "name": "save_note",
            "description": "שמירת מידע חשוב לזיכרון לטווח ארוך. השתמש בזה כשהמשתמש מבקש לזכור משהו, שומר רעיון, משימה, או כל מידע שצריך להישאר לאורך זמן.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "המידע לשמירה"}
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_notes",
            "description": "קבלת כל הפתקים השמורים בזיכרון. השתמש בזה כשהמשתמש שואל מה זכרת, מה הרעיונות שלו, מה המשימות, וכו'.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_note",
            "description": "מחיקת פתק מהזיכרון לפי מספר סידורי (1-based).",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_index": {"type": "integer", "description": "מספר הפתק למחיקה"}
                },
                "required": ["note_index"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "סימון משימה/פתק כבוצע (✅). השתמש בזה כשהמשתמש אומר שסיים משימה, שגמר עם משהו, שעשה את זה.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_index": {"type": "integer", "description": "מספר המשימה לסימון (1-based)"}
                },
                "required": ["note_index"]
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

def _save_note_for_phone(phone: str):
    def _save(content: str) -> str:
        return save_note(phone, content)
    return _save

def _get_notes_for_phone(phone: str):
    def _get() -> str:
        notes = get_notes(phone)
        if not notes:
            return "אין פתקים שמורים עדיין."
        return "\n".join(f"{i+1}. {n}" for i, n in enumerate(notes))
    return _get

def _delete_note_for_phone(phone: str):
    def _delete(note_index: int) -> str:
        return delete_note(phone, note_index)
    return _delete

def _complete_task_for_phone(phone: str):
    def _complete(note_index: int) -> str:
        return complete_note(phone, note_index)
    return _complete


def get_response(phone: str, message: str, sender_name: str = "") -> str:
    """Process a message and return an AI response."""

    history = get_history(phone, limit=settings.MAX_HISTORY)

    # Add current date/time to every message so model knows "today"/"tomorrow"
    israel_tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(israel_tz)
    date_prefix = f"[תאריך ושעה נוכחיים: {now.strftime('%A %d/%m/%Y %H:%M')} שעון ישראל]\n"
    message_with_date = date_prefix + message

    # Inject persistent notes/tasks into system prompt so model always "knows" them
    notes = get_notes(phone)
    if notes:
        pending = [n for n in notes if not n.startswith("✅")]
        done = [n for n in notes if n.startswith("✅")]
        notes_block = "\n\n=== זיכרון שמור של טום ==="
        if pending:
            notes_block += "\nמשימות/רעיונות פתוחים:\n" + "\n".join(f"{i+1}. {n}" for i, n in enumerate(notes) if not n.startswith("✅"))
        if done:
            notes_block += "\nבוצע:\n" + "\n".join(f"- {n}" for n in done)
        notes_block += "\n=== סוף זיכרון ==="
        system_content = settings.SYSTEM_PROMPT + notes_block
    else:
        system_content = settings.SYSTEM_PROMPT

    messages = [{"role": "system", "content": system_content}]
    messages.extend(history)
    messages.append({"role": "user", "content": message_with_date})

    TOOL_FUNCTIONS = {
        "list_events": list_events,
        "create_event": create_event,
        "update_event": update_event,
        "delete_event": delete_event,
        "save_note": _save_note_for_phone(phone),
        "get_notes": _get_notes_for_phone(phone),
        "delete_note": _delete_note_for_phone(phone),
        "complete_task": _complete_task_for_phone(phone),
    }

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
            print(f"[TOOL CALL] {func_name} args={func_args}", flush=True)
            try:
                result = func(**func_args) if func else f"פונקציה לא נמצאה: {func_name}"
                print(f"[TOOL RESULT] {func_name}: {result}", flush=True)
                logger.info(f"Tool {func_name} result: {result}")
            except Exception as e:
                result = f"שגיאה: {str(e)}"
                print(f"[TOOL ERROR] {func_name}: {e}", flush=True)
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
