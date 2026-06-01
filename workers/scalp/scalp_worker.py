"""Sentinel Scalp — main worker with Flask route registration.

Import this module in desktop_app.py to activate all /scalp/* routes.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Feed + signal state
_feed_running = False
_signal_log: List[Dict] = []
_last_signals: Dict[str, Dict] = {}


def _get_feed():
    from workers.scalp.data.feed import get_feed
    return get_feed()


def _get_risk():
    from workers.scalp.risk.risk_manager import get_risk_manager
    return get_risk_manager()


def _get_executor():
    from workers.scalp.execution.executor import get_executor
    return get_executor()


def _get_signal_engine():
    from workers.scalp.signals.signal_engine import get_signal, get_active_model
    return get_signal, get_active_model


def _run_signal_loop():
    """Background loop: poll bars → signal → risk → paper execute."""
    from workers.scalp.data.feed import SYMBOLS, TIMEFRAMES
    from workers.scalp.signals.signal_engine import get_signal
    from workers.scalp.risk.risk_manager import get_risk_manager, Portfolio
    from workers.scalp.execution.executor import get_executor
    import time

    global _feed_running
    feed = _get_feed()

    while _feed_running:
        for sym in SYMBOLS:
            try:
                bars = feed.get_bars(sym, "1m", 50)
                if len(bars) < 20:
                    continue

                signal = get_signal(bars)
                entry = {
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "symbol": sym,
                    "action": signal.action,
                    "confidence": round(signal.confidence, 2),
                }

                _last_signals[sym] = entry
                if signal.action != "HOLD":
                    _signal_log.insert(0, entry)
                    _signal_log[:] = _signal_log[:100]  # keep last 100

                    # Risk check + execute paper trade
                    if signal.action in ("BUY", "SELL"):
                        risk = get_risk_manager()
                        port = Portfolio(
                            balance=10000.0,
                            open_positions=len(get_executor().get_open_positions()),
                            daily_pnl=risk.get_daily_pnl(),
                        )
                        decision = risk.approve_trade(signal, port)
                        decision.symbol = sym
                        decision.action = signal.action
                        if decision.approved:
                            get_executor().execute(decision)

            except Exception as exc:
                logger.debug("[ScalpWorker] Signal loop error for %s: %s", sym, exc)

        time.sleep(30)  # poll every 30 seconds in paper mode


def register_routes(app):
    """Register /scalp/* routes on the Flask app."""
    from flask import jsonify, request

    @app.route('/scalp/status', methods=['GET'])
    def scalp_status():
        feed = _get_feed()
        engine_fn, active_model_fn = _get_signal_engine()
        risk = _get_risk()
        positions = _get_executor().get_open_positions()
        return jsonify({
            "running": _feed_running,
            "feed_connected": feed.is_connected,
            "active_model": active_model_fn(),
            "open_positions": len(positions),
            "daily_pnl": risk.get_daily_pnl(),
            "max_daily_loss_pct": risk.DAILY_LOSS_LIMIT_PCT,
            "max_positions": risk.MAX_OPEN_POSITIONS,
            "live_trading_enabled": False,  # INVARIANT: always False in v1
        })

    @app.route('/scalp/signal', methods=['GET'])
    def scalp_signal():
        """Return latest signal for all subscribed symbols."""
        if not _last_signals:
            # Generate on-demand from current bars
            feed = _get_feed()
            from workers.scalp.data.feed import SYMBOLS
            from workers.scalp.signals.signal_engine import get_signal
            result = {}
            for sym in SYMBOLS:
                bars = feed.get_bars(sym, "1m", 50)
                if bars:
                    sig = get_signal(bars)
                    result[sym] = {
                        "action": sig.action,
                        "confidence": round(sig.confidence, 2),
                        "timestamp": datetime.now().isoformat(),
                    }
                else:
                    result[sym] = {"action": "HOLD", "confidence": 0.5, "no_data": True}
            return jsonify({"signals": result, "model": "xgboost"})
        return jsonify({"signals": _last_signals, "model": "xgboost"})

    @app.route('/scalp/start', methods=['POST'])
    def scalp_start():
        global _feed_running
        data = request.get_json() or {}

        # INVARIANT: reject any live trading requests
        if data.get("live_trading"):
            return jsonify({
                "status": "error",
                "error": (
                    "Live trading is not enabled in v1. "
                    "Set SCALP_LIVE_TRADING=true in .env to unlock in v2. "
                    "This requires an explicit second confirmation prompt."
                ),
                "live_trading_blocked": True,
            }), 403

        # Check for Binance credentials via lazy init
        from workers.lazy_init import get_lazy_init
        cred_check = get_lazy_init().check("scalp")
        if cred_check:
            return jsonify(cred_check), 200  # returns not_configured card

        if _feed_running:
            return jsonify({"status": "already_running"})

        _feed_running = True
        feed = _get_feed()
        feed.start()
        threading.Thread(target=_run_signal_loop, daemon=True, name="ScalpSignalLoop").start()
        return jsonify({"status": "started", "paper_mode": True})

    @app.route('/scalp/stop', methods=['POST'])
    def scalp_stop():
        global _feed_running
        _feed_running = False
        _get_feed().stop()
        return jsonify({"status": "stopped"})

    @app.route('/scalp/positions', methods=['GET'])
    def scalp_positions():
        positions = _get_executor().get_open_positions()
        return jsonify({"positions": positions, "count": len(positions)})

    @app.route('/scalp/performance', methods=['GET'])
    def scalp_performance():
        perf = _get_executor().get_performance()
        risk = _get_risk()
        return jsonify({**perf, "daily_pnl": risk.get_daily_pnl()})

    @app.route('/scalp/backtest', methods=['POST'])
    def scalp_backtest():
        data = request.get_json() or {}
        symbol = data.get("symbol", "BTC/USDT")
        start = data.get("start", "2024-01-01")
        end = data.get("end", datetime.now().strftime("%Y-%m-%d"))
        try:
            from workers.scalp.backtest.backtester import get_backtester, set_last_result
            bt = get_backtester()
            result = bt.run("xgboost_v1", symbol, start, end)
            set_last_result(result)
            return jsonify({
                "strategy": result.strategy,
                "symbol": result.symbol,
                "total_return": result.total_return,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "total_trades": result.total_trades,
            })
        except Exception as exc:
            logger.exception("Backtest error")
            return jsonify({"status": "error", "error": str(exc)}), 500

    @app.route('/scalp/backtest/results', methods=['GET'])
    def scalp_backtest_results():
        from workers.scalp.backtest.backtester import get_last_result
        r = get_last_result()
        if not r:
            return jsonify({"status": "no_results"})
        return jsonify({
            "strategy": r.strategy, "symbol": r.symbol,
            "total_return": r.total_return, "sharpe_ratio": r.sharpe_ratio,
            "max_drawdown": r.max_drawdown, "win_rate": r.win_rate,
            "total_trades": r.total_trades, "log": r.log[-20:],
        })

    @app.route('/scalp/models', methods=['GET'])
    def scalp_models():
        from workers.scalp.signals.signal_engine import get_active_model
        return jsonify({
            "active": get_active_model(),
            "available": [
                {"name": "xgboost", "status": "active", "version": "v1"},
                {"name": "tft", "status": "skeleton", "version": "v2"},
                {"name": "lstm", "status": "skeleton", "version": "v2"},
                {"name": "finrl", "status": "skeleton", "version": "v2"},
            ],
        })

    @app.route('/scalp/models/switch', methods=['POST'])
    def scalp_models_switch():
        from workers.scalp.signals.signal_engine import set_active_model, get_active_model
        data = request.get_json() or {}
        name = data.get("model", "")
        if name != "xgboost":
            return jsonify({
                "status": "error",
                "error": f"Model '{name}' is a v2 skeleton — not available in v1.",
            }), 400
        ok = set_active_model(name)
        return jsonify({"status": "ok" if ok else "error", "active": get_active_model()})

    logger.info("[ScalpWorker] Routes registered")
