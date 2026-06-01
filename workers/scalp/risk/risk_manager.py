"""Risk manager for Sentinel Scalp.

Hard limits enforced before every trade decision.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Portfolio:
    balance: float          # total paper balance in USD
    open_positions: int     # current open position count
    daily_pnl: float        # today's realized P&L


@dataclass
class TradeDecision:
    approved: bool
    size: float             # USD size of the trade
    reason: str
    stop_loss_price: Optional[float] = None


@dataclass
class Position:
    symbol: str
    entry_price: float
    size: float             # USD
    stop_loss: float


class RiskManager:
    MAX_POSITION_PCT = 0.02       # 2% of portfolio per trade
    STOP_LOSS_PCT = 0.01          # 1% stop loss
    DAILY_LOSS_LIMIT_PCT = 0.03   # 3% max daily loss
    MAX_OPEN_POSITIONS = 3        # hard cap

    def __init__(self):
        self._daily_pnl: float = 0.0
        self._pnl_date: date = date.today()
        self._positions: Dict[str, Position] = {}

    def _reset_daily_if_needed(self) -> None:
        today = date.today()
        if today != self._pnl_date:
            self._daily_pnl = 0.0
            self._pnl_date = today

    def record_pnl(self, amount: float) -> None:
        self._reset_daily_if_needed()
        self._daily_pnl += amount

    def get_daily_pnl(self) -> float:
        self._reset_daily_if_needed()
        return self._daily_pnl

    def approve_trade(self, signal, portfolio: Portfolio) -> TradeDecision:
        from workers.scalp.signals.xgboost_signal import Signal
        self._reset_daily_if_needed()

        # Daily loss limit
        if portfolio.balance > 0:
            daily_loss_pct = -self._daily_pnl / portfolio.balance
            if daily_loss_pct >= self.DAILY_LOSS_LIMIT_PCT:
                return TradeDecision(
                    approved=False, size=0,
                    reason=f"Daily loss limit reached: {daily_loss_pct:.1%} (max {self.DAILY_LOSS_LIMIT_PCT:.0%})"
                )

        # Max open positions
        if portfolio.open_positions >= self.MAX_OPEN_POSITIONS:
            return TradeDecision(
                approved=False, size=0,
                reason=f"Max open positions reached ({self.MAX_OPEN_POSITIONS})"
            )

        # Confidence threshold
        if signal.confidence < 0.65:
            return TradeDecision(
                approved=False, size=0,
                reason=f"Signal confidence too low: {signal.confidence:.2f}"
            )

        # Position size
        size = self.calculate_position_size(signal, portfolio)
        if size <= 0:
            return TradeDecision(
                approved=False, size=0,
                reason="Position size calculation returned 0"
            )

        # Stop loss price
        if hasattr(signal, "features") and signal.features:
            entry = signal.features.get("close", 0)
        else:
            entry = 0
        stop_loss = entry * (1 - self.STOP_LOSS_PCT) if entry > 0 else None

        return TradeDecision(
            approved=True,
            size=size,
            reason=f"Approved: {signal.action} conf={signal.confidence:.2f} size=${size:.2f}",
            stop_loss_price=stop_loss,
        )

    def calculate_position_size(self, signal, portfolio: Portfolio) -> float:
        """v1: fixed MAX_POSITION_PCT. v2: Kelly criterion."""
        return round(portfolio.balance * self.MAX_POSITION_PCT, 2)

    def check_stop_loss(self, position: Position, current_price: float) -> bool:
        """Returns True if stop loss is triggered."""
        return current_price <= position.stop_loss

    def add_position(self, position: Position) -> None:
        self._positions[position.symbol] = position

    def remove_position(self, symbol: str) -> Optional[Position]:
        return self._positions.pop(symbol, None)

    def open_positions(self) -> List[Position]:
        return list(self._positions.values())


# Singleton
_risk_manager: Optional[RiskManager] = None


def get_risk_manager() -> RiskManager:
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager
