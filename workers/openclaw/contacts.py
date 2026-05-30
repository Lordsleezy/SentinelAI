"""
OpenClaw Contacts — Google Contacts integration
"""
import os
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

SCOPES = ['https://www.googleapis.com/auth/contacts']
CREDS_PATH = Path(__file__).parent.parent.parent / "config" / "google_creds.json"
TOKEN_PATH = Path(__file__).parent.parent.parent / "config" / "contacts_token.pickle"


class ContactsManager:
    """Google Contacts integration"""

    def __init__(self):
        self.service = None
        if GOOGLE_AVAILABLE and CREDS_PATH.exists():
            try:
                self._connect()
            except Exception:
                pass  # Graceful failure

    def _connect(self):
        """Connect to Google Contacts API"""
        if not GOOGLE_AVAILABLE:
            return

        creds = None
        if TOKEN_PATH.exists():
            with open(TOKEN_PATH, 'rb') as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDS_PATH.exists():
                    return
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
                creds = flow.run_local_server(port=0)

            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_PATH, 'wb') as token:
                pickle.dump(creds, token)

        self.service = build('people', 'v1', credentials=creds)

    def search_contacts(self, query: str) -> List[Dict[str, Any]]:
        """Search contacts by name or email"""
        if not self.service:
            return []

        try:
            results = self.service.people().searchContacts(
                query=query,
                readMask='names,emailAddresses,phoneNumbers'
            ).execute()

            contacts = []
            for person in results.get('results', []):
                person_data = person.get('person', {})
                names = person_data.get('names', [])
                emails = person_data.get('emailAddresses', [])
                phones = person_data.get('phoneNumbers', [])

                contacts.append({
                    'resource_name': person_data.get('resourceName'),
                    'name': names[0].get('displayName') if names else '',
                    'email': emails[0].get('value') if emails else '',
                    'phone': phones[0].get('value') if phones else ''
                })

            return contacts

        except Exception:
            return []

    def get_contact(self, resource_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific contact by resource name"""
        if not self.service:
            return None

        try:
            person = self.service.people().get(
                resourceName=resource_name,
                personFields='names,emailAddresses,phoneNumbers'
            ).execute()

            names = person.get('names', [])
            emails = person.get('emailAddresses', [])
            phones = person.get('phoneNumbers', [])

            return {
                'resource_name': person.get('resourceName'),
                'name': names[0].get('displayName') if names else '',
                'email': emails[0].get('value') if emails else '',
                'phone': phones[0].get('value') if phones else ''
            }

        except Exception:
            return None

    def create_contact(
        self,
        given_name: str,
        family_name: str,
        email: str,
        phone: str = ''
    ) -> Optional[str]:
        """Create a new contact"""
        if not self.service:
            return None

        try:
            contact = {
                'names': [{
                    'givenName': given_name,
                    'familyName': family_name
                }]
            }

            if email:
                contact['emailAddresses'] = [{'value': email}]

            if phone:
                contact['phoneNumbers'] = [{'value': phone}]

            result = self.service.people().createContact(body=contact).execute()
            return result.get('resourceName')

        except Exception:
            return None


_contacts_manager = None


def get_contacts_manager() -> ContactsManager:
    """Get or create the global ContactsManager instance"""
    global _contacts_manager
    if _contacts_manager is None:
        _contacts_manager = ContactsManager()
    return _contacts_manager
