"""Signal engine — routes to the active signal model.

ACTIVE_MODEL controls which model is used. Change to "tft"|"lstm"|"finrl" in v2.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workers.scalp.signals.xgboost_signal import Signal

logger = logging.getLogger(__name__)

ACTIVE_MODEL = "xgboost"   # v1 default — change to "tft"|"lstm"|"finrl" in v2

_xgb = None


def _get_xgboost():
    global _xgb
    if _xgb is None:
        from workers.scalp.signals.xgboost_signal import XGBoostSignal
        _xgb = XGBoostSignal()
    return _xgb


def get_signal(bars) -> "Signal":
    """Route to the active signal model."""
    if ACTIVE_MODEL == "xgboost":
        return _get_xgboost().predict(bars)
    elif ACTIVE_MODEL == "tft":
        from workers.scalp.signals.tft_signal import TFTSignal
        return TFTSignal().predict(bars)
    elif ACTIVE_MODEL == "lstm":
        from workers.scalp.signals.lstm_signal import LSTMSignal
        return LSTMSignal().predict(bars)
    elif ACTIVE_MODEL == "finrl":
        from workers.scalp.signals.finrl_signal import FinRLSignal
        return FinRLSignal().predict(bars)
    else:
        logger.error("[SignalEngine] Unknown model: %s — falling back to XGBoost", ACTIVE_MODEL)
        return _get_xgboost().predict(bars)


def get_active_model() -> str:
    return ACTIVE_MODEL


def set_active_model(name: str) -> bool:
    """Switch active model. v2 models raise NotImplementedError on predict."""
    global ACTIVE_MODEL
    allowed = {"xgboost", "tft", "lstm", "finrl"}
    if name not in allowed:
        return False
    ACTIVE_MODEL = name
    logger.info("[SignalEngine] Active model switched to: %s", name)
    return True
