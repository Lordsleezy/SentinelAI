"""
workers/licensing/trial_manager.py — 7-day free trial system for SentinelAI.
"""
import os
import json
import uuid
from datetime import datetime, timedelta


class TrialManager:
    """Manages the 7-day free trial. No credit card, no signup."""

    TRIAL_FILE = os.path.expanduser("~/.sentinelai/trial.json")
    TRIAL_DAYS = 7

    def start_trial(self) -> dict | None:
        """Start trial if not already started. Returns trial data or None."""
        if self.get_trial_data():
            return None

        trial_data = {
            'started_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(days=self.TRIAL_DAYS)).isoformat(),
            'trial_id': uuid.uuid4().hex,
        }

        os.makedirs(os.path.dirname(self.TRIAL_FILE), exist_ok=True)
        with open(self.TRIAL_FILE, 'w') as f:
            json.dump(trial_data, f, indent=2)

        return trial_data

    def get_trial_data(self) -> dict | None:
        try:
            with open(self.TRIAL_FILE) as f:
                return json.load(f)
        except Exception:
            return None

    def get_status(self) -> dict:
        """
        Returns trial status dict:
          active, expired, days_remaining, hours_remaining,
          started_at, expires_at
        """
        data = self.get_trial_data()
        if not data:
            return {
                'active': False,
                'expired': False,
                'days_remaining': 0,
                'hours_remaining': 0,
                'never_started': True,
            }

        expires = datetime.fromisoformat(data['expires_at'])
        now = datetime.now()
        remaining = expires - now

        if remaining.total_seconds() <= 0:
            return {
                'active': False,
                'expired': True,
                'days_remaining': 0,
                'hours_remaining': 0,
                'expires_at': data['expires_at'],
            }

        return {
            'active': True,
            'expired': False,
            'days_remaining': remaining.days,
            'hours_remaining': remaining.seconds // 3600,
            'expires_at': data['expires_at'],
            'started_at': data['started_at'],
        }

    def is_valid(self) -> bool:
        """True if trial is active and not expired."""
        return self.get_status().get('active', False)


_trial_manager_instance = None


def get_trial_manager() -> TrialManager:
    global _trial_manager_instance
    if _trial_manager_instance is None:
        _trial_manager_instance = TrialManager()
    return _trial_manager_instance
