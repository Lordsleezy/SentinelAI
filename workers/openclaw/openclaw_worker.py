"""
OpenClaw Worker — Personal Information Management Router
Routes intents to Calendar, Contacts, Reminders, Web, Notes
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Import submodules with graceful fallback
try:
    from .calendar import get_calendar_manager
    CALENDAR_AVAILABLE = True
except Exception as e:
    CALENDAR_AVAILABLE = False
    logger.warning(f"Calendar module unavailable: {e}")

try:
    from .contacts import get_contacts_manager
    CONTACTS_AVAILABLE = True
except Exception as e:
    CONTACTS_AVAILABLE = False
    logger.warning(f"Contacts module unavailable: {e}")

try:
    from .reminders import get_reminders_manager
    REMINDERS_AVAILABLE = True
except Exception as e:
    REMINDERS_AVAILABLE = False
    logger.warning(f"Reminders module unavailable: {e}")

try:
    from . import web
    WEB_AVAILABLE = True
except Exception as e:
    WEB_AVAILABLE = False
    logger.warning(f"Web module unavailable: {e}")

try:
    from . import notes
    NOTES_AVAILABLE = True
except Exception as e:
    NOTES_AVAILABLE = False
    logger.warning(f"Notes module unavailable: {e}")


def handle_intent(intent: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Route intent to the appropriate OpenClaw module"""

    # Calendar intents
    if intent == "calendar.list":
        if not CALENDAR_AVAILABLE:
            return {"status": "error", "message": "Google Calendar not configured"}

        try:
            cal = get_calendar_manager()
            days = payload.get('days', 7)
            events = cal.list_upcoming_events(days=days)
            return {"status": "ok", "result": events}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif intent == "calendar.create":
        if not CALENDAR_AVAILABLE:
            return {"status": "error", "message": "Google Calendar not configured"}

        try:
            cal = get_calendar_manager()

            title = payload.get('title')
            start_dt = datetime.fromisoformat(payload.get('start_dt'))
            end_dt = datetime.fromisoformat(payload.get('end_dt'))
            description = payload.get('description', '')
            reminder_minutes = payload.get('reminder_minutes', 15)

            event_id = cal.create_event(title, start_dt, end_dt, description, reminder_minutes)
            return {"status": "ok", "result": {"event_id": event_id}}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif intent == "calendar.delete":
        if not CALENDAR_AVAILABLE:
            return {"status": "error", "message": "Google Calendar not configured"}

        try:
            cal = get_calendar_manager()
            event_id = payload.get('event_id')
            success = cal.delete_event(event_id)
            return {"status": "ok", "result": {"deleted": success}}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # Contacts intents
    elif intent == "contacts.search":
        if not CONTACTS_AVAILABLE:
            return {"status": "error", "message": "Google Contacts not configured"}

        try:
            contacts = get_contacts_manager()
            query = payload.get('query', '')
            results = contacts.search_contacts(query)
            return {"status": "ok", "result": results}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif intent == "contacts.create":
        if not CONTACTS_AVAILABLE:
            return {"status": "error", "message": "Google Contacts not configured"}

        try:
            contacts = get_contacts_manager()
            resource_name = contacts.create_contact(
                given_name=payload.get('given_name'),
                family_name=payload.get('family_name'),
                email=payload.get('email'),
                phone=payload.get('phone', '')
            )
            return {"status": "ok", "result": {"resource_name": resource_name}}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # Reminders intents
    elif intent == "reminders.add":
        if not REMINDERS_AVAILABLE:
            return {"status": "error", "message": "Reminders not available"}

        try:
            reminders = get_reminders_manager()
            title = payload.get('title')
            due_dt = datetime.fromisoformat(payload.get('due_dt'))
            repeat = payload.get('repeat')

            reminder_id = reminders.add_reminder(title, due_dt, repeat)
            return {"status": "ok", "result": {"reminder_id": reminder_id}}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif intent == "reminders.due":
        if not REMINDERS_AVAILABLE:
            return {"status": "error", "message": "Reminders not available"}

        try:
            reminders = get_reminders_manager()
            due_list = reminders.get_due_reminders()
            return {"status": "ok", "result": due_list}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif intent == "reminders.dismiss":
        if not REMINDERS_AVAILABLE:
            return {"status": "error", "message": "Reminders not available"}

        try:
            reminders = get_reminders_manager()
            reminder_id = payload.get('reminder_id')
            reminders.dismiss_reminder(reminder_id)
            return {"status": "ok", "result": {"dismissed": True}}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # Web intents
    elif intent == "web.search":
        if not WEB_AVAILABLE:
            return {"status": "error", "message": "Web module not available"}

        try:
            query = payload.get('query')
            num_results = payload.get('num_results', 5)
            result = web.search_web(query, num_results)

            if result.get('error'):
                return {"status": "error", "message": result['error']}

            return {"status": "ok", "result": result['results']}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif intent == "web.fetch":
        if not WEB_AVAILABLE:
            return {"status": "error", "message": "Web module not available"}

        try:
            url = payload.get('url')
            result = web.fetch_page(url)

            if result.get('error'):
                return {"status": "error", "message": result['error']}

            return {"status": "ok", "result": {"text": result['text']}}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif intent == "web.summarize":
        if not WEB_AVAILABLE:
            return {"status": "error", "message": "Web module not available"}

        try:
            url = payload.get('url')
            result = web.summarize_page(url)

            if result.get('error'):
                return {"status": "error", "message": result['error']}

            return {"status": "ok", "result": {"summary": result['summary']}}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # Notes intents
    elif intent == "notes.create":
        if not NOTES_AVAILABLE:
            return {"status": "error", "message": "Notes module not available"}

        try:
            title = payload.get('title')
            content = payload.get('content')
            result = notes.create_note(title, content)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif intent == "notes.list":
        if not NOTES_AVAILABLE:
            return {"status": "error", "message": "Notes module not available"}

        try:
            result = notes.list_notes()
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif intent == "notes.search":
        if not NOTES_AVAILABLE:
            return {"status": "error", "message": "Notes module not available"}

        try:
            query = payload.get('query')
            result = notes.search_notes(query)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif intent == "notes.append":
        if not NOTES_AVAILABLE:
            return {"status": "error", "message": "Notes module not available"}

        try:
            title = payload.get('title')
            content = payload.get('content')
            result = notes.append_to_note(title, content)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    else:
        return {"status": "error", "message": f"Unknown intent: {intent}"}
