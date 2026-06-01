"""Sentinel Scalp — crypto scalping subsystem.

v1: XGBoost signals, NautilusTrader/Binance WS feed, Freqtrade paper trading.
v2 slots: TFT, LSTM, FinRL+PPO, hftbacktest full suite, live trading.

INVARIANT: SCALP_LIVE_TRADING must NEVER be set to true automatically.
           Live trading requires explicit .env opt-in AND Paul's confirmation.
"""
