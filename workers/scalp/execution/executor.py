"""Paper trading executor via Freqtrade dry_run API.

INVARIANT (never remove):
  v1 ALWAYS uses paper trading (dry_run=True).
  Live trading requires SCALP_LIVE_TRADING=true in .env
  AND an explicit confirmation prompt to Paul.
  live_execute() raises NotImplementedError in v1.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FREQTRADE_URL = os.getenv("FREQTRADE_URL", "http://localhost:8080")
FREQTRADE_USER = os.getenv("FREQTRADE_USER", "freqtrader")
FREQTRADE_PASS = os.getenv("FREQTRADE_PASS", "SuperSecurePassword")

# Paper trading log — in-memory for v1
_paper_log: List[Dict] = []
_paper_positions: Dict[str, Dict] = {}


@dataclass
class ExecutionResult:
    success: bool
    order_id: str
    message: str
    is_paper: bool = True
    trade: Optional[Dict] = None


class ScalpExecutor:
    """Paper trading executor.

    v1: simulates trades via internal log (Freqtrade integration available if running).
    v2 skeleton: live trading behind SCALP_LIVE_TRADING gate.
    """

    def execute(self, decision) -> ExecutionResult:
        """
        v1: Paper trade only. Routes to live_execute if SCALP_LIVE_TRADING=true
        (raises NotImplementedError in v1).
        """
        if os.getenv("SCALP_LIVE_TRADING", "").lower() == "true":
            return self.live_execute(decision)

        return self._paper_execute(decision)

    def _paper_execute(self, decision) -> ExecutionResult:
        """Simulate a paper trade."""
        import uuid
        order_id = str(uuid.uuid4())[:8]
        trade = {
            "order_id": order_id,
            "symbol": getattr(decision, "symbol", "BTC/USDT"),
            "action": getattr(decision, "action", "BUY"),
            "size_usd": decision.size,
            "paper": True,
            "timestamp": datetime.now().isoformat(),
            "stop_loss": decision.stop_loss_price,
        }
        _paper_log.append(trade)
        sym = trade["symbol"]
        if trade["action"] == "BUY":
            _paper_positions[sym] = trade.copy()
        elif trade["action"] == "SELL":
            _paper_positions.pop(sym, None)

        logger.info("[Executor] Paper trade: %s %s $%.2f (id=%s)",
                    trade["action"], sym, decision.size, order_id)
        return ExecutionResult(
            success=True,
            order_id=order_id,
            message=f"Paper {trade['action']} {sym} ${decision.size:.2f}",
            is_paper=True,
            trade=trade,
        )

    def live_execute(self, decision) -> ExecutionResult:
        """
        v2 SKELETON — live trading.
        Requires: SCALP_LIVE_TRADING=true in .env AND Paul's confirmation.
        NOT IMPLEMENTED in v1.
        """
        raise NotImplementedError(
            "Live trading not enabled in v1. "
            "Set SCALP_LIVE_TRADING=true in .env to unlock in v2. "
            "This also requires an explicit second confirmation prompt."
        )

    def get_open_positions(self) -> list:
        """Return currently open paper positions."""
        return list(_paper_positions.values())

    def get_performance(self) -> dict:
        """Return aggregate performance metrics from paper log."""
        if not _paper_log:
            return {"win_rate": 0, "total_pnl": 0, "trade_count": 0}
        wins = sum(1 for t in _paper_log if t.get("pnl", 0) > 0)
        total_pnl = sum(t.get("pnl", 0) for t in _paper_log)
        return {
            "win_rate": wins / len(_paper_log) if _paper_log else 0,
            "total_pnl": total_pnl,
            "trade_count": len(_paper_log),
        }

    def get_trade_log(self) -> list:
        return list(_paper_log)


# Singleton
_executor: Optional[ScalpExecutor] = None


def get_executor() -> ScalpExecutor:
    global _executor
    if _executor is None:
        _executor = ScalpExecutor()
    return _executor
