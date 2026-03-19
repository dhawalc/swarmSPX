/* ============================================================
   SwarmSPX — UI Components
   Market Bar, Trade Card, Consensus Gauge, Round Timeline,
   Debate Room, Alert Badges, Activity Log
   ============================================================ */

"use strict";

// ── Market Bar ──────────────────────────────────────────────

const MarketBar = {
  _lastPrice: null,

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
    const vixFill = document.getElementById("vix-thermo-fill");

    if (spxEl) {
      const price = parseFloat(ctx.spx_price) || 0;
      // Flash on price change
      if (this._lastPrice !== null && price !== this._lastPrice) {
        const flashClass = price > this._lastPrice ? "price-flash-up" : "price-flash-down";
        spxEl.classList.remove("price-flash-up", "price-flash-down");
        void spxEl.offsetWidth; // Force reflow
        spxEl.classList.add(flashClass);
        setTimeout(() => spxEl.classList.remove(flashClass), 500);
      }
      this._lastPrice = price;
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

      // VIX thermometer: 10-40 range mapped to 0-100%
      if (vixFill) {
        const pct = Math.max(0, Math.min(100, ((vix - 10) / 30) * 100));
        vixFill.style.width = pct + "%";
        vixFill.style.background = vix > 25 ? "var(--bear)" : vix > 18 ? "var(--warn)" : "var(--bull)";
      }
    }

    if (regimeEl && ctx.market_regime) {
      const r = ctx.market_regime.toLowerCase().replace(/[\s_]+/g, "-");
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
    if (!el) return;
    el.className = "card";
    el.innerHTML = `
      <div class="card-header">
        <span class="card-header-icon">&#9889;</span> Trade Signal
      </div>
      <div class="tc-waiting">
        <div class="tc-scan-text">SCANNING...</div>
        <div class="tc-scan-bar"></div>
      </div>
    `;
  },

  render(tc) {
    if (!tc) return;
    const el = document.getElementById("trade-card");
    if (!el) return;

    const action = (tc.action || tc.direction || "WAIT").toUpperCase();
    const actionClass = action === "BUY" || action === "BULL" ? "buy"
                      : action === "SELL" || action === "BEAR" ? "sell" : "wait";
    const dir = tc.direction ? tc.direction.toUpperCase() : "";
    const isBull = dir === "BULL" || action === "BUY";
    const isBear = dir === "BEAR" || action === "SELL";

    const arrow = isBull ? "&#9650;" : isBear ? "&#9660;" : "&#9654;";
    const arrowClass = isBull ? "bull" : isBear ? "bear" : "neut";
    const borderClass = isBull ? "tc-border-bull" : isBear ? "tc-border-bear" : "";

    el.className = "card " + borderClass;

    el.innerHTML = `
      <div class="card-header">
        <span class="card-header-icon">&#9889;</span> Trade Signal
      </div>
      <div class="tc-body tc-materialize">
        <div style="display:flex;align-items:center;gap:14px;margin-bottom:6px;">
          <span class="tc-direction-arrow ${arrowClass}">${arrow}</span>
          <div>
            <span class="tc-action ${actionClass}">${_esc(action)}</span>
            ${dir && dir !== action ? `<span class="mono dim" style="font-size:.8rem;margin-left:8px;">${_esc(dir)}</span>` : ""}
          </div>
        </div>
        <div class="tc-instrument">${_esc(tc.instrument || "SPX 0DTE")}</div>
        <div class="tc-price-ladder">
          <div class="tc-price-level target">
            <span class="tc-price-tag bull">TARGET</span>
            <span class="tc-price-val mono bull">${_fmtPrice(tc.target_price)}</span>
          </div>
          <div class="tc-price-level entry">
            <span class="tc-price-tag accent">ENTRY</span>
            <span class="tc-price-val mono accent">${_fmtPrice(tc.entry_price_est)}</span>
          </div>
          <div class="tc-price-level stop">
            <span class="tc-price-tag bear">STOP</span>
            <span class="tc-price-val mono bear">${_fmtPrice(tc.stop_price)}</span>
          </div>
        </div>
        <div class="tc-rationale">${_esc(tc.rationale || "")}</div>
        ${tc.key_risk ? `<div class="tc-risk">${_esc(tc.key_risk)}</div>` : ""}
        <div class="tc-meta">
          ${tc.time_window ? `<span>&#9202; ${_esc(tc.time_window)}</span>` : ""}
          ${tc.market_regime ? `<span>&#9881; ${_esc(tc.market_regime)}</span>` : ""}
          ${tc.confidence != null ? `<span>&#9733; ${tc.confidence}% conf</span>` : ""}
          ${tc.agreement_pct != null ? `<span>&#9745; ${tc.agreement_pct}% agree</span>` : ""}
        </div>
      </div>
    `;
  },
};

// ── Consensus Gauge ─────────────────────────────────────────

const ConsensusGauge = {
  _animTarget: 0,
  _animCurrent: 0,
  _animating: false,

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

    // Initial draw
    this._drawArc(0, "NEUTRAL");
  },

  _reset() {
    const valEl = document.getElementById("gauge-value");
    const subEl = document.getElementById("gauge-sub");
    if (valEl) { valEl.textContent = "--"; valEl.className = "gauge-value mono"; }
    if (subEl) subEl.textContent = "";
    this._animTarget = 0;
    this._animCurrent = 0;
    this._drawArc(0, "NEUTRAL");
    this._renderVoteBar({});
  },

  render(c) {
    if (!c) return;
    const conf = parseFloat(c.confidence) || 0;
    const agree = c.agreement_pct != null ? parseFloat(c.agreement_pct) : null;
    const dir = (c.direction || "").toUpperCase();

    const valEl = document.getElementById("gauge-value");
    const subEl = document.getElementById("gauge-sub");

    if (valEl) {
      valEl.textContent = conf.toFixed(0) + "%";
      valEl.className = "gauge-value mono " + (dir === "BULL" ? "bull" : dir === "BEAR" ? "bear" : "neut");
    }
    if (subEl) {
      subEl.textContent = (agree != null ? agree.toFixed(0) + "% agreement" : "") +
                          (dir ? "  " + dir : "");
    }

    // Animated arc sweep
    this._animTarget = conf;
    if (!this._animating) this._animateArc(dir);

    if (c.vote_counts) this._renderVoteBar(c.vote_counts);
    this._renderAlerts(c);
  },

  _animateArc(dir) {
    this._animating = true;
    const step = () => {
      const diff = this._animTarget - this._animCurrent;
      if (Math.abs(diff) < 0.5) {
        this._animCurrent = this._animTarget;
        this._drawArc(this._animCurrent, dir);
        this._animating = false;
        return;
      }
      this._animCurrent += diff * 0.06;
      this._drawArc(this._animCurrent, dir);
      requestAnimationFrame(step);
    };
    step();
  },

  _drawArc(pct, dir) {
    const svg = document.getElementById("gauge-svg");
    if (!svg) return;

    const cx = 110, cy = 110, r = 85;
    const startAngle = Math.PI;
    const endAngle = startAngle + (Math.PI * Math.min(pct, 100) / 100);

    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);
    const large = pct > 50 ? 1 : 0;

    // Color based on confidence level
    let color, glowColor;
    if (pct >= 80) {
      color = "var(--bull)"; glowColor = "rgba(0,230,118,0.4)";
    } else if (pct >= 60) {
      color = "#66bb6a"; glowColor = "rgba(102,187,106,0.3)";
    } else if (pct >= 40) {
      color = "var(--warn)"; glowColor = "rgba(255,214,0,0.3)";
    } else {
      color = "var(--bear)"; glowColor = "rgba(255,23,68,0.3)";
    }

    // Needle angle
    const needleAngle = startAngle + (Math.PI * Math.min(pct, 100) / 100);
    const needleLen = r - 15;
    const nx = cx + needleLen * Math.cos(needleAngle);
    const ny = cy + needleLen * Math.sin(needleAngle);

    svg.innerHTML = `
      <defs>
        <filter id="gauge-glow">
          <feGaussianBlur in="SourceGraphic" stdDeviation="3" />
        </filter>
      </defs>
      <!-- Background arc -->
      <path d="M ${cx - r} ${cy} A ${r} ${r} 0 1 1 ${cx + r} ${cy}"
            fill="none" stroke="rgba(255,255,255,0.04)" stroke-width="10" stroke-linecap="round" />
      <!-- Tick marks -->
      ${_gaugeTickMarks(cx, cy, r)}
      ${pct > 0 ? `
      <!-- Glow arc -->
      <path d="M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}"
            fill="none" stroke="${color}" stroke-width="12" stroke-linecap="round"
            filter="url(#gauge-glow)" opacity="0.5" />
      <!-- Main arc -->
      <path d="M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}"
            fill="none" stroke="${color}" stroke-width="8" stroke-linecap="round" />
      <!-- Needle -->
      <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}"
            stroke="${color}" stroke-width="2" stroke-linecap="round" />
      <!-- Needle tip glow -->
      <circle cx="${nx.toFixed(1)}" cy="${ny.toFixed(1)}" r="4"
              fill="${color}" filter="url(#gauge-glow)" />
      <circle cx="${nx.toFixed(1)}" cy="${ny.toFixed(1)}" r="2" fill="${color}" />
      ` : ""}
      <!-- Center dot -->
      <circle cx="${cx}" cy="${cy}" r="3" fill="rgba(255,255,255,0.15)" />
    `;
  },

  _renderVoteBar(counts) {
    const bar = document.getElementById("vote-bar");
    const legend = document.getElementById("vote-bar-legend");
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

function _gaugeTickMarks(cx, cy, r) {
  let marks = "";
  for (let i = 0; i <= 10; i++) {
    const angle = Math.PI + (Math.PI * i / 10);
    const inner = r + 8;
    const outer = r + (i % 5 === 0 ? 16 : 12);
    const x1 = cx + inner * Math.cos(angle);
    const y1 = cy + inner * Math.sin(angle);
    const x2 = cx + outer * Math.cos(angle);
    const y2 = cy + outer * Math.sin(angle);
    marks += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"
                stroke="rgba(255,255,255,${i % 5 === 0 ? 0.12 : 0.06})" stroke-width="${i % 5 === 0 ? 1.5 : 0.8}" />`;
  }
  return marks;
}

