"""
Google Calendar integration.
Provides functions to create, list, update, and delete calendar events.
"""

import os
import json
import datetime

CALENDAR_AVAILABLE = False
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from googleapiclient.discovery import build
    CALENDAR_AVAILABLE = True
except ImportError:
    pass

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "token.json")
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")


def _get_calendar_service():
    """Get authenticated Google Calendar service. Auto-refreshes token."""
    if not CALENDAR_AVAILABLE:
        raise RuntimeError("חיבור היומן לא זמין כרגע - חסרות חבילות נדרשות")

    creds = None

    # Try loading from environment variable first (for Render deployment)
    token_json = os.getenv("GOOGLE_CALENDAR_TOKEN")
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    elif os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds:
        raise RuntimeError("חיבור היומן לא זמין כרגע - צריך להגדיר אימות קודם")

    # Always refresh if expired or about to expire - refresh_token never expires
    if not creds.valid or creds.expired:
        if creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
            # Save locally if possible
            try:
                with open(TOKEN_PATH, "w") as token:
                    token.write(creds.to_json())
            except Exception:
                pass  # On Render, filesystem may be read-only - that's ok
        else:
            raise RuntimeError("חיבור היומן לא זמין - צריך לחדש אימות")

    return build("calendar", "v3", credentials=creds)


def list_events(date: str = None, max_results: int = 10) -> str:
    """List upcoming events. If date is provided (YYYY-MM-DD), show events for that day."""
    service = _get_calendar_service()
    if date:
        start = datetime.datetime.fromisoformat(date)
        end = start + datetime.timedelta(days=1)
        time_min = start.isoformat() + "Z"
        time_max = end.isoformat() + "Z"
    else:
        time_min = datetime.datetime.utcnow().isoformat() + "Z"
        time_max = None

    kwargs = {
        "calendarId": "primary",
        "timeMin": time_min,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if time_max:
        kwargs["timeMax"] = time_max

    results = service.events().list(**kwargs).execute()
    events = results.get("items", [])

    if not events:
        return "אין אירועים קרובים ביומן."

    lines = []
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        summary = event.get("summary", "ללא כותרת")
        event_id = event.get("id", "")
        lines.append(f"- {start}: {summary} [event_id: {event_id}]")
    return "\n".join(lines)


COLORS = {
    "כחול": "9", "blue": "9",
    "ירוק": "2", "green": "2",
    "צהוב": "5", "yellow": "5",
    "כתום": "6", "orange": "6",
    "אדום": "11", "red": "11",
    "ורוד": "4", "pink": "4",
    "סגול": "3", "purple": "3",
    "תכלת": "7", "teal": "7",
}


def create_event(summary: str, start_time: str, end_time: str, description: str = "", color: str = "") -> str:
    """Create a new calendar event.
    start_time and end_time should be ISO format (e.g., 2026-04-09T10:00:00).
    color: optional color name in Hebrew or English (e.g., כחול, ירוק, אדום).
    """
    service = _get_calendar_service()
    event = {
        "summary": summary,
        "start": {"dateTime": start_time, "timeZone": "Asia/Jerusalem"},
        "end": {"dateTime": end_time, "timeZone": "Asia/Jerusalem"},
    }
    if description:
        event["description"] = description
    if color:
        color_id = COLORS.get(color.lower().strip())
        if color_id:
            event["colorId"] = color_id

    created = service.events().insert(calendarId="primary", body=event).execute()
    return f"אירוע נוצר: {created.get('summary')} ב-{start_time}"


def update_event(event_id: str, summary: str = None, start_time: str = None, end_time: str = None) -> str:
    """Update an existing calendar event by ID."""
    service = _get_calendar_service()
    event = service.events().get(calendarId="primary", eventId=event_id).execute()

    if summary:
        event["summary"] = summary
    if start_time:
        event["start"] = {"dateTime": start_time, "timeZone": "Asia/Jerusalem"}
    if end_time:
        event["end"] = {"dateTime": end_time, "timeZone": "Asia/Jerusalem"}

    updated = service.events().update(calendarId="primary", eventId=event_id, body=event).execute()
    return f"אירוע עודכן: {updated.get('summary')}"


def delete_event(event_id: str) -> str:
    """Delete a calendar event by ID."""
    service = _get_calendar_service()
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return "האירוע נמחק בהצלחה."
