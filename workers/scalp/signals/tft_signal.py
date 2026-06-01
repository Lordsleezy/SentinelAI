"""v2 SKELETON — Temporal Fusion Transformer signal model.

Requires: pytorch-forecasting, pytorch-lightning
Requires: minimum 90 days of training data
Status: SKELETON — not active in v1
"""
from __future__ import annotations


class TFTSignal:
    """v2 Temporal Fusion Transformer. NOT active in v1."""

    def predict(self, bars):
        raise NotImplementedError("TFT not implemented — v2")

    def train(self, data):
        raise NotImplementedError("TFT not implemented — v2")
