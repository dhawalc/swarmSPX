/* ============================================================
   SwarmSPX — Agent Network Canvas Visualization
   24 agents in 4 tribal clusters, animated with votes
   ============================================================ */

"use strict";

const AgentNetwork = (() => {
  // ── Agent definitions ───────────────────────────────────
  const TRIBES = {
    technical: {
      label: "TECHNICAL",
      color: "#448aff",
      agents: ["vwap_victor","gamma_gary","delta_dawn","momentum_mike","level_lucy","tick_tina"],
      names:  ["VWAP Victor","Gamma Gary","Delta Dawn","Momentum Mike","Level Lucy","Tick Tina"],
    },
    macro: {
      label: "MACRO",
      color: "#ab47bc",
      agents: ["fed_fred","flow_fiona","vix_vinny","gex_gina","putcall_pete","breadth_brad"],
      names:  ["Fed Fred","Flow Fiona","VIX Vinny","GEX Gina","PutCall Pete","Breadth Brad"],
    },
    sentiment: {
      label: "SENTIMENT",
      color: "#ff7043",
      agents: ["twitter_tom","contrarian_carl","fear_felicia","news_nancy","retail_ray","whale_wanda"],
      names:  ["Twitter Tom","Contrarian Carl","Fear Felicia","News Nancy","Retail Ray","Whale Wanda"],
    },
    strategists: {
      label: "STRATEGISTS",
      color: "#26c6da",
      agents: ["calendar_cal","spread_sam","scalp_steve","swing_sarah","risk_rick","synthesis_syd"],
      names:  ["Calendar Cal","Spread Sam","Scalp Steve","Swing Sarah","Risk Rick","Synthesis Syd"],
    },
  };

  const DIR_COLORS = {
    BULL: "#00e676", bull: "#00e676",
    BEAR: "#ff1744", bear: "#ff1744",
    NEUTRAL: "#78909c", neutral: "#78909c",
  };

  // ── State ───────────────────────────────────────────────
  let canvas, ctx;
  let W, H, dpr;
  let nodes = [];       // { id, name, tribe, tribeColor, x, y, tx, ty, r, dir, conv, glow, ring, ringTime, initial }
  let animId = null;
  let time = 0;

  // ── Init ────────────────────────────────────────────────
  function init() {
    canvas = document.getElementById("agent-canvas");
    if (!canvas) return;
    ctx = canvas.getContext("2d");

    _resize();
    _buildNodes();
    _listen();
    _loop();

    window.addEventListener("resize", () => { _resize(); _layoutNodes(); });
  }

  function _resize() {
    const wrap = canvas.parentElement;
    dpr = window.devicePixelRatio || 1;
    W = wrap.clientWidth;
    H = wrap.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function _buildNodes() {
    nodes = [];
    for (const [tribe, info] of Object.entries(TRIBES)) {
      for (let i = 0; i < info.agents.length; i++) {
        nodes.push({
          id: info.agents[i],
          name: info.names[i],
          tribe,
          tribeColor: info.color,
          x: 0, y: 0, tx: 0, ty: 0,
          r: 16,
          dir: "NEUTRAL",
          conv: 5,
          glow: 0,
          ring: false,
          ringTime: 0,
          initial: info.names[i].split(" ").map(w => w[0]).join(""),
        });
      }
    }
    _layoutNodes();
  }

  function _layoutNodes() {
    const cx = W / 2;
    const cy = H / 2;
    const orbitR = Math.min(W, H) * 0.32;
    const clusterR = Math.min(W, H) * 0.12;

    // Compass positions: technical=top, macro=right, sentiment=bottom, strategists=left
    const positions = {
      technical:   { angle: -Math.PI / 2 },
      macro:       { angle: 0 },
      sentiment:   { angle: Math.PI / 2 },
      strategists: { angle: Math.PI },
    };

    for (const node of nodes) {
      const pos = positions[node.tribe];
      const tribeCx = cx + orbitR * Math.cos(pos.angle);
      const tribeCy = cy + orbitR * Math.sin(pos.angle);

      const tribeNodes = nodes.filter(n => n.tribe === node.tribe);
      const idx = tribeNodes.indexOf(node);
      const a = (idx / tribeNodes.length) * Math.PI * 2 - Math.PI / 2;
      node.tx = tribeCx + clusterR * Math.cos(a);
      node.ty = tribeCy + clusterR * Math.sin(a);

      // Init position
      if (node.x === 0 && node.y === 0) {
        node.x = node.tx;
        node.y = node.ty;
      }
    }
  }

  // ── Events ──────────────────────────────────────────────
  function _listen() {
    document.addEventListener("agent:voted", (e) => {
      const d = e.detail;
      const node = nodes.find(n => n.id === d.agent_id);
      if (!node) return;
      const oldDir = node.dir;
      node.dir = (d.direction || "NEUTRAL").toUpperCase();
      node.conv = d.conviction || 5;
      node.glow = 1.0;
      if (d.changed_from && d.changed_from.toUpperCase() !== node.dir) {
        node.ring = true;
        node.ringTime = 0;
      }
    });

    document.addEventListener("state:full", (e) => {
      const votes = e.detail.votes || {};
      for (const [id, v] of Object.entries(votes)) {
        const node = nodes.find(n => n.id === id);
        if (!node) continue;
        node.dir = (v.direction || "NEUTRAL").toUpperCase();
        node.conv = v.conviction || 5;
      }
    });

    document.addEventListener("cycle:started", () => {
      for (const n of nodes) {
        n.dir = "NEUTRAL";
        n.conv = 5;
        n.glow = 0;
        n.ring = false;
      }
    });
  }

  // ── Render Loop ─────────────────────────────────────────
  function _loop() {
    time += 0.016;
    _update();
    _draw();
    animId = requestAnimationFrame(_loop);
  }

  function _update() {
    for (const n of nodes) {
      // Smooth move to target
      n.x += (n.tx - n.x) * 0.08;
      n.y += (n.ty - n.y) * 0.08;

      // Radius based on conviction (5 = default, 10 = max)
      const targetR = 12 + (n.conv / 10) * 14;
      n.r += (targetR - n.r) * 0.1;

      // Glow decay
      if (n.glow > 0) n.glow *= 0.97;
      if (n.glow < 0.01) n.glow = 0;

      // Ring animation
      if (n.ring) {
        n.ringTime += 0.02;
        if (n.ringTime > 1) n.ring = false;
      }
    }
  }

  function _draw() {
    ctx.clearRect(0, 0, W, H);

    // Background grid dots
    _drawGrid();

    // Connection lines between agreeing agents
    _drawConnections();

    // Tribe labels
    _drawTribeLabels();

    // Nodes
    for (const n of nodes) {
      _drawNode(n);
    }
  }

  function _drawGrid() {
    ctx.fillStyle = "rgba(30,30,46,0.3)";
    const step = 40;
    for (let x = step; x < W; x += step) {
      for (let y = step; y < H; y += step) {
        ctx.beginPath();
        ctx.arc(x, y, 0.8, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  function _drawConnections() {
    // Only draw connections within same tribe that agree on direction
    for (const [tribe, info] of Object.entries(TRIBES)) {
      const tribeNodes = nodes.filter(n => n.tribe === tribe);
      for (let i = 0; i < tribeNodes.length; i++) {
        for (let j = i + 1; j < tribeNodes.length; j++) {
          const a = tribeNodes[i], b = tribeNodes[j];
          if (a.dir === b.dir && a.dir !== "NEUTRAL") {
            const col = DIR_COLORS[a.dir] || "#78909c";
            const alpha = 0.08 + Math.min(a.conv, b.conv) / 10 * 0.12;
            ctx.strokeStyle = _hex2rgba(col, alpha);
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }
    }

    // Cross-tribe connections for strong agreement (conviction >= 7)
    const strong = nodes.filter(n => n.conv >= 7 && n.dir !== "NEUTRAL");
    for (let i = 0; i < strong.length; i++) {
      for (let j = i + 1; j < strong.length; j++) {
        if (strong[i].tribe === strong[j].tribe) continue;
        if (strong[i].dir !== strong[j].dir) continue;
        const col = DIR_COLORS[strong[i].dir];
        ctx.strokeStyle = _hex2rgba(col, 0.04);
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        ctx.moveTo(strong[i].x, strong[i].y);
        ctx.lineTo(strong[j].x, strong[j].y);
        ctx.stroke();
      }
    }
  }

  function _drawTribeLabels() {
    const cx = W / 2;
    const cy = H / 2;
    const orbitR = Math.min(W, H) * 0.32;
    const positions = {
      technical:   -Math.PI / 2,
      macro:       0,
      sentiment:   Math.PI / 2,
      strategists: Math.PI,
    };

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = "600 9px " + getComputedStyle(document.body).fontFamily;

    for (const [tribe, info] of Object.entries(TRIBES)) {
      const a = positions[tribe];
      const lx = cx + orbitR * Math.cos(a);
      const ly = cy + orbitR * Math.sin(a);
      ctx.fillStyle = _hex2rgba(info.color, 0.35);
      ctx.fillText(info.label, lx, ly);
    }
  }

  function _drawNode(n) {
    const col = DIR_COLORS[n.dir] || "#78909c";

    // Glow / pulse
    if (n.glow > 0.05) {
      const gr = ctx.createRadialGradient(n.x, n.y, n.r, n.x, n.y, n.r * 2.5);
      gr.addColorStop(0, _hex2rgba(col, n.glow * 0.4));
      gr.addColorStop(1, _hex2rgba(col, 0));
      ctx.fillStyle = gr;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r * 2.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Ring animation (direction flip)
    if (n.ring) {
      const rr = n.r + n.ringTime * 30;
      const alpha = 1 - n.ringTime;
      ctx.strokeStyle = _hex2rgba(col, alpha * 0.6);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(n.x, n.y, rr, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Idle breathing
    const breathe = Math.sin(time * 1.5 + nodes.indexOf(n) * 0.5) * 1.5;
    const drawR = n.r + breathe;

    // Main circle - gradient
    const grad = ctx.createRadialGradient(n.x - drawR * 0.3, n.y - drawR * 0.3, 0, n.x, n.y, drawR);
    grad.addColorStop(0, _hex2rgba(col, 0.35));
    grad.addColorStop(1, _hex2rgba(col, 0.12));
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(n.x, n.y, drawR, 0, Math.PI * 2);
    ctx.fill();

    // Border
    ctx.strokeStyle = _hex2rgba(col, 0.5 + n.glow * 0.5);
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Initial text
    ctx.fillStyle = _hex2rgba(col, 0.85);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const fontSize = Math.max(8, drawR * 0.7);
    ctx.font = `700 ${fontSize}px ${getComputedStyle(document.body).getPropertyValue('--font-mono') || 'monospace'}`;
    ctx.fillText(n.initial, n.x, n.y);

    // Conviction indicator - small bar under node
    const barW = drawR * 1.4;
    const barH = 2.5;
    const barX = n.x - barW / 2;
    const barY = n.y + drawR + 5;
    ctx.fillStyle = "rgba(30,30,46,0.6)";
    ctx.fillRect(barX, barY, barW, barH);
    ctx.fillStyle = _hex2rgba(col, 0.6);
    ctx.fillRect(barX, barY, barW * (n.conv / 10), barH);
  }

  // ── Utils ───────────────────────────────────────────────
  function _hex2rgba(hex, alpha) {
    const r = parseInt(hex.slice(1,3), 16);
    const g = parseInt(hex.slice(3,5), 16);
    const b = parseInt(hex.slice(5,7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  // ── Public ──────────────────────────────────────────────
  return { init };
})();

document.addEventListener("DOMContentLoaded", () => {
  AgentNetwork.init();
});
