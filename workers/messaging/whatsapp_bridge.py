"""
WhatsApp Bridge — Control SentinelAI via WhatsApp
NOTE: WhatsApp bridges are unstable due to frequent API changes.
This is a stub implementation - Telegram is recommended as the primary bridge.
"""
import os
import logging

logger = logging.getLogger(__name__)

# WhatsApp libraries are frequently broken due to API changes
# This is a placeholder for future implementation
WHATSAPP_AVAILABLE = False


class WhatsAppBridge:
    """WhatsApp bridge stub - use Telegram instead"""

    def __init__(self):
        self.allowed_number = os.getenv('WHATSAPP_ALLOWED_NUMBER')

    def start(self):
        """Start WhatsApp bridge (stub)"""
        if not self.allowed_number:
            logger.info("WHATSAPP_ALLOWED_NUMBER not set - WhatsApp bridge disabled")
            return

        logger.warning("WhatsApp bridge is experimental and currently disabled")
        logger.info("Use Telegram bridge instead for reliable messaging")

    def stop(self):
        """Stop WhatsApp bridge"""
        pass


# Global instance
_whatsapp_bridge = None


def start_bridge():
    """Start the global WhatsApp bridge"""
    global _whatsapp_bridge
    if _whatsapp_bridge is None:
        _whatsapp_bridge = WhatsAppBridge()
    _whatsapp_bridge.start()


def stop_bridge():
    """Stop the global WhatsApp bridge"""
    global _whatsapp_bridge
    if _whatsapp_bridge:
        _whatsapp_bridge.stop()
