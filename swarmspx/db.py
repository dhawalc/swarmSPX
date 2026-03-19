import duckdb
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

class Database:
    def __init__(self, path: str = "data/swarmspx.duckdb"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(path)

    def init_schema(self):
        self.conn.execute("""
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
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS market_snapshots_id_seq
        """)
        self.conn.execute("""
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
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS simulation_results_id_seq
        """)

    def store_snapshot(self, snapshot: dict):
        self.conn.execute("""
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

    def get_latest_snapshot(self) -> dict:
        result = self.conn.execute("""
            SELECT * FROM market_snapshots
            ORDER BY timestamp DESC LIMIT 1
        """).fetchone()
        if not result:
            return {}
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, result))

    def store_simulation_result(self, result: dict) -> Optional[int]:
        """Store a simulation result and return its ID."""
        row = self.conn.execute("""
            INSERT INTO simulation_results
            (id, timestamp, direction, confidence, agreement_pct, spx_entry_price, memory_id,
             trade_setup, agent_votes, outcome, outcome_pct)
            VALUES (nextval('simulation_results_id_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, [
            datetime.now().isoformat(),
            result.get("direction", "NEUTRAL"),
            result.get("confidence", 0.0),
            result.get("agreement_pct", 0.0),
            result.get("spx_entry_price", 0.0),
            result.get("memory_id"),
            json.dumps(result.get("trade_setup", {})),
            json.dumps(result.get("agent_votes", {})),
            result.get("outcome", "pending"),
            result.get("outcome_pct", 0.0)
        ]).fetchone()
        return row[0] if row else None

    def update_outcome(self, signal_id: int, outcome: str, outcome_pct: float):
        """Update a signal's outcome after resolution."""
        self.conn.execute("""
            UPDATE simulation_results
            SET outcome = ?, outcome_pct = ?
            WHERE id = ?
        """, [outcome, outcome_pct, signal_id])

    def get_pending_signals(self, max_age_hours: int = 24) -> list[dict]:
        """Get unresolved signals from the last N hours."""
        cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
        rows = self.conn.execute("""
            SELECT id, timestamp, direction, confidence, spx_entry_price, memory_id,
                   trade_setup, agent_votes
            FROM simulation_results
            WHERE outcome = 'pending' AND timestamp > ?
            ORDER BY timestamp ASC
        """, [cutoff]).fetchall()
        if not rows:
            return []
        cols = ["id", "timestamp", "direction", "confidence", "spx_entry_price",
                "memory_id", "trade_setup", "agent_votes"]
        return [dict(zip(cols, row)) for row in rows]

    def get_recent_signals(self, limit: int = 20) -> list[dict]:
        """Get recent signals for the dashboard."""
        rows = self.conn.execute("""
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

    def get_signal_stats(self) -> dict:
        """Get aggregate signal statistics."""
        row = self.conn.execute("""
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

    def close(self):
        self.conn.close()
