"""Dealer-side intelligence — gamma exposure, dealer positioning, flow.

Modules:
    gex   — Compute dealer Gamma Exposure (GEX) from an SPX option chain.
            Replaces $199/mo SpotGamma with free CBOE OI + Schwab/Tradier
            real-time Greeks.
"""
