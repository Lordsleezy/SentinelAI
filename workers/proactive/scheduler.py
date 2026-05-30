"""
Proactive Scheduler — Morning briefings, health checks, camera watch
"""
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    logger.warning("apscheduler not installed - proactive agents disabled")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class ProactiveScheduler:
    """Background scheduler for proactive agent tasks"""

    def __init__(self):
        self.scheduler = None
        self.enabled = os.getenv('PROACTIVE_ENABLED', 'true').lower() == 'true'
        self.api_base = "http://127.0.0.1:5001"
        self.memory_vault = Path(__file__).parent.parent.parent / "memory" / "vault"

    def start(self):
        """Start the proactive scheduler"""
        if not SCHEDULER_AVAILABLE:
            logger.warning("Proactive scheduler not available - dependencies missing")
            return

        if not self.enabled:
            logger.info("Proactive scheduler disabled via PROACTIVE_ENABLED=false")
            return

        self.scheduler = BackgroundScheduler()

        # Morning briefing - daily at configured time
        morning_time = os.getenv('MORNING_BRIEFING_TIME', '07:00')
        hour, minute = map(int, morning_time.split(':'))

        self.scheduler.add_job(
            self._morning_briefing,
            CronTrigger(hour=hour, minute=minute),
            id='morning_briefing',
            name='Morning Briefing'
        )

        # Earn scanner summary - every 4 hours
        self.scheduler.add_job(
            self._earn_summary,
            IntervalTrigger(hours=4),
            id='earn_summary',
            name='Earn Scanner Summary'
        )

        # System health check - every 30 minutes
        self.scheduler.add_job(
            self._health_check,
            IntervalTrigger(minutes=30),
            id='health_check',
            name='System Health Check'
        )

        # Camera watch - every 15 minutes
        self.scheduler.add_job(
            self._camera_watch,
            IntervalTrigger(minutes=15),
            id='camera_watch',
            name='Camera Watch'
        )

        self.scheduler.start()
        logger.info("Proactive scheduler started")

    def stop(self):
        """Stop the scheduler"""
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("Proactive scheduler stopped")

    def _morning_briefing(self):
        """Generate and send morning briefing"""
        logger.info("Running morning briefing...")

        try:
            briefing_parts = []

            # Weather
            weather = self._get_weather()
            if weather:
                briefing_parts.append(f"🌤 Weather: {weather}")

            # Calendar
            calendar = self._get_calendar()
            if calendar:
                briefing_parts.append(f"\n📅 Today's Calendar:\n{calendar}")

            # Reminders
            reminders = self._get_reminders()
            if reminders:
                briefing_parts.append(f"\n⏰ Reminders:\n{reminders}")

            # Earn jobs
            earn = self._get_earn_jobs()
            if earn:
                briefing_parts.append(f"\n💰 New Opportunities:\n{earn}")

            # Health summary
            health = self._get_health()
            if health:
                briefing_parts.append(f"\n❤️ Health: {health}")

            # Finance summary
            finance = self._get_finance()
            if finance:
                briefing_parts.append(f"\n💵 Finance: {finance}")

            # News headlines
            news = self._get_news()
            if news:
                briefing_parts.append(f"\n📰 News:\n{news}")

            # Compose full briefing
            briefing = "☀️ **Good Morning!**\n\n" + "\n".join(briefing_parts)

            # Save to memory vault
            self._save_briefing(briefing)

            # Send via Telegram if configured
            self._send_telegram(briefing)

            logger.info("Morning briefing complete")

        except Exception as e:
            logger.exception(f"Morning briefing failed: {e}")

    def _earn_summary(self):
        """Check for new earn jobs and notify"""
        logger.info("Running earn scanner summary...")

        try:
            if not HTTPX_AVAILABLE:
                return

            with httpx.Client() as client:
                response = client.get(f"{self.api_base}/earn/jobs?limit=10", timeout=10.0)
                data = response.json()

                if data.get('status') == 'ok':
                    jobs = data.get('data', [])

                    if jobs:
                        msg = f"💰 Found {len(jobs)} new opportunities!\n\n"
                        top_job = jobs[0]
                        msg += f"Top: {top_job.get('title', 'Untitled')} - {top_job.get('reward_range', 'N/A')}"

                        self._send_telegram(msg)

        except Exception as e:
            logger.error(f"Earn summary failed: {e}")

    def _health_check(self):
        """Check system health and alert if issues"""
        logger.info("Running system health check...")

        try:
            if not HTTPX_AVAILABLE:
                return

            with httpx.Client() as client:
                response = client.get(f"{self.api_base}/api/status", timeout=5.0)
                data = response.json()

                # Log health snapshot
                health_log = self.memory_vault / "sessions" / f"health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                health_log.parent.mkdir(parents=True, exist_ok=True)

                health_content = f"# System Health Check\n\n**Time:** {datetime.now().isoformat()}\n\n"
                health_content += f"**Status:** {data.get('status', 'unknown')}\n"

                health_log.write_text(health_content, encoding='utf-8')

                # Alert if down
                if data.get('status') != 'ok':
                    self._send_telegram(f"⚠️ System health check: {data.get('status', 'unknown')}")

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self._send_telegram(f"❌ Health check failed: {str(e)}")

    def _camera_watch(self):
        """Check cameras for activity"""
        logger.info("Running camera watch...")

        try:
            if not HTTPX_AVAILABLE:
                return

            with httpx.Client() as client:
                response = client.post(f"{self.api_base}/home/camera/look_all", timeout=30.0)
                data = response.json()

                if data.get('status') == 'ok':
                    cameras = data.get('data', {}).get('cameras', {})

                    # Check for keywords
                    keywords = ['person', 'vehicle', 'package', 'delivery', 'unknown', 'motion']

                    for cam_name, description in cameras.items():
                        desc_lower = description.lower()

                        if any(kw in desc_lower for kw in keywords):
                            # Alert
                            msg = f"📷 {cam_name} activity detected:\n{description}"
                            self._send_telegram(msg)
                            logger.info(f"Camera alert: {cam_name}")

        except Exception as e:
            logger.error(f"Camera watch failed: {e}")

    # Helper methods for fetching data
    def _get_weather(self) -> Optional[str]:
        """Get weather summary"""
        try:
            lat = os.getenv('LATITUDE', '37.3382')
            lon = os.getenv('LONGITUDE', '-121.8863')

            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weathercode&timezone=auto"

            if not HTTPX_AVAILABLE:
                return None

            with httpx.Client() as client:
                response = client.get(url, timeout=10.0)
                data = response.json()

                temp = data.get('current', {}).get('temperature_2m')
                return f"{temp}°C" if temp else None

        except Exception:
            return None

    def _get_calendar(self) -> Optional[str]:
        """Get today's calendar events"""
        try:
            if not HTTPX_AVAILABLE:
                return None

            with httpx.Client() as client:
                response = client.get(f"{self.api_base}/openclaw/calendar/upcoming?days=1", timeout=5.0)
                data = response.json()

                if data.get('status') == 'ok' and data.get('result'):
                    events = data['result']
                    return "\n".join([f"- {e.get('summary', 'Untitled')}" for e in events[:3]])

        except Exception:
            return None

    def _get_reminders(self) -> Optional[str]:
        """Get due reminders"""
        try:
            if not HTTPX_AVAILABLE:
                return None

            with httpx.Client() as client:
                response = client.get(f"{self.api_base}/openclaw/reminders/due", timeout=5.0)
                data = response.json()

                if data.get('status') == 'ok' and data.get('result'):
                    reminders = data['result']
                    return "\n".join([f"- {r.get('title', 'Untitled')}" for r in reminders[:3]])

        except Exception:
            return None

    def _get_earn_jobs(self) -> Optional[str]:
        """Get top earn opportunities"""
        try:
            if not HTTPX_AVAILABLE:
                return None

            with httpx.Client() as client:
                response = client.get(f"{self.api_base}/earn/jobs?limit=3", timeout=5.0)
                data = response.json()

                if data.get('status') == 'ok' and data.get('data'):
                    jobs = data['data']
                    return "\n".join([f"- {j.get('title', 'Untitled')} ({j.get('source', 'unknown')})" for j in jobs])

        except Exception:
            return None

    def _get_health(self) -> Optional[str]:
        """Get health summary"""
        try:
            if not HTTPX_AVAILABLE:
                return None

            with httpx.Client() as client:
                response = client.get(f"{self.api_base}/health/summary", timeout=5.0)
                data = response.json()

                if data.get('status') == 'ok':
                    return data.get('data', {}).get('summary', '')

        except Exception:
            return None

    def _get_finance(self) -> Optional[str]:
        """Get finance summary"""
        try:
            if not HTTPX_AVAILABLE:
                return None

            with httpx.Client() as client:
                response = client.get(f"{self.api_base}/finance/summary", timeout=5.0)
                data = response.json()

                if data.get('status') == 'ok':
                    return data.get('data', {}).get('summary', '')

        except Exception:
            return None

    def _get_news(self) -> Optional[str]:
        """Get news headlines"""
        try:
            if not HTTPX_AVAILABLE:
                return None

            with httpx.Client() as client:
                response = client.get(f"{self.api_base}/news/headlines", timeout=5.0)
                data = response.json()

                if data.get('status') == 'ok' and data.get('data'):
                    headlines = data['data']
                    return "\n".join([f"- {h.get('title', 'Untitled')}" for h in headlines[:3]])

        except Exception:
            return None

    def _save_briefing(self, briefing: str):
        """Save briefing to memory vault"""
        try:
            briefing_file = self.memory_vault / "sessions" / f"morning_briefing_{datetime.now().strftime('%Y%m%d')}.md"
            briefing_file.parent.mkdir(parents=True, exist_ok=True)

            content = f"# Morning Briefing\n\n**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{briefing}"
            briefing_file.write_text(content, encoding='utf-8')

        except Exception as e:
            logger.error(f"Failed to save briefing: {e}")

    def _send_telegram(self, message: str):
        """Send message via Telegram if configured"""
        try:
            bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
            user_id = os.getenv('TELEGRAM_ALLOWED_USER_ID')

            if not bot_token or not user_id or not HTTPX_AVAILABLE:
                return

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

            with httpx.Client() as client:
                client.post(
                    url,
                    json={"chat_id": user_id, "text": message, "parse_mode": "Markdown"},
                    timeout=10.0
                )

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    def get_status(self) -> dict:
        """Get scheduler status"""
        if not self.scheduler:
            return {"running": False, "jobs": []}

        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None
            })

        return {
            "running": self.scheduler.running,
            "jobs": jobs
        }


# Global instance
_scheduler: Optional[ProactiveScheduler] = None


def start_scheduler():
    """Start the global proactive scheduler"""
    global _scheduler
    if _scheduler is None:
        _scheduler = ProactiveScheduler()
    _scheduler.start()


def stop_scheduler():
    """Stop the global proactive scheduler"""
    global _scheduler
    if _scheduler:
        _scheduler.stop()


def get_scheduler() -> Optional[ProactiveScheduler]:
    """Get the global scheduler instance"""
    return _scheduler
