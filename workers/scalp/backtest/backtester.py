"""Backtester for Sentinel Scalp.

v1: Single strategy, basic metrics.
v2: Full hftbacktest suite, walk-forward optimization.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    strategy: str
    symbol: str
    start_date: str
    end_date: str
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    log: List[str] = field(default_factory=list)


class Backtester:
    """
    Runs strategy backtests.
    v1: Uses in-memory bar data from the feed.
    v2: Full hftbacktest suite with walk-forward optimization.
    """

    def run(self, strategy: str, symbol: str,
            start_date: str, end_date: str) -> BacktestResult:
        """Run a backtest and return metrics."""
        from workers.scalp.data.feed import get_feed
        from workers.scalp.signals.signal_engine import get_signal

        feed = get_feed()
        bars = feed.get_bars(symbol.replace("/", "").upper(), "1m", 500)

        if not bars:
            logger.warning("[Backtester] No bars available for %s — returning synthetic result", symbol)
            return self._synthetic_result(strategy, symbol, start_date, end_date)

        # Simple backtest loop
        trades = []
        equity = 10000.0
        position = None
        log = []

        for i in range(20, len(bars)):
            window = bars[:i]
            signal = get_signal(window)

            bar = bars[i]
            if signal.action == "BUY" and position is None and signal.confidence >= 0.65:
                position = {"entry": bar.close, "size": equity * 0.02}
                log.append(f"BUY @ {bar.close:.2f}")
            elif signal.action == "SELL" and position is not None:
                pnl = (bar.close - position["entry"]) / position["entry"] * position["size"]
                equity += pnl
                trades.append(pnl)
                log.append(f"SELL @ {bar.close:.2f} pnl={pnl:.2f}")
                position = None

        return self.get_metrics(BacktestResult(
            strategy=strategy,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            total_return=0,
            sharpe_ratio=0,
            max_drawdown=0,
            win_rate=0,
            total_trades=len(trades),
            log=log,
        ), trades, equity)

    def get_metrics(self, result: BacktestResult,
                    trades: Optional[List[float]] = None,
                    final_equity: float = 10000.0) -> BacktestResult:
        if trades is None:
            trades = []
        if not trades:
            return result

        wins = sum(1 for t in trades if t > 0)
        total_return = (final_equity - 10000.0) / 10000.0

        # Simplified Sharpe
        import statistics
        if len(trades) > 1:
            mean_r = statistics.mean(trades)
            std_r = statistics.stdev(trades)
            sharpe = mean_r / (std_r + 1e-9) * (252 ** 0.5)
        else:
            sharpe = 0.0

        # Max drawdown
        equity_curve = [10000.0]
        for t in trades:
            equity_curve.append(equity_curve[-1] + t)
        peak = equity_curve[0]
        max_dd = 0.0
        for e in equity_curve:
            if e > peak:
                peak = e
            dd = (peak - e) / peak
            if dd > max_dd:
                max_dd = dd

        result.total_return = round(total_return, 4)
        result.sharpe_ratio = round(sharpe, 3)
        result.max_drawdown = round(max_dd, 4)
        result.win_rate = round(wins / len(trades), 3) if trades else 0
        result.total_trades = len(trades)
        return result

    def _synthetic_result(self, strategy, symbol, start_date, end_date) -> BacktestResult:
        """Return a placeholder result when no data is available."""
        return BacktestResult(
            strategy=strategy, symbol=symbol,
            start_date=start_date, end_date=end_date,
            total_return=0.0, sharpe_ratio=0.0,
            max_drawdown=0.0, win_rate=0.0,
            total_trades=0,
            log=["No bar data available — start the feed first"],
        )


# Singleton
_backtester: Optional[Backtester] = None
_last_result: Optional[BacktestResult] = None


def get_backtester() -> Backtester:
    global _backtester
    if _backtester is None:
        _backtester = Backtester()
    return _backtester


def set_last_result(r: BacktestResult) -> None:
    global _last_result
    _last_result = r


def get_last_result() -> Optional[BacktestResult]:
    return _last_result
