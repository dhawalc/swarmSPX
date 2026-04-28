"""Paper broker — shadow trading simulator.

The bridge between research and live trading. Opens "paper" positions when
the engine produces a non-gated trade card, tracks them via the same
option-chain lookup the real OutcomeTracker uses, and closes them on
target / stop / time-based exits.

Why this exists:
    Until walk-forward Sharpe > 1.0 across ≥60% of test windows (war room
    decision gate at month 2), the system MUST NOT trade real money. Paper
    trading lets the system run the full pipeline — agents debate, GEX
    fires, risk gate fires, sizer sizes — and accumulate honest P&L
    statistics. After 30 days of clean paper data we have an honest
    answer to "does this make money?"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from swarmspx.clock import now_et

logger = logging.getLogger(__name__)


# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_TARGET_MULTIPLIER = 2.0     # exit at 2× entry premium
DEFAULT_STOP_MULTIPLIER = 0.5       # exit at 0.5× entry premium (-50%)


@dataclass
class PaperPosition:
    """In-memory representation of a paper position."""
    id: int
    signal_id: int
    direction: str
    option_strike: float
    option_type: str
    entry_premium: float
    exit_premium: float
    contracts: int
    target_premium: float
    stop_premium: float
    opened_at: str
    closed_at: Optional[str]
    status: str
    close_reason: str

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def pnl_per_contract(self) -> float:
        if self.exit_premium <= 0:
            return 0.0
        return self.exit_premium - self.entry_premium

    @property
    def pnl_usd(self) -> float:
        return self.pnl_per_contract * self.contracts * 100.0  # SPX multiplier

    @property
    def pnl_pct(self) -> float:
        if self.entry_premium <= 0:
            return 0.0
        return ((self.exit_premium - self.entry_premium) / self.entry_premium) * 100.0


class PaperBroker:
    """Persistent shadow-trading simulator backed by the engine's DuckDB."""

    def __init__(
        self,
        db,
        target_multiplier: float = DEFAULT_TARGET_MULTIPLIER,
        stop_multiplier: float = DEFAULT_STOP_MULTIPLIER,
    ):
        self.db = db
        self.target_multiplier = float(target_multiplier)
        self.stop_multiplier = float(stop_multiplier)
        self._ensure_schema()

    # ── Schema bootstrap ─────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        conn = self.db._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_positions (
                    id INTEGER PRIMARY KEY,
                    signal_id INTEGER,
                    direction VARCHAR,
                    option_strike DOUBLE,
                    option_type VARCHAR,
                    entry_premium DOUBLE,
                    exit_premium DOUBLE DEFAULT 0.0,
                    contracts INTEGER,
                    target_premium DOUBLE,
                    stop_premium DOUBLE,
                    opened_at TIMESTAMP,
                    closed_at TIMESTAMP,
                    status VARCHAR DEFAULT 'open',
                    close_reason VARCHAR DEFAULT ''
                )
            """)
            conn.execute("CREATE SEQUENCE IF NOT EXISTS paper_positions_id_seq")
        except Exception:
            logger.exception("Failed to create paper_positions table")
        finally:
            self.db._close(conn)

    # ── Public API ───────────────────────────────────────────────────────

    def open_position(
        self,
        *,
        signal_id: int,
        direction: str,
        option_strike: float,
        option_type: str,
        entry_premium: float,
        contracts: int,
        target_premium: Optional[float] = None,
        stop_premium: Optional[float] = None,
    ) -> Optional[int]:
        """Open a paper position. Returns the position id or None on failure."""
        if entry_premium <= 0 or contracts <= 0:
            logger.warning(
                "Refusing to open paper position with bad inputs: "
                "entry=%s contracts=%s", entry_premium, contracts,
            )
            return None
        if option_type not in ("call", "put"):
            logger.warning("Bad option_type=%r; refusing", option_type)
            return None

        target = target_premium if target_premium is not None else (
            entry_premium * self.target_multiplier
        )
        stop = stop_premium if stop_premium is not None else (
            entry_premium * self.stop_multiplier
        )

        conn = self.db._connect()
        try:
            row = conn.execute("""
                INSERT INTO paper_positions
                (id, signal_id, direction, option_strike, option_type,
                 entry_premium, contracts, target_premium, stop_premium,
                 opened_at, status, close_reason)
                VALUES (nextval('paper_positions_id_seq'),
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', '')
                RETURNING id
            """, [
                signal_id,
                direction,
                float(option_strike),
                option_type,
                float(entry_premium),
                int(contracts),
                float(target),
                float(stop),
                now_et().isoformat(),
            ]).fetchone()
            pid = row[0] if row else None
            if pid is not None:
                logger.info(
                    "Paper position #%d opened: %s %.0f%s @ $%.2f x%d "
                    "(target $%.2f, stop $%.2f)",
                    pid, direction, option_strike, option_type[0].upper(),
                    entry_premium, contracts, target, stop,
                )
            return pid
        except Exception:
            logger.exception("Failed to open paper position")
            return None
        finally:
            self.db._close(conn)

    def get_open_positions(self) -> list[PaperPosition]:
        """Return all currently open paper positions."""
        conn = self.db._connect()
        try:
            rows = conn.execute("""
                SELECT id, signal_id, direction, option_strike, option_type,
                       entry_premium, exit_premium, contracts,
                       target_premium, stop_premium,
                       opened_at, closed_at, status, close_reason
                FROM paper_positions
                WHERE status = 'open'
                ORDER BY opened_at ASC
            """).fetchall()
        except Exception:
            logger.exception("Failed to read open paper positions")
            return []
        finally:
            self.db._close(conn)

        positions: list[PaperPosition] = []
        for r in rows:
            positions.append(PaperPosition(
                id=r[0], signal_id=r[1], direction=r[2],
                option_strike=float(r[3]), option_type=r[4],
                entry_premium=float(r[5]), exit_premium=float(r[6] or 0.0),
                contracts=int(r[7]),
                target_premium=float(r[8]), stop_premium=float(r[9]),
                opened_at=str(r[10]),
                closed_at=str(r[11]) if r[11] else None,
                status=r[12], close_reason=r[13] or "",
            ))
        return positions

    def close_position(
        self,
        position_id: int,
        exit_premium: float,
        reason: str,
    ) -> bool:
        """Close a position with the given exit premium + reason.

        status is computed automatically:
          exit_premium >= entry_premium  → 'won'
          0 <  exit_premium < entry_premium → 'lost'
          exit_premium == 0              → 'expired' (worthless on EOD)
        """
        conn = self.db._connect()
        try:
            row = conn.execute("""
                SELECT entry_premium FROM paper_positions WHERE id = ? AND status='open'
            """, [position_id]).fetchone()
            if not row:
                logger.warning("close_position: id=%d not found or already closed", position_id)
                return False
            entry = float(row[0])

            if exit_premium <= 0:
                status = "expired"
            elif exit_premium >= entry:
                status = "won"
            else:
                status = "lost"

            conn.execute("""
                UPDATE paper_positions
                SET exit_premium = ?, closed_at = ?, status = ?, close_reason = ?
                WHERE id = ?
            """, [
                float(exit_premium),
                now_et().isoformat(),
                status,
                str(reason)[:200],
                position_id,
            ])
            logger.info(
                "Paper position #%d closed: %s @ $%.2f (reason: %s)",
                position_id, status.upper(), exit_premium, reason,
            )
            return True
        except Exception:
            logger.exception("Failed to close paper position #%d", position_id)
            return False
        finally:
            self.db._close(conn)

    async def check_exits(self, fetcher) -> list[dict]:
        """Walk open positions and close those that hit target/stop/EOD.

        Args:
            fetcher: MarketDataFetcher with `lookup_option_premium(strike, option_type)`.

        Returns:
            List of close events: {position_id, signal_id, status, exit_premium, reason}.
        """
        events: list[dict] = []
        from swarmspx.clock import is_after_hours

        for pos in self.get_open_positions():
            try:
                current_premium = await fetcher.lookup_option_premium(
                    pos.option_strike, pos.option_type,
                )
            except Exception:
                logger.exception("Lookup failed for paper position #%d", pos.id)
                current_premium = None

            close_reason: Optional[str] = None
            close_at: float = 0.0

            if current_premium is None:
                if is_after_hours():
                    close_reason = "expired_no_chain_eod"
                    close_at = 0.0
                else:
                    continue  # transient — try again next pass
            else:
                if current_premium >= pos.target_premium:
                    close_reason = f"target_hit (>= ${pos.target_premium:.2f})"
                    close_at = current_premium
                elif current_premium <= pos.stop_premium:
                    close_reason = f"stop_hit (<= ${pos.stop_premium:.2f})"
                    close_at = current_premium
                elif is_after_hours() and current_premium <= 0:
                    close_reason = "expired_worthless"
                    close_at = 0.0

            if close_reason is not None:
                if self.close_position(pos.id, close_at, close_reason):
                    final_status = "won" if close_at >= pos.entry_premium else (
                        "expired" if close_at <= 0 else "lost"
                    )
                    events.append({
                        "position_id": pos.id,
                        "signal_id": pos.signal_id,
                        "status": final_status,
                        "exit_premium": close_at,
                        "reason": close_reason,
                    })

        return events

    def get_pnl_summary(self) -> dict:
        """Aggregate P&L across all paper positions ever."""
        conn = self.db._connect()
        try:
            row = conn.execute("""
                SELECT
                    COUNT(*)                                              AS total,
                    COUNT(CASE WHEN status='open'    THEN 1 END)          AS open,
                    COUNT(CASE WHEN status='won'     THEN 1 END)          AS won,
                    COUNT(CASE WHEN status='lost'    THEN 1 END)          AS lost,
                    COUNT(CASE WHEN status='expired' THEN 1 END)          AS expired,
                    COALESCE(SUM(CASE WHEN status<>'open'
                                      THEN (exit_premium - entry_premium) * contracts * 100.0
                                      END), 0.0)                          AS pnl_usd
                FROM paper_positions
            """).fetchone()
        except Exception:
            logger.exception("Failed to read paper P&L summary")
            return {}
        finally:
            self.db._close(conn)

        if not row:
            return {}
        total, open_, won, lost, expired, pnl_usd = row
        closed = (won or 0) + (lost or 0) + (expired or 0)
        win_rate = ((won or 0) / closed * 100.0) if closed > 0 else 0.0
        return {
            "total": total or 0,
            "open": open_ or 0,
            "won": won or 0,
            "lost": lost or 0,
            "expired": expired or 0,
            "win_rate_pct": round(win_rate, 2),
            "pnl_usd": round(float(pnl_usd or 0.0), 2),
        }
