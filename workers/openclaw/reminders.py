"""
OpenClaw Reminders — SQLite-backed reminder system with desktop notifications
"""
import sqlite3
import threading
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    from plyer import notification
    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False
    logger.warning("plyer not available - notifications disabled")

DB_PATH = Path(__file__).parent.parent.parent / "config" / "reminders.db"


class RemindersManager:
    """SQLite-backed reminder system"""

    def __init__(self):
        self.db_path = DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.running = False
        self.thread = None

    def _init_db(self):
        """Initialize database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_dt TEXT NOT NULL,
                repeat TEXT,
                dismissed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def add_reminder(self, title: str, due_dt: datetime, repeat: Optional[str] = None) -> int:
        """Add a reminder"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reminders (title, due_dt, repeat)
            VALUES (?, ?, ?)
        ''', (title, due_dt.isoformat(), repeat))
        conn.commit()
        reminder_id = cursor.lastrowid
        conn.close()
        return reminder_id

    def get_due_reminders(self) -> List[Dict[str, Any]]:
        """Get reminders due in the next 60 minutes"""
        now = datetime.now()
        window_end = now + timedelta(minutes=60)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM reminders
            WHERE dismissed = 0
            AND datetime(due_dt) BETWEEN datetime(?) AND datetime(?)
            ORDER BY due_dt ASC
        ''', (now.isoformat(), window_end.isoformat()))

        reminders = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return reminders

    def dismiss_reminder(self, reminder_id: int):
        """Mark a reminder as dismissed"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('UPDATE reminders SET dismissed = 1 WHERE id = ?', (reminder_id,))
        conn.commit()
        conn.close()

    def start_background_checker(self):
        """Start the background thread that checks for due reminders"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._check_loop, daemon=True)
        self.thread.start()
        logger.info("Reminders background checker started")

    def stop_background_checker(self):
        """Stop the background checker"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)

    def _check_loop(self):
        """Background loop to check for due reminders"""
        last_check = {}

        while self.running:
            try:
                due_reminders = self.get_due_reminders()

                for reminder in due_reminders:
                    reminder_id = reminder['id']

                    # Skip if we already notified about this reminder recently
                    if reminder_id in last_check:
                        if (datetime.now() - last_check[reminder_id]).seconds < 300:
                            continue

                    # Fire notification
                    self._fire_notification(reminder)

                    # Mark as notified
                    last_check[reminder_id] = datetime.now()

                    # Auto-dismiss if not repeating
                    if not reminder.get('repeat'):
                        self.dismiss_reminder(reminder_id)

                # Clean up old entries from last_check
                old_ids = [
                    rid for rid, ts in last_check.items()
                    if (datetime.now() - ts).seconds > 3600
                ]
                for rid in old_ids:
                    del last_check[rid]

            except Exception as e:
                logger.error(f"Error in reminders check loop: {e}")

            time.sleep(60)  # Check every 60 seconds

    def _fire_notification(self, reminder: Dict[str, Any]):
        """Fire a desktop notification for a reminder"""
        if not PLYER_AVAILABLE:
            logger.info(f"Reminder due: {reminder['title']}")
            return

        try:
            notification.notify(
                title="⏰ Sentinel Reminder",
                message=reminder['title'],
                app_name="SentinelAI",
                timeout=10
            )
            logger.info(f"Notification fired: {reminder['title']}")
        except Exception as e:
            logger.error(f"Failed to fire notification: {e}")


_reminders_manager = None


def get_reminders_manager() -> RemindersManager:
    """Get or create the global RemindersManager instance"""
    global _reminders_manager
    if _reminders_manager is None:
        _reminders_manager = RemindersManager()
        _reminders_manager.start_background_checker()
    return _reminders_manager
