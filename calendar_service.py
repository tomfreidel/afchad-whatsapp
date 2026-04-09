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


def _fmt_time(dt_str: str) -> str:
    """Format ISO datetime string to HH:MM."""
    try:
        dt = datetime.datetime.fromisoformat(dt_str)
        return dt.strftime("%H:%M")
    except Exception:
        return dt_str


def _parse_dt(dt_str: str):
    """Parse ISO datetime string to datetime object (timezone-aware or naive)."""
    try:
        return datetime.datetime.fromisoformat(dt_str)
    except Exception:
        return None


def list_events(date: str = None, max_results: int = 20) -> str:
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

    # Parse events
    parsed = []
    for event in events:
        start_raw = event["start"].get("dateTime", event["start"].get("date"))
        end_raw = event["end"].get("dateTime", event["end"].get("date"))
        summary = event.get("summary", "ללא כותרת")
        event_id = event.get("id", "")
        start_dt = _parse_dt(start_raw)
        end_dt = _parse_dt(end_raw)
        parsed.append((start_dt, end_dt, summary, event_id, start_raw, end_raw))

    # Build lines with formatted times
    lines = []
    if date and parsed:
        # Show day header
        first_dt = parsed[0][0]
        if first_dt:
            day_names = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
            day_name = day_names[first_dt.weekday()]
            lines.append(f"יום {day_name} {first_dt.strftime('%d/%m/%Y')}:")
            lines.append("")

    for start_dt, end_dt, summary, event_id, start_raw, end_raw in parsed:
        if start_dt and end_dt:
            start_str = _fmt_time(start_raw)
            end_str = _fmt_time(end_raw)
            lines.append(f"{start_str} - {end_str} | {summary} [event_id: {event_id}]")
        else:
            # All-day event
            lines.append(f"כל היום | {summary} [event_id: {event_id}]")

    # Detect conflicts (overlapping events)
    conflicts = []
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            s1, e1 = parsed[i][0], parsed[i][1]
            s2, e2 = parsed[j][0], parsed[j][1]
            if s1 and e1 and s2 and e2:
                # Make both timezone-naive or both timezone-aware for comparison
                try:
                    if s1.tzinfo and not s2.tzinfo:
                        s2 = s2.replace(tzinfo=s1.tzinfo)
                        e2 = e2.replace(tzinfo=e1.tzinfo)
                    elif s2.tzinfo and not s1.tzinfo:
                        s1 = s1.replace(tzinfo=s2.tzinfo)
                        e1 = e1.replace(tzinfo=e2.tzinfo)
                    if s1 < e2 and s2 < e1:
                        conflicts.append(f"⚠️ התנגשות: {parsed[i][2]} ({_fmt_time(parsed[i][4])}-{_fmt_time(parsed[i][5])}) חופף עם {parsed[j][2]} ({_fmt_time(parsed[j][4])}-{_fmt_time(parsed[j][5])})")
                except Exception:
                    pass

    if conflicts:
        lines.append("")
        lines.extend(conflicts)

    # Free windows (only when showing a specific day, between 08:00-22:00)
    if date and parsed:
        try:
            first_dt = parsed[0][0]
            if first_dt:
                tz = first_dt.tzinfo
                base = first_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                day_start = base.replace(hour=8)
                day_end = base.replace(hour=22)

                busy = []
                for start_dt, end_dt, _, _, _, _ in parsed:
                    if start_dt and end_dt:
                        s = max(start_dt, day_start)
                        e = min(end_dt, day_end)
                        if s < e:
                            busy.append((s, e))
                busy.sort()

                free = []
                cursor = day_start
                for s, e in busy:
                    if cursor < s:
                        free.append((cursor, s))
                    cursor = max(cursor, e)
                if cursor < day_end:
                    free.append((cursor, day_end))

                if free:
                    lines.append("")
                    lines.append("חלונות פנויים:")
                    for fs, fe in free:
                        diff = (fe - fs).seconds // 60
                        hours = diff // 60
                        mins = diff % 60
                        dur = f"{hours} שעות" if hours and not mins else (f"{hours} שעה" if hours == 1 else "") + (f" ו-{mins} דק'" if mins and hours else f"{mins} דק'")
                        lines.append(f"• {fs.strftime('%H:%M')} - {fe.strftime('%H:%M')} ({dur.strip()})")
        except Exception:
            pass

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


def create_event(summary: str, start_time: str, end_time: str, description: str = "", color: str = "", attendees: str = "") -> str:
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
    if attendees:
        event["attendees"] = [{"email": e.strip()} for e in attendees.split(",") if e.strip()]

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
