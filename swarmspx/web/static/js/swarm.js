/* ============================================================
   SwarmSPX — WebSocket Client & Global State Manager
   ============================================================ */

"use strict";

const SwarmState = {
  status: "idle",
  cycle_id: null,
  market_context: null,
  current_round: 0,
  total_rounds: 5,
  votes: {},
  round_summaries: [],
  consensus: null,
  trade_card: null,
  error: null,
};

// ── WebSocket Connection ────────────────────────────────────

const WS = {
  socket: null,
  url: null,
  retryDelay: 1000,
  maxRetry: 30000,
  retryCount: 0,

  connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    this.url = `${proto}//${location.host}/ws`;
    this._open();
  },

  _open() {
    if (this.socket && this.socket.readyState <= 1) return;
    this.socket = new WebSocket(this.url);

    this.socket.onopen = () => {
      this.retryCount = 0;
      this.retryDelay = 1000;
      _dispatch("ws:connected");
      _updateWsStatus(true);
    };

    this.socket.onclose = () => {
      _updateWsStatus(false);
      this._retry();
    };

    this.socket.onerror = () => {
      this.socket.close();
    };

    this.socket.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        this._handle(msg);
      } catch (e) {
        console.error("WS parse error:", e);
      }
    };
  },

  _retry() {
    this.retryCount++;
    const delay = Math.min(this.retryDelay * Math.pow(1.5, this.retryCount), this.maxRetry);
    setTimeout(() => this._open(), delay);
  },

  _handle(msg) {
    const { type, data } = msg;

    if (type === "full_state") {
      Object.assign(SwarmState, data);
      _dispatch("state:full", SwarmState);
      return;
    }

    // Route by event_type
    switch (type) {
      case "cycle_started":
        SwarmState.status = "running";
        SwarmState.cycle_id = data.cycle_id;
        SwarmState.votes = {};
        SwarmState.round_summaries = [];
        SwarmState.consensus = null;
        SwarmState.trade_card = null;
        SwarmState.error = null;
        _dispatch("cycle:started", data);
        break;

      case "market_data_fetched":
        SwarmState.market_context = data.market_context;
        SwarmState.status = "running";
        _dispatch("market:update", data.market_context);
        break;

      case "round_started":
        SwarmState.current_round = data.round_num;
        SwarmState.total_rounds = data.total_rounds;
        SwarmState.status = "deliberating";
        _dispatch("round:started", data);
        break;

      case "agent_voted":
        SwarmState.votes[data.agent_id] = data;
        _dispatch("agent:voted", data);
        break;

      case "round_completed":
        SwarmState.round_summaries.push({
          round_num: data.round_num,
          vote_counts: data.vote_counts,
          votes: data.votes,
        });
        _dispatch("round:completed", data);
        break;

      case "consensus_reached":
        SwarmState.consensus = data.consensus;
        SwarmState.status = "consensus";
        _dispatch("consensus:reached", data.consensus);
        break;

      case "trade_card_generated":
        SwarmState.trade_card = data.trade_card;
        SwarmState.status = "complete";
        _dispatch("tradecard:generated", data.trade_card);
        break;

      case "cycle_completed":
        SwarmState.status = "idle";
        _dispatch("cycle:completed", data);
        break;

      case "engine_error":
        SwarmState.error = data.message;
        SwarmState.status = "error";
        _dispatch("engine:error", data);
        break;
    }

    // Always fire generic event for activity log
    _dispatch("event:any", { type, data });
  },
};

// ── DOM Custom Events ───────────────────────────────────────

function _dispatch(name, detail) {
  document.dispatchEvent(new CustomEvent(name, { detail }));
}

function _updateWsStatus(connected) {
  const el = document.getElementById("ws-status");
  if (!el) return;
  const dot = el.querySelector(".status-dot");
  const label = el.querySelector(".ws-label");
  if (connected) {
    dot.className = "status-dot complete";
    label.textContent = "LIVE";
  } else {
    dot.className = "status-dot error";
    label.textContent = "OFFLINE";
  }
}

// ── Trigger Button ──────────────────────────────────────────

function initTrigger() {
  const btn = document.getElementById("trigger-btn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const res = await fetch("/api/cycle/trigger", { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        console.warn("Trigger failed:", body.detail || res.statusText);
      }
    } catch (e) {
      console.error("Trigger error:", e);
    }
    // Re-enable after 3s to avoid double-trigger
    setTimeout(() => { btn.disabled = false; }, 3000);
  });

  // Disable while cycle is running
  document.addEventListener("cycle:started", () => { btn.disabled = true; });
  document.addEventListener("cycle:completed", () => { btn.disabled = false; });
  document.addEventListener("engine:error", () => { btn.disabled = false; });
}

// ── Boot ────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  WS.connect();
  initTrigger();
});