// ── Round Timeline ──────────────────────────────────────────

const RoundTimeline = {
  init() {
    document.addEventListener("round:started", () => this._render());
    document.addEventListener("round:completed", () => this._render());
    document.addEventListener("state:full", () => this._render());
    document.addEventListener("cycle:started", () => this._render());
  },

  _render() {
    const wrap = document.getElementById("tl-rounds");
    if (!wrap) return;

    const total = SwarmState.total_rounds || 5;
    const current = SwarmState.current_round || 0;
    const summaries = SwarmState.round_summaries || [];

    if (summaries.length === 0 && current === 0) {
      wrap.innerHTML = '<div class="dim mono" style="font-size:.8rem;text-align:center;padding:20px 0;">No rounds yet</div>';
      return;
    }

    let html = "";
    for (let i = 1; i <= total; i++) {
      const summary = summaries.find((s) => s.round_num === i);
      const isActive = i === current && SwarmState.status === "deliberating";
      const isDone = !!summary;

      let pieCanvas = "";
      let dirArrow = "";
      let checkMark = "";

      if (isDone && summary.vote_counts) {
        const vc = summary.vote_counts;
        const bull = vc.BULL || vc.bull || 0;
        const bear = vc.BEAR || vc.bear || 0;
        const neut = vc.NEUTRAL || vc.neutral || 0;

        // We'll draw the pie chart after DOM update
        pieCanvas = `<div class="tl-mini-pie"><canvas data-bull="${bull}" data-bear="${bear}" data-neut="${neut}" width="56" height="56"></canvas></div>`;

        const dominant = bull >= bear && bull >= neut ? "bull"
                       : bear >= bull && bear >= neut ? "bear" : "neut";
        const arrow = dominant === "bull" ? "&#9650;" : dominant === "bear" ? "&#9660;" : "&#9654;";
        dirArrow = `<span class="tl-direction ${dominant}">${arrow}</span>`;
        checkMark = "";
      } else if (isActive) {
        pieCanvas = `<div class="tl-mini-pie" style="border:1px solid var(--accent);border-radius:50%;"></div>`;
      } else {
        pieCanvas = `<div class="tl-mini-pie"></div>`;
      }

      html += `
        <div class="tl-round ${isActive ? 'active' : ''} ${isDone ? 'done' : ''}">
          <span class="tl-round-num">R${i}</span>
          ${pieCanvas}
          ${dirArrow}
        </div>
      `;
    }
    wrap.innerHTML = html;

    // Draw mini pie charts
    wrap.querySelectorAll(".tl-mini-pie canvas").forEach(c => {
      const bull = parseInt(c.dataset.bull) || 0;
      const bear = parseInt(c.dataset.bear) || 0;
      const neut = parseInt(c.dataset.neut) || 0;
      _drawMiniPie(c, bull, bear, neut);
    });
  },
};

