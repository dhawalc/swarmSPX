"""Concrete strategy modules with documented edge.

Each strategy exposes a signal generator for live trading and is
compatible with swarmspx.backtest.runner for historical validation.
"""
from swarmspx.strategies.friday_pin import FridayPinSignal, generate_live_signal as friday_pin_signal

__all__ = ["FridayPinSignal", "friday_pin_signal"]
