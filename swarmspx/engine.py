import asyncio
import logging
import time
import yaml
from typing import Optional
from swarmspx.ingest.market_data import MarketDataFetcher
from swarmspx.agents.forge import AgentForge
from swarmspx.simulation.pit import TradingPit
from swarmspx.report.generator import ReportGenerator
from swarmspx.providers import resolve_synthesis_model
from swarmspx.memory import AOMemory
from swarmspx.db import Database
from swarmspx.scoring import AgentScorer
from swarmspx.events import (
    EventBus, NoOpBus,
    CycleStarted, MarketDataFetched, ConsensusReached,
    TradeCardGenerated, CycleCompleted, EngineError,
    OutcomeResolved,
)
from swarmspx.tracking.outcome_tracker import OutcomeTracker
from swarmspx.strategy.selector import select_strategy
from swarmspx.risk.gate import PreTradeRiskGate
from swarmspx.risk.killswitch import KillSwitch
from swarmspx.risk.sizer import KellyPositionSizer
from swarmspx.dealer.gex import compute_gex

logger = logging.getLogger(__name__)

class SwarmSPXEngine:
    """Main orchestrator for the full simulation pipeline."""

    def __init__(self, settings_path: str = "config/settings.yaml", bus: Optional[EventBus] = None):
        with open(settings_path) as f:
            self.settings = yaml.safe_load(f)

        self.bus = bus or NoOpBus()
        self.cycle_count = 0

        self.fetcher = MarketDataFetcher()
        self.forge = AgentForge()
        self.agents = self.forge.create_all()
        self.memory = AOMemory(self.settings["aoms"]["base_url"])
        self.pit = TradingPit(
            agents=self.agents,
            memory=self.memory,
            num_rounds=self.settings["simulation"]["num_rounds"],
            bus=self.bus,
        )
        synth_cfg = resolve_synthesis_model(self.settings)
        self.reporter = ReportGenerator(
            ollama_base_url=synth_cfg["base_url"],
            model=synth_cfg["model"],
            api_key=synth_cfg["api_key"],
            use_claude_cli=synth_cfg["use_claude_cli"],
            claude_model=synth_cfg["claude_model"],
        )
        self.db = Database(self.settings["database"]["path"])
        self.db.init_schema()
        self.scorer = AgentScorer(self.db)
        self.tracker = OutcomeTracker(self.db, self.fetcher, self.memory, self.bus, self.scorer)

        # ── Tier 1 risk infrastructure ───────────────────────────────────
        # Override defaults via the optional `risk:` block in settings.yaml.
        risk_cfg = self.settings.get("risk", {}) or {}
        self.killswitch = KillSwitch(
            state_path=risk_cfg.get(
                "killswitch_state_path",
                "data/killswitch_state.json",
            ),
            daily_loss_pct=risk_cfg.get("daily_loss_pct", 3.0),
            weekly_loss_pct=risk_cfg.get("weekly_loss_pct", 6.0),
            monthly_loss_pct=risk_cfg.get("monthly_loss_pct", 10.0),
            max_consecutive_losses=risk_cfg.get("max_consecutive_losses", 3),
        )
        self.risk_gate = PreTradeRiskGate(
            db=self.db,
            bankroll=risk_cfg.get("bankroll_usd", 25_000.0),
            daily_loss_pct=risk_cfg.get("daily_loss_pct", 3.0),
            weekly_loss_pct=risk_cfg.get("weekly_loss_pct", 6.0),
            monthly_loss_pct=risk_cfg.get("monthly_loss_pct", 10.0),
            max_open_positions=risk_cfg.get("max_open_positions", 5),
            max_consecutive_losses=risk_cfg.get("max_consecutive_losses", 3),
            data_staleness_sec=risk_cfg.get("data_staleness_sec", 30),
        )
        self.sizer = KellyPositionSizer(
            bankroll_usd=risk_cfg.get("bankroll_usd", 25_000.0),
            kelly_fraction=risk_cfg.get("kelly_fraction", 0.10),
            win_prob=risk_cfg.get("win_prob", 0.40),
            payoff_ratio=risk_cfg.get("payoff_ratio", 3.0),
            max_per_trade_pct=risk_cfg.get("max_per_trade_pct", 0.05),
            lock_dir=risk_cfg.get("lock_dir", "data"),
        )

        self._cycle_lock = asyncio.Lock()

    async def run_cycle(self) -> dict:
        """Run one full simulation cycle.

        Always emits CycleCompleted (even on error) so the web trigger guard
        cannot get stuck at status="running". Concurrent cycles are rejected.
        """
        if self._cycle_lock.locked():
            logger.warning("run_cycle invoked while another cycle is in progress; skipping")
            await self.bus.emit(EngineError(message="Concurrent cycle rejected"))
            return {}

        async with self._cycle_lock:
            self.cycle_count += 1
            cycle_id = self.cycle_count
            start = time.time()
            trade_card: dict = {}

            await self.bus.emit(CycleStarted(cycle_id=cycle_id))
            try:
                # 0. Kill switch — short-circuit before any market work
                if self.killswitch.is_tripped():
                    ks_state = self.killswitch.state
                    msg = (
                        f"Kill switch active: {ks_state.get('triggered_by')} — "
                        f"{ks_state.get('triggered_reason')}"
                    )
                    logger.warning(msg)
                    await self.bus.emit(EngineError(message=msg))
                    return {}

                # 1. Fetch market data
                market_context = self.fetcher.get_snapshot()
                if not market_context.get("spx_price"):
                    await self.bus.emit(EngineError(message="Market data unavailable"))
                    return {}

                # 1b. Enrich with live options chain (if configured)
                await self.fetcher.enrich_with_options(market_context)

                # 1c. Compute dealer GEX (replaces SpotGamma) and inject into
                # market_context so agents see dealer positioning.
                opt_snap = self.fetcher._options_snapshot
                if opt_snap and opt_snap.contracts:
                    try:
                        gex_snapshot = compute_gex(
                            opt_snap.contracts,
                            market_context.get("spx_price", 0.0),
                        )
                        if gex_snapshot:
                            # Only store JSON-safe primitives in market_context.
                            # The full GEXSnapshot dataclass is intentionally
                            # NOT placed here because db.store_snapshot
                            # serializes the whole dict and would crash.
                            market_context["gex_block"] = gex_snapshot.to_prompt_block()
                            market_context["gex_regime"] = gex_snapshot.regime
                            market_context["gamma_flip"] = gex_snapshot.gamma_flip_strike
                            market_context["call_wall"] = gex_snapshot.call_wall
                            market_context["put_wall"] = gex_snapshot.put_wall
                            market_context["net_gex"] = gex_snapshot.net_gex
                    except Exception:
                        logger.exception("GEX computation failed; agents proceed without it")

                await self.bus.emit(MarketDataFetched(market_context=market_context))

                # 2. Store snapshot
                self.db.store_snapshot(market_context)

                # 3. Get agent weights for current regime and run simulation
                regime = market_context.get("market_regime", "unknown")
                agent_weights = self.scorer.get_weights(regime)
                consensus = await self.pit.run(market_context, agent_weights=agent_weights)
                await self.bus.emit(ConsensusReached(consensus=consensus))

                # 4. Select strategy based on consensus + regime + options
                strategy = select_strategy(
                    consensus, market_context, self.fetcher._options_snapshot,
                )
                market_context["selected_strategy"] = strategy

                # 4b. Capture option metadata for OutcomeTracker option-P&L path
                strategy_meta = _extract_strategy_meta(strategy)

                # 4c. Kelly sizing — fractional, daily-locked
                sizing = self.sizer.size_for_signal(
                    entry_premium=strategy_meta["entry_premium"],
                    confidence=consensus.get("confidence"),
                )

                # 5. Get AOMS memories for report context (async, non-blocking)
                memories = await self.memory.recall(
                    f"SPX {market_context['market_regime']} {consensus['direction']} trading",
                    limit=5,
                )

                # 6. Generate trade card
                trade_card = await self.reporter.generate(consensus, market_context, memories)

                # 6b. Inject sizing into the trade card so the alert dispatcher
                # and downstream consumers see the recommended size.
                trade_card["sizing"] = {
                    "contracts": sizing.contracts,
                    "risk_usd": sizing.risk_usd,
                    "kelly_used": sizing.kelly_used,
                    "bankroll": sizing.bankroll,
                    "reason": sizing.reason,
                }

                # 7. Pre-trade risk gate — between trade card and dispatch.
                gate_input = {
                    "direction": consensus.get("direction"),
                    "strategy_type": (strategy or {}).get("strategy"),
                    "strike": strategy_meta["option_strike"],
                    "option_type": strategy_meta["option_type"],
                }
                risk_decision = self.risk_gate.check(
                    gate_input,
                    market_context,
                    kill_switch_active=False,  # already handled above
                )
                trade_card["risk_decision"] = {
                    "action": risk_decision.action,
                    "reasons": risk_decision.reasons,
                    "meta": risk_decision.meta,
                }

                signal_outcome = "pending"
                if risk_decision.passed:
                    # Healthy path — emit so AlertDispatcher fires Telegram/Slack.
                    await self.bus.emit(TradeCardGenerated(trade_card=trade_card))
                else:
                    # Rejected — log + persist with 'gated' outcome, NO dispatch.
                    logger.warning(
                        "RISK_GATE_REJECT cycle=%d reasons=%s meta=%s",
                        cycle_id, risk_decision.reasons, risk_decision.meta,
                    )
                    signal_outcome = "gated"

                # 8. Store to AOMS (async, fail-soft) — only for non-gated trades
                memory_id = None
                if signal_outcome == "pending":
                    memory_id = await self.memory.store_result(
                        direction=consensus["direction"],
                        confidence=consensus["confidence"],
                        trade_setup=trade_card,
                        regime=market_context["market_regime"],
                        agent_votes=consensus.get("vote_counts", {}),
                    )

                # 8b. Store to DuckDB (always — gated signals are useful audit data)
                signal_id = self.db.store_simulation_result({
                    "direction": consensus["direction"],
                    "confidence": consensus["confidence"],
                    "agreement_pct": consensus["agreement_pct"],
                    "spx_entry_price": market_context.get("spx_price", 0.0),
                    "entry_premium": strategy_meta["entry_premium"],
                    "option_strike": strategy_meta["option_strike"],
                    "option_type": strategy_meta["option_type"],
                    "memory_id": memory_id,
                    "trade_setup": trade_card,
                    "agent_votes": consensus.get("vote_counts", {}),
                    "outcome": signal_outcome,
                })

                # 8c. Store individual agent votes for Darwinian scoring
                if signal_id and consensus.get("individual_votes"):
                    self.db.store_agent_votes(signal_id, consensus["individual_votes"], regime)
                    logger.info("Stored %d individual agent votes for signal #%d",
                               len(consensus["individual_votes"]), signal_id)

                # 9. Resolve pending signals + auto-evaluate kill-switch loss bands
                await self.tracker.check_pending_signals()
                self._evaluate_killswitch_loss_bands()

                return trade_card

            except Exception as exc:  # noqa: BLE001 — top-level cycle guard
                logger.exception("run_cycle failed for cycle %d", cycle_id)
                await self.bus.emit(EngineError(
                    message=f"Cycle {cycle_id} failed: {type(exc).__name__}: {exc}"
                ))
                return trade_card

            finally:
                duration = time.time() - start
                await self.bus.emit(CycleCompleted(cycle_id=cycle_id, duration_sec=duration))

    def _evaluate_killswitch_loss_bands(self) -> None:
        """Compute rolling P&L impact and trip the kill switch if breached.

        Heuristic until a position-size ledger lands: each resolved signal's
        outcome_pct is scaled by 0.02 (≈ fractional Kelly size) to estimate
        bankroll impact. Replace with size-weighted sum once the Kelly sizer
        records actual position dollars per trade.
        """
        try:
            signals = self.db.get_recent_signals(limit=200)
        except Exception:
            logger.exception("Failed to read recent signals for killswitch eval")
            return

        from datetime import datetime, timedelta
        from swarmspx.clock import now_et, UTC
        now = now_et()

        def _impact(days: int) -> float:
            cutoff = now - timedelta(days=days)
            total = 0.0
            for s in signals:
                ts_raw = s.get("timestamp")
                if not ts_raw:
                    continue
                try:
                    ts = datetime.fromisoformat(str(ts_raw))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    continue
                if ts < cutoff:
                    continue
                if s.get("outcome") not in ("win", "loss"):
                    continue
                total += float(s.get("outcome_pct", 0) or 0) * 0.02
            return total

        daily = _impact(1)
        weekly = _impact(7)
        monthly = _impact(30)
        self.killswitch.evaluate_loss_bands(daily, weekly, monthly)


