/* ============================================================
   SwarmSPX — UI Components
   Trade Card, Consensus Gauge, Round Timeline, Market Bar,
   Alert Badges, Activity Log
   ============================================================ */

"use strict";

// ── Market Bar ──────────────────────────────────────────────

const MarketBar = {
  init() {
    document.addEventListener("market:update", (e) => this.render(e.detail));
    document.addEventListener("state:full", (e) => {
      if (e.detail.market_context) this.render(e.detail.market_context);
      this._renderStatus(e.detail.status);
    });
    document.addEventListener("cycle:started", () => this._renderStatus("running"));
    document.addEventListener("round:started", () => this._renderStatus("deliberating"));
    document.addEventListener("consensus:reached", () => this._renderStatus("consensus"));
    document.addEventListener("cycle:completed", () => this._renderStatus("idle"));
    document.addEventListener("engine:error", () => this._renderStatus("error"));
  },

  render(ctx) {
    if (!ctx) return;

    const spxEl = document.getElementById("spx-price");
    const spxChg = document.getElementById("spx-change");
    const vixEl = document.getElementById("vix-level");
    const regimeEl = document.getElementById("regime-badge");
    const vwapEl = document.getElementById("vwap-distance");

    if (spxEl) {
      const price = parseFloat(ctx.spx_price) || 0;
      spxEl.textContent = price.toFixed(2);
    }

    if (spxChg && ctx.spx_change_pct != null) {
      const pct = parseFloat(ctx.spx_change_pct);
      spxChg.textContent = (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%";
      spxChg.className = "ticker-value mono " + (pct >= 0 ? "bull" : "bear");
    }

    if (vixEl) {
      const vix = parseFloat(ctx.vix_level) || 0;
      vixEl.textContent = vix.toFixed(2);
      vixEl.className = "ticker-value mono " + (vix > 25 ? "bear" : vix > 18 ? "accent" : "bull");
    }

    if (regimeEl && ctx.market_regime) {
      const r = ctx.market_regime.toLowerCase().replace(/\s+/g, "-");
      regimeEl.textContent = ctx.market_regime;
      regimeEl.className = "regime-badge " + r;
    }

    if (vwapEl && ctx.spx_vwap_distance_pct != null) {
      const d = parseFloat(ctx.spx_vwap_distance_pct);
      vwapEl.textContent = (d >= 0 ? "+" : "") + d.toFixed(3) + "%";
      vwapEl.className = "ticker-value mono " + (d >= 0 ? "bull" : "bear");
    }
  },

  _renderStatus(status) {
    const dot = document.getElementById("cycle-status-dot");
    const label = document.getElementById("cycle-status-label");
    if (dot) dot.className = "status-dot " + (status || "idle");
    if (label) label.textContent = (status || "idle").toUpperCase();
  },
};

// ── Trade Card ──────────────────────────────────────────────

const TradeCard = {
  init() {
    document.addEventListener("tradecard:generated", (e) => this.render(e.detail));
    document.addEventListener("state:full", (e) => {
      if (e.detail.trade_card) this.render(e.detail.trade_card);
    });
    document.addEventListener("cycle:started", () => this.clear());
  },

  clear() {
    const el = document.getElementById("trade-card");
    if (el) el.classList.remove("visible");
  },

  render(tc) {
    if (!tc) return;
    const el = document.getElementById("trade-card");
    if (!el) return;

    const action = (tc.action || tc.direction || "WAIT").toUpperCase();
    const actionClass = action === "BUY" || action === "BULL" ? "buy"
                      : action === "SELL" || action === "BEAR" ? "sell" : "wait";
    const dir = tc.direction ? tc.direction.toUpperCase() : "";

    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">
        <span class="tc-action ${actionClass}">${action}</span>
        ${dir && dir !== action ? `<span class="mono dim" style="font-size:.85rem">${dir}</span>` : ""}
      </div>
      <div class="tc-instrument">${tc.instrument || "SPX 0DTE"}</div>
      <div class="tc-prices">
        <div class="tc-price-item">
          <span class="tc-price-label">Entry</span>
          <span class="tc-price-val mono">${_fmtPrice(tc.entry_price_est)}</span>
        </div>
        <div class="tc-price-item">
          <span class="tc-price-label">Target</span>
          <span class="tc-price-val mono bull">${_fmtPrice(tc.target_price)}</span>
        </div>
        <div class="tc-price-item">
          <span class="tc-price-label">Stop</span>
          <span class="tc-price-val mono bear">${_fmtPrice(tc.stop_price)}</span>
        </div>
      </div>
      <div class="tc-rationale">${_esc(tc.rationale || "")}</div>
      ${tc.key_risk ? `<div class="tc-risk">Risk: ${_esc(tc.key_risk)}</div>` : ""}
      <div class="tc-meta">
        ${tc.time_window ? `<span>&#9202; ${_esc(tc.time_window)}</span>` : ""}
        ${tc.market_regime ? `<span>&#9881; ${_esc(tc.market_regime)}</span>` : ""}
        ${tc.confidence != null ? `<span>&#9733; ${tc.confidence}% conf</span>` : ""}
        ${tc.agreement_pct != null ? `<span>&#9745; ${tc.agreement_pct}% agree</span>` : ""}
      </div>
    `;
    // Trigger slide-in
    el.classList.remove("visible");
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("visible")));
  },
};

// ── Consensus Gauge ─────────────────────────────────────────

const ConsensusGauge = {
  init() {
    document.addEventListener("consensus:reached", (e) => this.render(e.detail));
    document.addEventListener("state:full", (e) => {
      if (e.detail.consensus) this.render(e.detail.consensus);
      if (e.detail.round_summaries && e.detail.round_summaries.length > 0) {
        const last = e.detail.round_summaries[e.detail.round_summaries.length - 1];
        this._renderVoteBar(last.vote_counts);
      }
    });
    document.addEventListener("round:completed", (e) => {
      this._renderVoteBar(e.detail.vote_counts);
    });
    document.addEventListener("cycle:started", () => this._reset());
  },

  _reset() {
    const wrap = document.getElementById("consensus-wrap");
    if (!wrap) return;
    wrap.querySelector(".gauge-value").textContent = "--";
    wrap.querySelector(".gauge-sub").textContent = "";
    this._drawArc(0);
    this._renderVoteBar({});
  },

  render(c) {
    if (!c) return;
    const conf = parseFloat(c.confidence) || 0;
    const agree = c.agreement_pct != null ? parseFloat(c.agreement_pct) : null;
    const dir = (c.direction || "").toUpperCase();

    const valEl = document.querySelector("#consensus-wrap .gauge-value");
    const subEl = document.querySelector("#consensus-wrap .gauge-sub");

    if (valEl) {
      valEl.textContent = conf.toFixed(0) + "%";
      valEl.className = "gauge-value mono " + (dir === "BULL" ? "bull" : dir === "BEAR" ? "bear" : "neut");
    }
    if (subEl) {
      subEl.textContent = (agree != null ? agree.toFixed(0) + "% agreement" : "") +
                          (dir ? "  " + dir : "");
    }

    this._drawArc(conf);

    if (c.vote_counts) this._renderVoteBar(c.vote_counts);

    // Alerts
    this._renderAlerts(c);
  },

  _drawArc(pct) {
    const svg = document.querySelector("#consensus-wrap .gauge-svg");
    if (!svg) return;

    const cx = 110, cy = 105, r = 85;
    const startAngle = Math.PI;
    const endAngle = startAngle + (Math.PI * Math.min(pct, 100) / 100);

    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);
    const large = pct > 50 ? 1 : 0;

    const color = pct >= 80 ? "var(--bull)" : pct >= 60 ? "#66bb6a" : pct >= 40 ? "var(--warn)" : "var(--bear)";

    svg.innerHTML = `
      <path d="M ${cx - r} ${cy} A ${r} ${r} 0 1 1 ${cx + r} ${cy}"
            fill="none" stroke="var(--border)" stroke-width="10" stroke-linecap="round" />
      ${pct > 0 ? `
      <path d="M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}"
            fill="none" stroke="${color}" stroke-width="10" stroke-linecap="round"
            style="filter: drop-shadow(0 0 6px ${color})" />
      ` : ""}
    `;
  },

  _renderVoteBar(counts) {
    const bar = document.querySelector("#consensus-wrap .vote-bar");
    const legend = document.querySelector("#consensus-wrap .vote-bar-legend");
    if (!bar) return;

    const bull = counts.BULL || counts.bull || 0;
    const bear = counts.BEAR || counts.bear || 0;
    const neut = counts.NEUTRAL || counts.neutral || 0;
    const total = bull + bear + neut || 1;

    bar.innerHTML = `
      <div class="seg-bull" style="width:${(bull/total*100).toFixed(1)}%"></div>
      <div class="seg-bear" style="width:${(bear/total*100).toFixed(1)}%"></div>
      <div class="seg-neut" style="width:${(neut/total*100).toFixed(1)}%"></div>
    `;
    if (legend) {
      legend.innerHTML = `
        <span class="bull">${bull} Bull</span>
        <span class="bear">${bear} Bear</span>
        <span class="neut">${neut} Neutral</span>
      `;
    }
  },

  _renderAlerts(c) {
    const contrarian = document.getElementById("alert-contrarian");
    const herding = document.getElementById("alert-herding");
    if (contrarian) {
      contrarian.className = "alert-badge " + (c.contrarian_alert ? "contrarian" : "hidden");
      if (c.contrarian_alert) contrarian.textContent = "Contrarian Alert";
    }
    if (herding) {
      const warn = c.herding_detected || c.herding_warning;
      herding.className = "alert-badge " + (warn ? "herding" : "hidden");
      if (warn) herding.textContent = "Herding Detected";
    }
  },
};

// ── Round Timeline ──────────────────────────────────────────

const RoundTimeline = {
  init() {
    document.addEventListener("round:started", () => this._render());
    document.addEventListener("round:completed", () => this._render());
    document.addEventListener("state:full", () => this._render());
    document.addEventListener("cycle:started", () => this._render());
  },

  _render() {
    const wrap = document.querySelector("#round-timeline .tl-rounds");
    if (!wrap) return;

    const total = SwarmState.total_rounds || 5;
    const current = SwarmState.current_round || 0;
    const summaries = SwarmState.round_summaries || [];

    let html = "";
    for (let i = 1; i <= total; i++) {
      const summary = summaries.find((s) => s.round_num === i);
      const isActive = i === current && SwarmState.status === "deliberating";
      const isDone = !!summary;

      let miniBar = "";
      let dirArrow = "";

      if (isDone && summary.vote_counts) {
        const vc = summary.vote_counts;
        const bull = vc.BULL || vc.bull || 0;
        const bear = vc.BEAR || vc.bear || 0;
        const neut = vc.NEUTRAL || vc.neutral || 0;
        const t = bull + bear + neut || 1;
        miniBar = `
          <div class="seg-bull" style="width:${(bull/t*100).toFixed(1)}%"></div>
          <div class="seg-bear" style="width:${(bear/t*100).toFixed(1)}%"></div>
          <div class="seg-neut" style="width:${(neut/t*100).toFixed(1)}%"></div>
        `;
        const dominant = bull >= bear && bull >= neut ? "bull"
                       : bear >= bull && bear >= neut ? "bear" : "neut";
        const arrow = dominant === "bull" ? "&#9650;" : dominant === "bear" ? "&#9660;" : "&#9654;";
        dirArrow = `<span class="tl-direction ${dominant}">${arrow}</span>`;
      }

      html += `
        <div class="tl-round ${isActive ? 'active' : ''}">
          <span class="tl-round-num">R${i}</span>
          <div class="tl-mini-bar">${miniBar}</div>
          ${dirArrow}
        </div>
      `;
    }
    wrap.innerHTML = html;
  },
};

// ── Activity Log ────────────────────────────────────────────

const ActivityLog = {
  _max: 100,

  init() {
    document.addEventListener("event:any", (e) => this._add(e.detail));
  },

  _add({ type, data }) {
    const wrap = document.getElementById("activity-log");
    if (!wrap) return;

    const now = new Date();
    const ts = now.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const msg = this._describe(type, data);

    const typeColor = type.includes("error") ? "bear"
                    : type.includes("bull") ? "bull"
                    : type.includes("consensus") || type.includes("trade_card") ? "bull"
                    : "accent";

    const entry = document.createElement("div");
    entry.className = "log-entry";
    entry.innerHTML = `
      <span class="log-time">${ts}</span>
      <span class="log-type ${typeColor}">${_esc(type.replace(/_/g, " "))}</span>
      <span class="log-msg">${_esc(msg)}</span>
    `;

    wrap.prepend(entry);

    // Prune old entries
    while (wrap.children.length > this._max) {
      wrap.removeChild(wrap.lastChild);
    }
  },

  _describe(type, d) {
    switch (type) {
      case "cycle_started":       return `Cycle #${d.cycle_id} initiated`;
      case "market_data_fetched":
        const mc = d.market_context || {};
        return `SPX ${mc.spx_price || "?"} | VIX ${mc.vix_level || "?"} | ${mc.market_regime || "?"}`;
      case "round_started":       return `Round ${d.round_num}/${d.total_rounds} deliberation`;
      case "agent_voted":
        const flip = d.changed_from ? ` (flipped from ${d.changed_from})` : "";
        return `${d.agent_name} [${d.tribe}] -> ${d.direction} (${d.conviction}/10)${flip}`;
      case "round_completed":
        const vc = d.vote_counts || {};
        return `Bull:${vc.BULL||vc.bull||0} Bear:${vc.BEAR||vc.bear||0} Neutral:${vc.NEUTRAL||vc.neutral||0}`;
      case "consensus_reached":
        const c = d.consensus || d;
        return `${c.direction || "?"} @ ${c.confidence || "?"}% confidence, ${c.agreement_pct || "?"}% agreement`;
      case "trade_card_generated":
        const tc = d.trade_card || d;
        return `${tc.action || tc.direction || "?"} ${tc.instrument || "SPX"} Entry:${tc.entry_price_est || "?"}`;
      case "cycle_completed":     return `Cycle #${d.cycle_id} done in ${parseFloat(d.duration_sec || 0).toFixed(1)}s`;
      case "engine_error":        return d.message || "Unknown error";
      default:                    return JSON.stringify(d).slice(0, 120);
    }
  },
};

// ── Helpers ─────────────────────────────────────────────────

function _fmtPrice(v) {
  if (v == null) return "--";
  const n = parseFloat(v);
  return isNaN(n) ? String(v) : n.toFixed(2);
}

function _esc(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}

// ── Boot Components ─────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  MarketBar.init();
  TradeCard.init();
  ConsensusGauge.init();
  RoundTimeline.init();
  ActivityLog.init();
});
