import duckdb
import json
from datetime import datetime
from pathlib import Path

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
                trade_setup JSON,
                agent_votes JSON,
                outcome VARCHAR,
                outcome_pct DOUBLE
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

    def store_simulation_result(self, result: dict):
        self.conn.execute("""
            INSERT INTO simulation_results
            (id, timestamp, direction, confidence, agreement_pct, trade_setup, agent_votes, outcome, outcome_pct)
            VALUES (nextval('simulation_results_id_seq'), ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            datetime.now().isoformat(),
            result.get("direction", "NEUTRAL"),
            result.get("confidence", 0.0),
            result.get("agreement_pct", 0.0),
            json.dumps(result.get("trade_setup", {})),
            json.dumps(result.get("agent_votes", {})),
            result.get("outcome", "pending"),
            result.get("outcome_pct", 0.0)
        ])

    def close(self):
        self.conn.close()
