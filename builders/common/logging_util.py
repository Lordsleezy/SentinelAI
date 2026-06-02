"""Unified [BUILDER] logging to Socket.IO and Python logger."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("sentinel.builders")


def log_builder(message: str, level: str = "info", socketio: Any = None,
                log_type: str = "builder") -> None:
    if not message.startswith("[BUILDER]"):
        message = f"[BUILDER] {message}"
    logger.log(
        logging.ERROR if level == "error" else logging.WARNING if level == "warning" else logging.INFO,
        message,
    )
    if socketio:
        try:
            socketio.emit("log_event", {
                "type": log_type,
                "level": level,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception:
            pass