function _drawMiniPie(canvas, bull, bear, neut) {
  const ctx = canvas.getContext("2d");
  const total = bull + bear + neut || 1;
  const cx = 28, cy = 28, r = 12;
  const slices = [
    { val: bull, color: "#00e676" },
    { val: bear, color: "#ff1744" },
    { val: neut, color: "#546e7a" },
  ];

  let angle = -Math.PI / 2;
  for (const s of slices) {
    if (s.val === 0) continue;
    const sliceAngle = (s.val / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, angle, angle + sliceAngle);
    ctx.closePath();
    ctx.fillStyle = s.color;
    ctx.fill();
    angle += sliceAngle;
  }
}

// ── Debate Room ─────────────────────────────────────────────

const DebateRoom = {
  _entries: [],
  _maxEntries: 50,

  init() {
    document.addEventListener("agent:voted", (e) => this._addVote(e.detail));
    document.addEventListener("cycle:started", () => this._clear());
    document.addEventListener("state:full", (e) => {
      // Rebuild from existing votes
      this._clear();
      const votes = e.detail.votes || {};
      for (const [id, v] of Object.entries(votes)) {
        this._addVote(v, true);
      }
    });
  },

  _clear() {
    this._entries = [];
    const feed = document.getElementById("debate-feed");
    if (feed) feed.innerHTML = "";
    this._updateCount();
  },

  _addVote(d, silent) {
    const dir = (d.direction || "NEUTRAL").toUpperCase();
    const dirEmoji = dir === "BULL" ? "\uD83D\uDFE2" : dir === "BEAR" ? "\uD83D\uDD34" : "\u26AA";
    const dirClass = dir === "BULL" ? "dir-bull" : dir === "BEAR" ? "dir-bear" : "dir-neutral";
    const flipped = d.changed_from ? true : false;
    const conv = d.conviction || 0;
    const name = d.agent_name || d.agent_id || "?";
    const reasoning = d.reasoning || d.trade_idea || "";
    const roundNum = d.round_num || SwarmState.current_round || "?";
    const reasoningText = reasoning.length > 120 ? reasoning.slice(0, 117) + "..." : reasoning;

    const entry = {
      roundNum, dirEmoji, dirClass, flipped, name, conv, reasoningText, dir
    };
    this._entries.push(entry);
    if (this._entries.length > this._maxEntries) this._entries.shift();

    const feed = document.getElementById("debate-feed");
    if (!feed) return;

    const el = document.createElement("div");
    el.className = "debate-entry " + dirClass;
    if (!silent) el.style.animation = "debate-slide .3s ease-out";

    el.innerHTML = `
      <span class="debate-round">R${_esc(String(roundNum))}</span>
      <span class="debate-dir">${dirEmoji}</span>
      ${flipped ? '<span class="debate-flip">&#8634;</span>' : ''}
      <span class="debate-name">${_esc(name)}</span>
      <span class="debate-conv">(${conv}%)</span>
      <span class="debate-text">${_esc(reasoningText)}</span>
    `;

    feed.appendChild(el);

    // Auto-scroll to bottom
    feed.scrollTop = feed.scrollHeight;

    // Prune DOM
    while (feed.children.length > this._maxEntries) {
      feed.removeChild(feed.firstChild);
    }

    this._updateCount();
  },

  _updateCount() {
    const el = document.getElementById("debate-count");
    if (el) el.textContent = this._entries.length + " votes";
  },
};