def _extract_strategy_meta(strategy: dict) -> dict:
    """Pull option metadata from the selected strategy for honest P&L tracking.

    Returns a dict with three keys:
      entry_premium  — premium paid (or net debit) at signal time, 0.0 if N/A
      option_strike  — strike of the directional leg, 0.0 for spreads/condors
      option_type    — 'call' / 'put' / '' (empty for spreads/condors)

    Defensive: never raises. Returns zeros for WAIT / GUIDANCE / malformed
    strategy dicts so DB persistence is consistent.
    """
    blank = {"entry_premium": 0.0, "option_strike": 0.0, "option_type": ""}
    if not strategy or not isinstance(strategy, dict):
        return blank
    trade = strategy.get("trade")
    if not trade or not isinstance(trade, dict):
        return blank

    # Premium: STRAIGHT/LOTTO carry premium_ask; spreads carry net_debit
    premium = 0.0
    for key in ("premium_ask", "net_debit", "net_credit"):
        v = trade.get(key)
        if v is not None:
            try:
                premium = float(v)
                break
            except (TypeError, ValueError):
                continue

    # Strike + type — only meaningful for single-leg structures
    strike = 0.0
    opt_type = ""
    strat_kind = (strategy.get("strategy") or "").upper()
    if strat_kind in ("STRAIGHT", "LOTTO"):
        try:
            strike = float(trade.get("strike", 0) or 0)
        except (TypeError, ValueError):
            strike = 0.0
        ot = (trade.get("option_type") or trade.get("type") or "").lower()
        if ot in ("call", "put"):
            opt_type = ot

    return {
        "entry_premium": round(premium, 2),
        "option_strike": strike,
        "option_type": opt_type,
    }
