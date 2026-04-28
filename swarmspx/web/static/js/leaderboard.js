/* ============================================================
   SwarmSPX — Agent ELO Leaderboard Panel
   Fetches /api/leaderboard, renders ranked rows with hot/cold
   color-coded ELO bars. Emits leaderboard:updated so AgentNetwork
   can scale node sizes by ELO.
   ============================================================ */

"use strict";

const Leaderboard = (() => {

  const DEFAULT_ELO = 1000;

  // Tribe colours match agent_network.js
  const TRIBE_COL = {
    technical:   "#448aff",
    macro:       "#ab47bc",
    sentiment:   "#ff7043",
    strategists: "#26c6da",
  };

  // Map agent_id → tribe
  const AGENT_TRIBE = {
    vwap_victor: "technical",    gamma_gary: "technical",
    delta_dawn: "technical",     momentum_mike: "technical",
    level_lucy: "technical",     tick_tina: "technical",
    fed_fred: "macro",           flow_fiona: "macro",
    vix_vinny: "macro",          gex_gina: "macro",
    putcall_pete: "macro",       breadth_brad: "macro",
    twitter_tom: "sentiment",    contrarian_carl: "sentiment",
    fear_felicia: "sentiment",   news_nancy: "sentiment",
    retail_ray: "sentiment",     whale_wanda: "sentiment",
    calendar_cal: "strategists", spread_sam: "strategists",
    scalp_steve: "strategists",  swing_sarah: "strategists",
    risk_rick: "strategists",    synthesis_syd: "strategists",
  };

  const AGENT_NAMES = {
    vwap_victor: "VWAP Victor",      gamma_gary: "Gamma Gary",
    delta_dawn: "Delta Dawn",        momentum_mike: "Momentum Mike",
    level_lucy: "Level Lucy",        tick_tina: "Tick Tina",
    fed_fred: "Fed Fred",            flow_fiona: "Flow Fiona",
    vix_vinny: "VIX Vinny",          gex_gina: "GEX Gina",
    putcall_pete: "Put-Call Pete",   breadth_brad: "Breadth Brad",
    twitter_tom: "Twitter Tom",      contrarian_carl: "Contrarian Carl",
    fear_felicia: "Fear Felicia",    news_nancy: "News Nancy",
    retail_ray: "Retail Ray",        whale_wanda: "Whale Wanda",
    calendar_cal: "Calendar Cal",    spread_sam: "Spread Sam",
    scalp_steve: "Scalp Steve",      swing_sarah: "Swing Sarah",
    risk_rick: "Risk Rick",          synthesis_syd: "Synthesis Syd",
  };

  // ── State ──────────────────────────────────────────────────
  let _visible  = false;
  let _data     = [];
  let _regime   = "";
  let _loading  = false;
  const _eloMap = {};

  // ── Init ───────────────────────────────────────────────────
  function init() {
    const toggleBtn  = document.getElementById("lb-toggle-btn");
    const closeBtn   = document.getElementById("lb-close-btn");
    const refreshBtn = document.getElementById("lb-refresh-btn");
    const regSel     = document.getElementById("lb-regime-filter");

    if (toggleBtn)  toggleBtn.addEventListener("click",  () => _toggle());
    if (closeBtn)   closeBtn.addEventListener("click",   () => _hide());
    if (refreshBtn) refreshBtn.addEventListener("click", () => _fetch());
    if (regSel) {
      regSel.addEventListener("change", (e) => {
        _regime = e.target.value;
        _fetch();
      });
    }

    // Auto-refresh leaderboard after a cycle finishes
    document.addEventListener("cycle:completed", () => {
      if (_visible) _fetch();
    });

    // Populate ELO map silently on connect (so node sizes are scaled from start)
    document.addEventListener("ws:connected", () => _fetch());
  }

  // ── Visibility ─────────────────────────────────────────────
  function _toggle() { if (_visible) _hide(); else _show(); }

  function _show() {
    _visible = true;
    const panel = document.getElementById("panel-leaderboard");
    const btn   = document.getElementById("lb-toggle-btn");
    if (panel) panel.classList.add("visible");
    if (btn)   btn.classList.add("active");
    if (_data.length === 0 && !_loading) _fetch();
  }

  function _hide() {
    _visible = false;
    const panel = document.getElementById("panel-leaderboard");
    const btn   = document.getElementById("lb-toggle-btn");
    if (panel) panel.classList.remove("visible");
    if (btn)   btn.classList.remove("active");
  }

  // ── Data fetch ─────────────────────────────────────────────
  async function _fetch() {
    if (_loading) return;
    _loading = true;
    if (_visible) _renderLoading();

    try {
      const qs  = _regime ? "?regime=" + encodeURIComponent(_regime) : "";
      const res = await window.fetch("/api/leaderboard" + qs);
      if (!res.ok) throw new Error("HTTP " + res.status);
      const body = await res.json();
      _data = body.agents || [];

      // Update shared ELO map
      for (const row of _data) _eloMap[row.agent_id] = row.elo;

      if (_visible) _renderRows();

      // Notify AgentNetwork so node sizes update
      document.dispatchEvent(new CustomEvent("leaderboard:updated", {
        detail: { eloMap: Object.assign({}, _eloMap) },
      }));
    } catch (e) {
      console.error("[Leaderboard] fetch error:", e);
      if (_visible) _renderError();
    } finally {
      _loading = false;
    }
  }

  // ── Render helpers ─────────────────────────────────────────
  function _renderLoading() {
    const rows = document.getElementById("lb-rows");
    if (!rows) return;
    rows.innerHTML = [
      '<div class="lb-loading">',
      '<div class="skeleton skeleton-line" style="width:90%"></div>',
      '<div class="skeleton skeleton-line" style="width:75%"></div>',
      '<div class="skeleton skeleton-line" style="width:82%"></div>',
      '<div class="skeleton skeleton-line" style="width:68%"></div>',
      '<div class="skeleton skeleton-line" style="width:88%"></div>',
      '</div>',
    ].join("");
  }

  function _renderError() {
    const rows = document.getElementById("lb-rows");
    if (rows) rows.innerHTML = '<div class="lb-empty bear">Failed to load leaderboard</div>';
  }

  function _renderRows() {
    const rows = document.getElementById("lb-rows");
    const stat = document.getElementById("lb-stat");
    if (!rows) return;

    if (!_data.length) {
      rows.innerHTML = '<div class="lb-empty">No agent data yet — run a cycle first</div>';
      return;
    }

    const display = _data.slice(0, 24);
    const elos    = display.map(r => r.elo);
    const maxElo  = Math.max(...elos, 1200);
    const minElo  = Math.min(...elos, 850);
    const eloRng  = maxElo - minElo || 1;

    let html = [
      '<div class="lb-header-row">',
      '<span>#</span>',
      '<span>Agent</span>',
      '<span>ELO Bar</span>',
      '<span style="text-align:right;">ELO</span>',
      '<span style="text-align:right;">Win%</span>',
      '</div>',
    ].join("");

    display.forEach((row, idx) => {
      const rank    = idx + 1;
      const rkCls   = rank <= 3 ? "rank-" + rank : "";
      const topCls  = rank <= 3 ? "lb-top-3" : "";
      const tribe   = AGENT_TRIBE[row.agent_id] || "technical";
      const tCol    = TRIBE_COL[tribe] || "#40c4ff";
      const name    = AGENT_NAMES[row.agent_id] || row.agent_id;
      const barPct  = Math.max(4, ((row.elo - minElo) / eloRng) * 100).toFixed(1);
      const barCol  = _barColor(row.elo);
      const eCls    = _eloClass(row.elo);
      const wr      = row.total_signals > 0 ? row.win_rate.toFixed(0) + "%" : "--";
      const tip     = _esc(name) + " · ELO " + row.elo + " · " + row.wins + "W/" + row.losses + "L";

      html += [
        '<div class="lb-row ' + topCls + '" title="' + tip + '">',
        '<span class="lb-rank ' + rkCls + '">' + rank + '</span>',
        '<div class="lb-agent-info">',
        '<div class="lb-agent-name" style="color:' + tCol + '">' + _esc(name) + '</div>',
        '<div class="lb-agent-tribe">' + tribe + '</div>',
        '</div>',
        '<div class="lb-bar-cell">',
        '<div class="lb-bar-bg">',
        '<div class="lb-bar-fill" style="width:' + barPct + '%;background:' + barCol + ';"></div>',
        '</div></div>',
        '<span class="lb-elo ' + eCls + '">' + row.elo.toFixed(0) + '</span>',
        '<span class="lb-winrate">' + wr + '</span>',
        '</div>',
      ].join("");
    });

    rows.innerHTML = html;

    if (stat) {
      stat.textContent = display.length + " agents · " + (_regime || "all regimes");
    }
  }

  // ── ELO → visual helpers ───────────────────────────────────

  function _eloClass(elo) {
    if (elo >= 1050) return "elo-hot";
    if (elo >= 1010) return "elo-warm";
    if (elo >= 990)  return "elo-cool";
    return "elo-cold";
  }

  // Smooth gradient: cold red (#ff1744) → neutral (#546e7a) → hot green (#00e676)
  function _barColor(elo) {
    if (elo >= DEFAULT_ELO) {
      const t = Math.min(1, (elo - DEFAULT_ELO) / 100);
      const r = Math.round(0x54 + (0x00 - 0x54) * t);
      const g = Math.round(0x6e + (0xe6 - 0x6e) * t);
      const b = Math.round(0x7a + (0x76 - 0x7a) * t);
      return "rgb(" + r + "," + g + "," + b + ")";
    } else {
      const t = Math.min(1, (DEFAULT_ELO - elo) / 100);
      const r = Math.round(0x54 + (0xff - 0x54) * t);
      const g = Math.round(0x6e + (0x17 - 0x6e) * t);
      const b = Math.round(0x7a + (0x44 - 0x7a) * t);
      return "rgb(" + r + "," + g + "," + b + ")";
    }
  }

  function _esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  // ── Public ─────────────────────────────────────────────────
  return {
    init,
    fetch: _fetch,
    show: _show,
    hide: _hide,
    getEloMap: () => Object.assign({}, _eloMap),
  };
})();

document.addEventListener("DOMContentLoaded", () => {
  Leaderboard.init();
});