// ── Activity Log ────────────────────────────────────────────

const ActivityLog = {
  _max: 80,

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
        return `${d.agent_name} [${d.tribe}] -> ${d.direction} (${d.conviction}%)${flip}`;
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
      case "outcome_resolved":
        return `Signal #${d.signal_id} ${d.direction} → ${(d.outcome||"").toUpperCase()} ${d.outcome_pct >= 0 ? "+" : ""}${parseFloat(d.outcome_pct||0).toFixed(2)}%`;
      case "engine_error":        return d.message || "Unknown error";
      default:                    return JSON.stringify(d).slice(0, 120);
    }
  },
};

// ── Signal History ───────────────────────────────────────────

const SignalHistory = {
  _loaded: false,

  init() {
    // Fetch on connect and after each cycle
    document.addEventListener("ws:connected", () => this.fetch());
    document.addEventListener("cycle:completed", () => this.fetch());
  },

  async fetch() {
    try {
      const [sigRes, statRes] = await Promise.all([
        fetch("/api/signals"),
        fetch("/api/stats"),
      ]);
      if (sigRes.ok) {
        const { signals } = await sigRes.json();
        this._renderTable(signals || []);
      }
      if (statRes.ok) {
        const stats = await statRes.json();
        this._renderStats(stats);
      }
    } catch (e) {
      console.error("Signal fetch error:", e);
    }
  },

  _renderStats(s) {
    const el = document.getElementById("signals-stat");
    if (!el) return;
    if (s.resolved > 0) {
      el.textContent = `${s.win_rate.toFixed(0)}% win | ${s.avg_pnl >= 0 ? "+" : ""}${s.avg_pnl}% avg | ${s.total} total`;
    } else {
      el.textContent = `${s.total} signals`;
    }
  },

  _renderTable(signals) {
    const tbody = document.getElementById("signals-tbody");
    if (!tbody) return;

    if (signals.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="dim mono" style="text-align:center;">No signals yet</td></tr>';
      return;
    }

    tbody.innerHTML = signals.map(s => {
      const ts = s.timestamp ? new Date(s.timestamp).toLocaleTimeString("en-US", {
        hour12: false, hour: "2-digit", minute: "2-digit"
      }) : "--";
      const dirClass = s.direction === "BULL" ? "bull" : s.direction === "BEAR" ? "bear" : "neut";
      const outcomeClass = s.outcome === "win" ? "bull"
                         : s.outcome === "loss" ? "bear"
                         : s.outcome === "scratch" ? "accent" : "dim";
      const pnl = s.outcome !== "pending" && s.outcome_pct != null
                ? (s.outcome_pct >= 0 ? "+" : "") + s.outcome_pct.toFixed(2) + "%"
                : "--";
      const entry = s.spx_entry_price ? s.spx_entry_price.toFixed(2) : "--";
      const conf = s.confidence != null ? s.confidence.toFixed(0) + "%" : "--";

      return `<tr>
        <td class="mono">${_esc(ts)}</td>
        <td class="${dirClass}">${_esc(s.direction || "--")}</td>
        <td class="mono">${_esc(conf)}</td>
        <td class="mono">${_esc(entry)}</td>
        <td class="${outcomeClass}">${_esc((s.outcome || "pending").toUpperCase())}</td>
        <td class="mono ${outcomeClass}">${_esc(pnl)}</td>
      </tr>`;
    }).join("");
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
  DebateRoom.init();
  ActivityLog.init();
  SignalHistory.init();
});
