"""
אפחד - AI conversation logic.
Handles message processing, conversation history, and LLM calls with Google Calendar tools.
"""

import json
from config import settings
from database import get_history, save_message
from openai import OpenAI
from calendar_service import list_events, create_event, update_event, delete_event

client = OpenAI(
    api_key=settings.GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

# Define calendar tools for function calling
calendar_tools = [
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "List upcoming calendar events, or events for a specific date",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format. If not provided, shows upcoming events."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of events to return (default 10)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Create a new calendar event",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Event title/name"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time in ISO format, e.g. 2026-04-09T10:00:00"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "End time in ISO format, e.g. 2026-04-09T11:00:00"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional event description"
                    }
                },
                "required": ["summary", "start_time", "end_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_event",
            "description": "Update an existing calendar event",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The event ID to update"
                    },
                    "summary": {
                        "type": "string",
                        "description": "New event title"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "New start time in ISO format"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "New end time in ISO format"
                    }
                },
                "required": ["event_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": "Delete a calendar event",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The event ID to delete"
                    }
                },
                "required": ["event_id"]
            }
        }
    }
]

# Map function names to actual functions
TOOL_FUNCTIONS = {
    "list_events": list_events,
    "create_event": create_event,
    "update_event": update_event,
    "delete_event": delete_event,
}


def get_response(phone: str, message: str, sender_name: str = "") -> str:
    """Process a message and return an AI response."""

    # Load conversation history
    history = get_history(phone, limit=settings.MAX_HISTORY)

    # Build messages for LLM
    messages = [{"role": "system", "content": settings.SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    # Call LLM
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        tools=calendar_tools,
        tool_choice="auto",
    )

    reply_message = response.choices[0].message

    # Handle tool calls (calendar)
    while reply_message.tool_calls:
        messages.append(reply_message)

        for tool_call in reply_message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)

            func = TOOL_FUNCTIONS.get(func_name)
            if func:
                try:
                    result = func(**func_args)
                except Exception as e:
                    result = f"שגיאה: {str(e)}"
            else:
                result = f"פונקציה לא נמצאה: {func_name}"

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

    # Save conversation
    save_message(phone, "user", message)
    save_message(phone, "assistant", reply)

    return reply
