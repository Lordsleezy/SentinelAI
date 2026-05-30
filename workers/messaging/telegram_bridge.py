"""
Telegram Bridge — Control SentinelAI via Telegram
"""
import os
import logging
import threading
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed - Telegram bridge disabled")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class TelegramBridge:
    """Telegram bot bridge for SentinelAI control"""

    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.allowed_user_id = os.getenv('TELEGRAM_ALLOWED_USER_ID')
        self.application = None
        self.running = False
        self.thread = None
        self.api_base = "http://127.0.0.1:5001"

    def start(self):
        """Start the Telegram bridge"""
        if not TELEGRAM_AVAILABLE:
            logger.warning("Telegram bridge not available - dependencies missing")
            return

        if not self.bot_token:
            logger.info("TELEGRAM_BOT_TOKEN not set - Telegram bridge disabled")
            return

        if not self.allowed_user_id:
            logger.warning("TELEGRAM_ALLOWED_USER_ID not set - security risk, bridge disabled")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_bot, daemon=True)
        self.thread.start()
        logger.info("Telegram bridge started")

    def stop(self):
        """Stop the Telegram bridge"""
        self.running = False
        if self.application:
            # Schedule stop in the event loop
            asyncio.create_task(self.application.stop())

    def _run_bot(self):
        """Run the Telegram bot in background thread"""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Create application
            self.application = Application.builder().token(self.bot_token).build()

            # Register handlers
            self.application.add_handler(CommandHandler("status", self._handle_status))
            self.application.add_handler(CommandHandler("cameras", self._handle_cameras))
            self.application.add_handler(CommandHandler("earn", self._handle_earn))
            self.application.add_handler(CommandHandler("remind", self._handle_remind))
            self.application.add_handler(CommandHandler("note", self._handle_note))
            self.application.add_handler(CommandHandler("home", self._handle_home))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

            # Run the bot
            self.application.run_polling(allowed_updates=Update.ALL_TYPES)

        except Exception as e:
            logger.exception(f"Telegram bridge error: {e}")

    def _is_allowed_user(self, user_id: int) -> bool:
        """Check if user is allowed"""
        return str(user_id) == self.allowed_user_id

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        if not self._is_allowed_user(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        try:
            if not HTTPX_AVAILABLE:
                await update.message.reply_text("❌ httpx not available")
                return

            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_base}/api/status", timeout=5.0)
                data = response.json()

                status_text = f"🤖 **SentinelAI Status**\n\n"
                status_text += f"Backend: {data.get('status', 'unknown')}\n"

                await update.message.reply_text(status_text, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def _handle_cameras(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cameras command"""
        if not self._is_allowed_user(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        try:
            if not HTTPX_AVAILABLE:
                await update.message.reply_text("❌ httpx not available")
                return

            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.api_base}/home/camera/look_all", timeout=30.0)
                data = response.json()

                if data.get('status') == 'ok':
                    result = data.get('data', {})
                    cameras = result.get('cameras', {})

                    if not cameras:
                        await update.message.reply_text("📷 No cameras available")
                        return

                    msg = "📷 **Camera Snapshots**\n\n"
                    for cam_name, description in cameras.items():
                        msg += f"**{cam_name}:**\n{description}\n\n"

                    await update.message.reply_text(msg, parse_mode='Markdown')
                else:
                    await update.message.reply_text(f"❌ {data.get('error', 'Unknown error')}")

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def _handle_earn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /earn command"""
        if not self._is_allowed_user(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        try:
            if not HTTPX_AVAILABLE:
                await update.message.reply_text("❌ httpx not available")
                return

            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_base}/earn/jobs?limit=5", timeout=10.0)
                data = response.json()

                if data.get('status') == 'ok':
                    jobs = data.get('data', [])

                    if not jobs:
                        await update.message.reply_text("💰 No new jobs found")
                        return

                    msg = "💰 **Latest Earn Opportunities**\n\n"
                    for job in jobs[:5]:
                        msg += f"**{job.get('title', 'Untitled')}**\n"
                        msg += f"Source: {job.get('source', 'unknown')}\n"
                        msg += f"Reward: {job.get('reward_range', 'N/A')}\n\n"

                    await update.message.reply_text(msg, parse_mode='Markdown')
                else:
                    await update.message.reply_text(f"❌ {data.get('error', 'Unknown error')}")

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def _handle_remind(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remind command"""
        if not self._is_allowed_user(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        # Parse: /remind 30m Take out trash
        # For simplicity, just create a note for now
        text = ' '.join(context.args) if context.args else ''

        if not text:
            await update.message.reply_text("Usage: /remind <time> <message>")
            return

        await update.message.reply_text(f"⏰ Reminder noted: {text}\n(Full reminder system coming soon)")

    async def _handle_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /note command"""
        if not self._is_allowed_user(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        text = ' '.join(context.args) if context.args else ''

        if not text:
            await update.message.reply_text("Usage: /note <text>")
            return

        try:
            if not HTTPX_AVAILABLE:
                await update.message.reply_text("❌ httpx not available")
                return

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base}/openclaw/notes/create",
                    json={"title": f"Telegram Note", "content": text},
                    timeout=5.0
                )
                data = response.json()

                if data.get('status') == 'ok':
                    await update.message.reply_text("📝 Note saved!")
                else:
                    await update.message.reply_text(f"❌ {data.get('message', 'Failed')}")

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def _handle_home(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /home command"""
        if not self._is_allowed_user(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        command = ' '.join(context.args) if context.args else ''

        if not command:
            await update.message.reply_text("Usage: /home <command>")
            return

        try:
            if not HTTPX_AVAILABLE:
                await update.message.reply_text("❌ httpx not available")
                return

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base}/home/command",
                    json={"command": command},
                    timeout=10.0
                )
                data = response.json()

                if data.get('status') == 'ok':
                    await update.message.reply_text(f"✅ {data.get('message', 'Done')}")
                else:
                    await update.message.reply_text(f"❌ {data.get('message', 'Failed')}")

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular text messages"""
        if not self._is_allowed_user(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        text = update.message.text

        try:
            if not HTTPX_AVAILABLE:
                await update.message.reply_text("❌ httpx not available")
                return

            # Send to chat API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base}/api/chat",
                    json={"message": text, "source": "telegram"},
                    timeout=30.0
                )
                data = response.json()

                reply = data.get('response', 'No response')
                await update.message.reply_text(reply)

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")


# Global instance
_telegram_bridge: Optional[TelegramBridge] = None


def start_bridge():
    """Start the global Telegram bridge"""
    global _telegram_bridge
    if _telegram_bridge is None:
        _telegram_bridge = TelegramBridge()
    _telegram_bridge.start()


def stop_bridge():
    """Stop the global Telegram bridge"""
    global _telegram_bridge
    if _telegram_bridge:
        _telegram_bridge.stop()


def get_bridge() -> Optional[TelegramBridge]:
    """Get the global Telegram bridge instance"""
    return _telegram_bridge
