import duckdb
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

class Database:
    def __init__(self, path: str = "data/swarmspx.duckdb"):
        self._path = path
        self._persistent_conn = None
        if path == ":memory:":
            # In-memory DBs need a persistent connection (no file to reconnect to)
            self._persistent_conn = duckdb.connect(path)
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        """Open a short-lived connection (releases DuckDB file lock on close).
        For :memory: databases, returns the persistent connection."""
        if self._persistent_conn is not None:
            return self._persistent_conn
        return duckdb.connect(self._path)

    def _close(self, conn):
        """Close a connection unless it's the persistent in-memory one."""
        if conn is not self._persistent_conn:
            conn.close()

    def init_schema(self):
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    id INTEGER PRIMARY KEY,
                    timestamp TIMESTAMP,
                    spx_price DOUBLE,
                    spx_change_pct DOUBLE,
                    spx_vwap DOUBLE,
                    vix_level DOUBLE,
                    vix_change DOUBLE,
                    put_call_ratio DOUBLE,
                    market_regime VARCHAR,
                    raw_data JSON
                )
            """)
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS market_snapshots_id_seq
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS simulation_results (
                    id INTEGER PRIMARY KEY,
                    timestamp TIMESTAMP,
                    direction VARCHAR,
                    confidence DOUBLE,
                    agreement_pct DOUBLE,
                    spx_entry_price DOUBLE,
                    memory_id VARCHAR,
                    trade_setup JSON,
                    agent_votes JSON,
                    outcome VARCHAR DEFAULT 'pending',
                    outcome_pct DOUBLE DEFAULT 0.0
                )
            """)
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS simulation_results_id_seq
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_vote_history (
                    id INTEGER PRIMARY KEY,
                    signal_id INTEGER,
                    agent_id VARCHAR,
                    direction VARCHAR,
                    conviction INTEGER,
                    regime VARCHAR,
                    timestamp TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS agent_vote_history_id_seq
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_scores (
                    id INTEGER PRIMARY KEY,
                    agent_id VARCHAR,
                    regime VARCHAR,
                    elo_rating DOUBLE DEFAULT 1000.0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    total_signals INTEGER DEFAULT 0,
                    last_updated TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS agent_scores_id_seq
            """)
            # Schema migrations — idempotent ADD COLUMN if missing.
            #
            # Pattern: probe with SELECT col LIMIT 0; on failure, ALTER TABLE.
            # Multiple init_schema() calls are safe.  Option-P&L columns
            # (entry/exit_premium, strike, type) are required so OutcomeTracker
            # can compute outcome from option premium delta instead of SPX
            # move (review #1: training data was on the wrong signal).
            _migrations = [
                ("spx_entry_price", "DOUBLE DEFAULT 0.0"),
                ("memory_id",       "VARCHAR DEFAULT ''"),
                ("entry_premium",   "DOUBLE DEFAULT 0.0"),
                ("exit_premium",    "DOUBLE DEFAULT 0.0"),
                ("option_strike",   "DOUBLE DEFAULT 0.0"),
                ("option_type",     "VARCHAR DEFAULT ''"),
            ]
            for col_name, col_type in _migrations:
                try:
                    conn.execute(f"SELECT {col_name} FROM simulation_results LIMIT 0")
                except duckdb.Error:
                    # Column missing — apply migration.
                    conn.execute(
                        f"ALTER TABLE simulation_results ADD COLUMN "
                        f"{col_name} {col_type}"
                    )
        finally:
            self._close(conn)

    def store_snapshot(self, snapshot: dict):
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO market_snapshots
                (id, timestamp, spx_price, spx_change_pct, spx_vwap, vix_level, vix_change, put_call_ratio, market_regime, raw_data)
                VALUES (nextval('market_snapshots_id_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                snapshot.get("timestamp", datetime.now().isoformat()),
                snapshot.get("spx_price", 0.0),
                snapshot.get("spx_change_pct", 0.0),
                snapshot.get("spx_vwap", 0.0),
                snapshot.get("vix_level", 0.0),
                snapshot.get("vix_change", 0.0),
                snapshot.get("put_call_ratio", 1.0),
                snapshot.get("market_regime", "unknown"),
                json.dumps(snapshot)
            ])
        finally:
            self._close(conn)

    def get_latest_snapshot(self) -> dict:
        conn = self._connect()
        try:
            result = conn.execute("""
                SELECT * FROM market_snapshots
                ORDER BY timestamp DESC LIMIT 1
            """).fetchone()
            if not result:
                return {}
            cols = [d[0] for d in conn.description]
            return dict(zip(cols, result))
        finally:
            self._close(conn)

    def store_simulation_result(self, result: dict) -> Optional[int]:
        """Store a simulation result and return its ID.

        Optional keys for option-P&L tracking (review #1):
          entry_premium  — premium paid (or net debit) at signal time
          option_strike  — strike of the selected option (0.0 for spreads)
          option_type    — 'call' / 'put' / '' (empty for spreads/condors)
        """
        conn = self._connect()
        try:
            row = conn.execute("""
                INSERT INTO simulation_results
                (id, timestamp, direction, confidence, agreement_pct,
                 spx_entry_price, entry_premium, option_strike, option_type,
                 memory_id, trade_setup, agent_votes, outcome, outcome_pct)
                VALUES (nextval('simulation_results_id_seq'),
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
            """, [
                datetime.now().isoformat(),
                result.get("direction", "NEUTRAL"),
                float(result.get("confidence", 0.0) or 0.0),
                float(result.get("agreement_pct", 0.0) or 0.0),
                float(result.get("spx_entry_price", 0.0) or 0.0),
                float(result.get("entry_premium", 0.0) or 0.0),
                float(result.get("option_strike", 0.0) or 0.0),
                result.get("option_type", "") or "",
                result.get("memory_id"),
                json.dumps(result.get("trade_setup", {})),
                json.dumps(result.get("agent_votes", {})),
                result.get("outcome", "pending"),
                float(result.get("outcome_pct", 0.0) or 0.0),
            ]).fetchone()
            return row[0] if row else None
        finally:
            self._close(conn)

    def update_outcome(
        self,
        signal_id: int,
        outcome: str,
        outcome_pct: float,
        exit_premium: float = 0.0,
    ):
        """Update a signal's outcome after resolution.

        Args:
            signal_id:    Row id in simulation_results.
            outcome:      'win' / 'loss' / 'scratch'.
            outcome_pct:  P&L as a percentage (e.g. +75.0 means +75%).
            exit_premium: Option premium at resolution (0.0 if N/A).
        """
        conn = self._connect()
        try:
            conn.execute("""
                UPDATE simulation_results
                SET outcome = ?, outcome_pct = ?, exit_premium = ?
                WHERE id = ?
            """, [outcome, float(outcome_pct), float(exit_premium), signal_id])
        finally:
            self._close(conn)

    def get_pending_signals(self, max_age_hours: int = 24) -> list[dict]:
        """Get unresolved signals from the last N hours.

        Returns dicts including option-P&L fields (entry_premium, option_strike,
        option_type) so OutcomeTracker can compute resolution based on actual
        option premium delta, not SPX move.
        """
        cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT id, timestamp, direction, confidence,
                       spx_entry_price, entry_premium, option_strike, option_type,
                       memory_id, trade_setup, agent_votes
                FROM simulation_results
                WHERE outcome = 'pending' AND timestamp > ?
                ORDER BY timestamp ASC
            """, [cutoff]).fetchall()
            if not rows:
                return []
            cols = ["id", "timestamp", "direction", "confidence",
                    "spx_entry_price", "entry_premium", "option_strike", "option_type",
                    "memory_id", "trade_setup", "agent_votes"]
            return [dict(zip(cols, row)) for row in rows]
        finally:
            self._close(conn)

    def get_recent_signals(self, limit: int = 20) -> list[dict]:
        """Get recent signals for the dashboard."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT id, timestamp, direction, confidence, agreement_pct,
                       spx_entry_price, outcome, outcome_pct
                FROM simulation_results
                ORDER BY timestamp DESC
                LIMIT ?
            """, [limit]).fetchall()
            if not rows:
                return []
            cols = ["id", "timestamp", "direction", "confidence", "agreement_pct",
                    "spx_entry_price", "outcome", "outcome_pct"]
            return [dict(zip(cols, row)) for row in rows]
        finally:
            self._close(conn)

    def get_signal_stats(self) -> dict:
        """Get aggregate signal statistics."""
        conn = self._connect()
        try:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN outcome != 'pending' THEN 1 END) as resolved,
                    COUNT(CASE WHEN outcome = 'win' THEN 1 END) as wins,
                    COUNT(CASE WHEN outcome = 'loss' THEN 1 END) as losses,
                    AVG(CASE WHEN outcome != 'pending' THEN outcome_pct END) as avg_pnl
                FROM simulation_results
            """).fetchone()
            if not row:
                return {"total": 0, "resolved": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "avg_pnl": 0.0}
            total, resolved, wins, losses, avg_pnl = row
            return {
                "total": total,
                "resolved": resolved,
                "wins": wins,
                "losses": losses,
                "win_rate": (wins / resolved * 100) if resolved > 0 else 0.0,
                "avg_pnl": round(avg_pnl or 0.0, 2),
            }
        finally:
            self._close(conn)

    def store_agent_votes(self, signal_id: int, votes: list[dict], regime: str):
        """Store individual agent votes for a signal.
        votes: list of {agent_id, direction, conviction}
        """
        conn = self._connect()
        try:
            for vote in votes:
                conn.execute("""
                    INSERT INTO agent_vote_history
                    (id, signal_id, agent_id, direction, conviction, regime, timestamp)
                    VALUES (nextval('agent_vote_history_id_seq'), ?, ?, ?, ?, ?, ?)
                """, [
                    signal_id,
                    vote.get("agent_id"),
                    vote.get("direction", "NEUTRAL"),
                    vote.get("conviction", 0),
                    regime,
                    datetime.now().isoformat(),
                ])
        finally:
            self._close(conn)

    def get_agent_votes_for_signal(self, signal_id: int) -> list[dict]:
        """Get all agent votes for a specific signal."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT id, signal_id, agent_id, direction, conviction, regime, timestamp
                FROM agent_vote_history
                WHERE signal_id = ?
                ORDER BY timestamp ASC
            """, [signal_id]).fetchall()
            if not rows:
                return []
            cols = ["id", "signal_id", "agent_id", "direction", "conviction", "regime", "timestamp"]
            return [dict(zip(cols, row)) for row in rows]
        finally:
            self._close(conn)

    def get_agent_scores(self, regime: str = None) -> list[dict]:
        """Get agent scores, optionally filtered by regime."""
        conn = self._connect()
        try:
            if regime is not None:
                rows = conn.execute("""
                    SELECT id, agent_id, regime, elo_rating, wins, losses, total_signals, last_updated
                    FROM agent_scores
                    WHERE regime = ?
                    ORDER BY elo_rating DESC
                """, [regime]).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, agent_id, regime, elo_rating, wins, losses, total_signals, last_updated
                    FROM agent_scores
                    ORDER BY elo_rating DESC
                """).fetchall()
            if not rows:
                return []
            cols = ["id", "agent_id", "regime", "elo_rating", "wins", "losses", "total_signals", "last_updated"]
            return [dict(zip(cols, row)) for row in rows]
        finally:
            self._close(conn)

    def upsert_agent_score(self, agent_id: str, regime: str, elo_rating: float,
                           wins: int, losses: int, total_signals: int):
        """Insert or update an agent's score for a regime."""
        conn = self._connect()
        try:
            existing = conn.execute("""
                SELECT id FROM agent_scores
                WHERE agent_id = ? AND regime = ?
            """, [agent_id, regime]).fetchone()
            if existing:
                conn.execute("""
                    UPDATE agent_scores
                    SET elo_rating = ?, wins = ?, losses = ?, total_signals = ?, last_updated = ?
                    WHERE agent_id = ? AND regime = ?
                """, [elo_rating, wins, losses, total_signals, datetime.now().isoformat(), agent_id, regime])
            else:
                conn.execute("""
                    INSERT INTO agent_scores
                    (id, agent_id, regime, elo_rating, wins, losses, total_signals, last_updated)
                    VALUES (nextval('agent_scores_id_seq'), ?, ?, ?, ?, ?, ?, ?)
                """, [agent_id, regime, elo_rating, wins, losses, total_signals, datetime.now().isoformat()])
        finally:
            self._close(conn)

    def get_agent_vote_history(self, agent_id: str, limit: int = 50) -> list[dict]:
        """Get recent vote history for a specific agent with outcomes."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT
                    avh.id,
                    avh.signal_id,
                    avh.agent_id,
                    avh.direction,
                    avh.conviction,
                    avh.regime,
                    avh.timestamp,
                    sr.outcome,
                    sr.outcome_pct
                FROM agent_vote_history avh
                LEFT JOIN simulation_results sr ON avh.signal_id = sr.id
                WHERE avh.agent_id = ?
                ORDER BY avh.timestamp DESC
                LIMIT ?
            """, [agent_id, limit]).fetchall()
            if not rows:
                return []
            cols = ["id", "signal_id", "agent_id", "direction", "conviction",
                    "regime", "timestamp", "outcome", "outcome_pct"]
            return [dict(zip(cols, row)) for row in rows]
        finally:
            self._close(conn)

    def close(self):
        if self._persistent_conn is not None:
            self._persistent_conn.close()
            self._persistent_conn = None
