"""
OpenClaw Calendar — Google Calendar integration
"""
import os
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

# Google Calendar API imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False


SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDS_PATH = Path(__file__).parent.parent.parent / "config" / "google_creds.json"
TOKEN_PATH = Path(__file__).parent.parent.parent / "config" / "calendar_token.pickle"


class CalendarManager:
    """Google Calendar integration"""

    def __init__(self):
        self.service = None
        self._connect()

    def _connect(self):
        """Connect to Google Calendar API"""
        if not GOOGLE_AVAILABLE:
            raise RuntimeError("Google Calendar libraries not installed (pip install google-api-python-client google-auth-oauthlib)")

        creds = None

        # Load token if exists
        if TOKEN_PATH.exists():
            with open(TOKEN_PATH, 'rb') as token:
                creds = pickle.load(token)

        # Refresh or request new token
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDS_PATH.exists():
                    raise FileNotFoundError(
                        f"Google credentials not found at {CREDS_PATH}. "
                        "Download from Google Cloud Console and save there."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
                creds = flow.run_local_server(port=0)

            # Save token
            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_PATH, 'wb') as token:
                pickle.dump(creds, token)

        self.service = build('calendar', 'v3', credentials=creds)

    def list_upcoming_events(self, days: int = 7, max_results: int = 10) -> List[Dict[str, Any]]:
        """List upcoming calendar events"""
        if not self.service:
            return []

        now = datetime.utcnow().isoformat() + 'Z'
        end = (datetime.utcnow() + timedelta(days=days)).isoformat() + 'Z'

        events_result = self.service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=end,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        return [
            {
                'id': event['id'],
                'summary': event.get('summary', 'No Title'),
                'start': event['start'].get('dateTime', event['start'].get('date')),
                'end': event['end'].get('dateTime', event['end'].get('date')),
                'description': event.get('description', ''),
                'location': event.get('location', '')
            }
            for event in events
        ]

    def create_event(
        self,
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        description: str = '',
        reminder_minutes: int = 15
    ) -> str:
        """Create a calendar event"""
        if not self.service:
            raise RuntimeError("Calendar service not connected")

        event = {
            'summary': title,
            'description': description,
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': 'UTC',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': reminder_minutes},
                ],
            },
        }

        created_event = self.service.events().insert(calendarId='primary', body=event).execute()
        return created_event['id']

    def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event"""
        if not self.service:
            return False

        try:
            self.service.events().delete(calendarId='primary', eventId=event_id).execute()
            return True
        except Exception:
            return False


# Singleton instance
_calendar_manager = None


def get_calendar_manager() -> CalendarManager:
    """Get or create the global CalendarManager instance"""
    global _calendar_manager
    if _calendar_manager is None:
        _calendar_manager = CalendarManager()
    return _calendar_manager
