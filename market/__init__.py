"""Sentinel Market — financial data + paper trading workers (Pro tier).

This package is **dry_run only** by default. The OpenBB and Freqtrade adapters
never place a live trade unless ``SENTINEL_MARKET_LIVE=true`` is set in the
environment AND the operator approves each order through the orchestration UI.
"""
