/* ============================================================
   SwarmSPX — Neural Agent Network Canvas Visualization
   24 agents in 4 tribal diamond clusters with neural connections,
   data particles, thought bubbles, shockwaves, and ambient effects
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
      abbr:   ["VV","GG","DD","MM","LL","TT"],
    },
    macro: {
      label: "MACRO",
      color: "#ab47bc",
      agents: ["fed_fred","flow_fiona","vix_vinny","gex_gina","putcall_pete","breadth_brad"],
      names:  ["Fed Fred","Flow Fiona","VIX Vinny","GEX Gina","PutCall Pete","Breadth Brad"],
      abbr:   ["FF","FF","VV","GG","PP","BB"],
    },
    sentiment: {
      label: "SENTIMENT",
      color: "#ff7043",
      agents: ["twitter_tom","contrarian_carl","fear_felicia","news_nancy","retail_ray","whale_wanda"],
      names:  ["Twitter Tom","Contrarian Carl","Fear Felicia","News Nancy","Retail Ray","Whale Wanda"],
      abbr:   ["TT","CC","FF","NN","RR","WW"],
    },
    strategists: {
      label: "STRATEGISTS",
      color: "#26c6da",
      agents: ["calendar_cal","spread_sam","scalp_steve","swing_sarah","risk_rick","synthesis_syd"],
      names:  ["Calendar Cal","Spread Sam","Scalp Steve","Swing Sarah","Risk Rick","Synthesis Syd"],
      abbr:   ["CC","SS","SS","SS","RR","SS"],
    },
  };

  const DIR_COLORS = {
    BULL: "#00e676", bull: "#00e676",
    BEAR: "#ff1744", bear: "#ff1744",
    NEUTRAL: "#37474f", neutral: "#37474f",
  };

  // ── Agent Metadata for hover cards (Upgrade 2) ─────────
  const AGENT_META = {
    vwap_victor: { name: "VWAP Victor", tribe: "Technical", strategy: "Mean reversion to VWAP" },
    gamma_gary: { name: "Gamma Gary", tribe: "Technical", strategy: "Gamma exposure hedging" },
    delta_dawn: { name: "Delta Dawn", tribe: "Technical", strategy: "Delta-neutral scalping" },
    momentum_mike: { name: "Momentum Mike", tribe: "Technical", strategy: "Breakout & trend following" },
    level_lucy: { name: "Level Lucy", tribe: "Technical", strategy: "Support & resistance" },
    tick_tina: { name: "Tick Tina", tribe: "Technical", strategy: "Market internals (TICK, TRIN)" },
    fed_fred: { name: "Fed Fred", tribe: "Macro", strategy: "FOMC & rates policy" },
    flow_fiona: { name: "Flow Fiona", tribe: "Macro", strategy: "Dark pool & options flow" },
    vix_vinny: { name: "VIX Vinny", tribe: "Macro", strategy: "Volatility regime timing" },
    gex_gina: { name: "GEX Gina", tribe: "Macro", strategy: "Gamma exposure levels" },
    putcall_pete: { name: "Put-Call Pete", tribe: "Macro", strategy: "Put/call ratio sentiment" },
    breadth_brad: { name: "Breadth Brad", tribe: "Macro", strategy: "Market breadth & internals" },
    twitter_tom: { name: "Twitter Tom", tribe: "Sentiment", strategy: "Social media sentiment" },
    contrarian_carl: { name: "Contrarian Carl", tribe: "Sentiment", strategy: "Fade the crowd" },
    fear_felicia: { name: "Fear Felicia", tribe: "Sentiment", strategy: "Fear & greed mean reversion" },
    news_nancy: { name: "News Nancy", tribe: "Sentiment", strategy: "Breaking news & event-driven" },
    retail_ray: { name: "Retail Ray", tribe: "Sentiment", strategy: "Fade retail flow" },
    whale_wanda: { name: "Whale Wanda", tribe: "Sentiment", strategy: "Large block detection" },
    calendar_cal: { name: "Calendar Cal", tribe: "Strategists", strategy: "Time decay & expiry dynamics" },
    spread_sam: { name: "Spread Sam", tribe: "Strategists", strategy: "Defined-risk spreads" },
    scalp_steve: { name: "Scalp Steve", tribe: "Strategists", strategy: "1-5 minute scalping" },
    swing_sarah: { name: "Swing Sarah", tribe: "Strategists", strategy: "1-4 hour swings" },
    risk_rick: { name: "Risk Rick", tribe: "Strategists", strategy: "Position sizing & risk mgmt" },
    synthesis_syd: { name: "Synthesis Syd", tribe: "Strategists", strategy: "Cross-tribe consensus" },
  };

  // Short name for under-node label (e.g. "VWAP Victor" -> "VWAP V.")
  function _shortName(fullName) {
    const parts = fullName.split(" ");
    if (parts.length < 2) return fullName;
    return parts[0].toUpperCase() + " " + parts[1][0] + ".";
  }

  // ── State ───────────────────────────────────────────────
  let canvas, ctx;
  let W, H, dpr;
  let nodes = [];
  let particles = [];       // Background ambient particles
  let dataParticles = [];   // Particles flowing along connections
  let thoughtBubbles = [];  // Floating text near agents
  let shockwaves = [];      // Round-complete shockwave effects
  let time = 0;
  let lastTime = 0;

  // ELO map from leaderboard: {agent_id: elo}
  let _eloMap = {};

  // Consensus climax state (Upgrade 1)
  let consensusFlash = { active: false, alpha: 0, color: "#ffffff" };
  let consensusGlow = { active: false, alpha: 0, color: "#ffffff" };
  let particleSpeedMult = 1;

  // Hover state (Upgrade 2)
  let hoveredNode = null;
  let hoverCardEl = null;

  // Cinematic state (Upgrade 3)
  let isCinematic = false;

  // Performance: cached dot grid + idle throttle
  let dotGridCanvas = null;
  let dirty = true;       // force redraw when state changes
  let idleFrameSkip = 0;  // skip frames when idle
  let hoverThrottleTime = 0;

  // ── Init ────────────────────────────────────────────────
  function init(canvasId) {
    canvas = document.getElementById(canvasId || "agent-canvas");
    if (!canvas) return;
    ctx = canvas.getContext("2d");

    _resize();
    _buildNodes();
    _initAmbientParticles();
    _listen();
    _initHoverCard();
    _initCinematicMode();
    lastTime = performance.now();
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
    _buildDotGridCache();
    dirty = true;
  }

  function _buildDotGridCache() {
    dotGridCanvas = document.createElement("canvas");
    dotGridCanvas.width = W * dpr;
    dotGridCanvas.height = H * dpr;
    const dctx = dotGridCanvas.getContext("2d");
    dctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    dctx.fillStyle = "rgba(20, 20, 40, 0.25)";
    const step = 35;
    for (let x = step; x < W; x += step) {
      for (let y = step; y < H; y += step) {
        dctx.beginPath();
        dctx.arc(x, y, 0.6, 0, Math.PI * 2);
        dctx.fill();
      }
    }
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
          abbr: info.abbr[i],
          x: 0, y: 0, tx: 0, ty: 0,
          r: 24, tr: 24,
          dir: "NEUTRAL",
          prevDir: "NEUTRAL",
          conv: 0,
          targetConv: 0,
          glow: 0,
          ring: false,
          ringTime: 0,
          flipFlash: 0,
          breatheOffset: Math.random() * Math.PI * 2,
          reasoning: "",
        });
      }
    }
    _layoutNodes();
  }

  function _layoutNodes() {
    const cx = W / 2;
    const cy = H / 2;
    const orbitR = Math.min(W, H) * 0.30;
    const clusterR = Math.min(W, H) * 0.13;

    // Diamond: technical=top, macro=right, sentiment=bottom, strategists=left
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

      if (node.x === 0 && node.y === 0) {
        node.x = node.tx;
        node.y = node.ty;
      }
    }
  }

  // ── Ambient Particles ──────────────────────────────────
  function _initAmbientParticles() {
    particles = [];
    const count = Math.floor((W * H) / 8000);
    for (let i = 0; i < count; i++) {
      particles.push({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.15,
        vy: (Math.random() - 0.5) * 0.15,
        size: Math.random() * 1.2 + 0.3,
        alpha: Math.random() * 0.15 + 0.03,
      });
    }
  }

  // ── Events ──────────────────────────────────────────────
  function _listen() {
    document.addEventListener("agent:voted", (e) => {
      dirty = true;
      const d = e.detail;
      const node = nodes.find(n => n.id === d.agent_id);
      if (!node) return;
      const oldDir = node.dir;
      node.dir = (d.direction || "NEUTRAL").toUpperCase();
      node.targetConv = d.conviction || 0;
      node.glow = 1.0;
      node.reasoning = d.reasoning || "";

      if (d.changed_from && d.changed_from.toUpperCase() !== node.dir) {
        node.ring = true;
        node.ringTime = 0;
        node.flipFlash = 1.0;
        node.prevDir = d.changed_from.toUpperCase();
      }

      // Thought bubble
      if (node.reasoning) {
        _addThoughtBubble(node);
      }
    });

    document.addEventListener("state:full", (e) => {
      dirty = true;
      const state = e.detail;
      const votes = state.votes || {};
      for (const [id, v] of Object.entries(votes)) {
        const node = nodes.find(n => n.id === id);
        if (!node) continue;
        node.dir = (v.direction || "NEUTRAL").toUpperCase();
        node.targetConv = v.conviction || 0;
      }
    });

    document.addEventListener("cycle:started", () => {
      dirty = true;
      for (const n of nodes) {
        n.dir = "NEUTRAL";
        n.targetConv = 0;
        n.glow = 0;
        n.ring = false;
        n.flipFlash = 0;
        n.reasoning = "";
      }
      thoughtBubbles = [];
      dataParticles = [];
    });

    document.addEventListener("round:completed", () => {
      dirty = true;
      shockwaves.push({ x: W / 2, y: H / 2, radius: 0, maxRadius: Math.max(W, H) * 0.6, alpha: 0.3 });
    });

    // ── UPGRADE 1: Consensus Climax ──────────────────────
    document.addEventListener("consensus:reached", (e) => {
      dirty = true;
      const d = e.detail || {};
      const dir = (d.direction || "").toUpperCase();
      const col = dir === "BULL" ? "#00e676" : dir === "BEAR" ? "#ff1744" : "#40c4ff";

      // MASSIVE shockwave that fills the entire canvas
      shockwaves.push({ x: W / 2, y: H / 2, radius: 0, maxRadius: Math.max(W, H) * 1.5, alpha: 0.6, color: col, lineWidth: 4 });
      // Second trailing shockwave
      setTimeout(() => {
        shockwaves.push({ x: W / 2, y: H / 2, radius: 0, maxRadius: Math.max(W, H) * 1.2, alpha: 0.4, color: "#ffffff", lineWidth: 2 });
      }, 150);

      // Flash the entire canvas background
      consensusFlash.active = true;
      consensusFlash.alpha = 0.35;
      consensusFlash.color = col;

      // All connections glow white then settle to consensus color
      consensusGlow.active = true;
      consensusGlow.alpha = 1.0;
      consensusGlow.color = col;

      // All nodes pulse outward with consensus color
      for (const n of nodes) {
        n.glow = 1.0;
        n.ring = true;
        n.ringTime = 0;
      }

      // Triple particle speed
      particleSpeedMult = 3.0;
    });

    // ELO leaderboard updates: scale node sizes + apply hot/cold tint
    document.addEventListener("leaderboard:updated", (e) => {
      dirty = true;
      _eloMap = (e.detail && e.detail.eloMap) ? e.detail.eloMap : {};
      _applyEloToNodes();
    });

    // ── UPGRADE 1: Trade card dramatic flash ─────────────
    document.addEventListener("tradecard:generated", (e) => {
      dirty = true;
      const d = e.detail || {};
      const dir = (d.direction || d.action || "").toUpperCase();
      const isBull = dir === "BULL" || dir === "BUY";
      const isBear = dir === "BEAR" || dir === "SELL";

      // Dramatic glow on trade card panel
      const tcEl = document.getElementById("trade-card");
      if (tcEl) {
        tcEl.classList.remove("tc-dramatic-flash-bull", "tc-dramatic-flash-bear", "tc-dramatic-flash");
        void tcEl.offsetWidth;
        tcEl.classList.add(isBull ? "tc-dramatic-flash-bull" : isBear ? "tc-dramatic-flash-bear" : "tc-dramatic-flash");
        setTimeout(() => tcEl.classList.remove("tc-dramatic-flash-bull", "tc-dramatic-flash-bear", "tc-dramatic-flash"), 1300);
      }

      // Secondary pulse on canvas
      shockwaves.push({ x: W * 0.8, y: H * 0.4, radius: 0, maxRadius: Math.max(W, H) * 0.5, alpha: 0.25, color: isBull ? "#00e676" : isBear ? "#ff1744" : "#40c4ff" });
    });
  }

  // ── Thought Bubbles ─────────────────────────────────────
  function _addThoughtBubble(node) {
    const text = node.reasoning.length > 60 ? node.reasoning.slice(0, 57) + "..." : node.reasoning;
    thoughtBubbles.push({
      x: node.x,
      y: node.y - node.r - 12,
      text,
      alpha: 1.0,
      life: 3.0,  // seconds
      offsetY: 0,
    });
    // Max 5 visible at once
    if (thoughtBubbles.length > 5) thoughtBubbles.shift();
  }

  // ── Render Loop ─────────────────────────────────────────
  function _loop(now) {
    now = now || performance.now();
    const dt = Math.min((now - lastTime) / 1000, 0.05); // cap at 50ms
    lastTime = now;
    time += dt;

    // Idle throttle: render at ~10fps when nothing is happening
    const isActive = dirty || shockwaves.length > 0 || dataParticles.length > 0 ||
                     thoughtBubbles.length > 0 || consensusFlash.active || consensusGlow.active ||
                     nodes.some(n => n.glow > 0.01 || n.ring || n.flipFlash > 0.01);
    if (!isActive) {
      idleFrameSkip++;
      if (idleFrameSkip < 6) { // skip 5 of 6 frames (~10fps)
        requestAnimationFrame(_loop);
        return;
      }
    }
    idleFrameSkip = 0;
    dirty = false;

    _update(dt);
    _draw();
    requestAnimationFrame(_loop);
  }

  function _update(dt) {
    for (const n of nodes) {
      // Smooth move
      n.x += (n.tx - n.x) * 0.06;
      n.y += (n.ty - n.y) * 0.06;

      // Smooth conviction
      n.conv += (n.targetConv - n.conv) * 0.08;

      // Target radius: ELO-scaled base (18-32) + conviction bonus (0-6)
      const eloBase = n.eloRadius || 24;
      n.tr = eloBase + (n.conv / 100) * 6;
      n.r += (n.tr - n.r) * 0.08;

      // Glow decay
      if (n.glow > 0) n.glow *= Math.pow(0.3, dt);
      if (n.glow < 0.01) n.glow = 0;

      // Flip flash decay
      if (n.flipFlash > 0) n.flipFlash *= Math.pow(0.15, dt);
      if (n.flipFlash < 0.01) n.flipFlash = 0;

      // Ring animation
      if (n.ring) {
        n.ringTime += dt * 1.5;
        if (n.ringTime > 1) n.ring = false;
      }
    }

    // Ambient particles (speed multiplied during consensus climax)
    for (const p of particles) {
      p.x += p.vx * particleSpeedMult;
      p.y += p.vy * particleSpeedMult;
      if (p.x < 0) p.x = W;
      if (p.x > W) p.x = 0;
      if (p.y < 0) p.y = H;
      if (p.y > H) p.y = 0;
    }

    // Decay particle speed multiplier back to 1
    if (particleSpeedMult > 1) {
      particleSpeedMult = 1 + (particleSpeedMult - 1) * Math.pow(0.3, dt);
      if (particleSpeedMult < 1.05) particleSpeedMult = 1;
    }

    // Consensus flash decay (Upgrade 1)
    if (consensusFlash.active) {
      consensusFlash.alpha *= Math.pow(0.08, dt);
      if (consensusFlash.alpha < 0.005) consensusFlash.active = false;
    }
    if (consensusGlow.active) {
      consensusGlow.alpha *= Math.pow(0.25, dt);
      if (consensusGlow.alpha < 0.005) consensusGlow.active = false;
    }

    // Data particles along connections
    _updateDataParticles(dt);

    // Thought bubbles
    for (let i = thoughtBubbles.length - 1; i >= 0; i--) {
      const tb = thoughtBubbles[i];
      tb.life -= dt;
      tb.alpha = Math.max(0, tb.life / 1.5);  // Fade out in last 1.5s
      tb.offsetY -= dt * 10;
      if (tb.life <= 0) thoughtBubbles.splice(i, 1);
    }

    // Shockwaves
    for (let i = shockwaves.length - 1; i >= 0; i--) {
      const sw = shockwaves[i];
      sw.radius += dt * 350;
      sw.alpha *= Math.pow(0.2, dt);
      if (sw.alpha < 0.005 || sw.radius > sw.maxRadius) shockwaves.splice(i, 1);
    }

    // Periodically spawn data particles
    if (Math.random() < dt * 3) {
      _spawnDataParticle();
    }
  }

  function _spawnDataParticle() {
    // Find two connected nodes (same tribe, same direction, or cross-tribe high conviction)
    const votedNodes = nodes.filter(n => n.dir !== "NEUTRAL" && n.conv > 20);
    if (votedNodes.length < 2) return;

    const a = votedNodes[Math.floor(Math.random() * votedNodes.length)];
    // Find a partner
    let candidates;
    if (Math.random() < 0.7) {
      // Same tribe
      candidates = votedNodes.filter(n => n !== a && n.tribe === a.tribe && n.dir === a.dir);
    } else {
      // Cross-tribe, same direction, high conviction
      candidates = votedNodes.filter(n => n !== a && n.tribe !== a.tribe && n.dir === a.dir && n.conv > 70);
    }
    if (candidates.length === 0) return;

    const b = candidates[Math.floor(Math.random() * candidates.length)];
    // Flow from higher conviction to lower
    const from = a.conv >= b.conv ? a : b;
    const to = a.conv >= b.conv ? b : a;
    const col = DIR_COLORS[from.dir] || "#37474f";

    dataParticles.push({
      fromX: from.x, fromY: from.y,
      toX: to.x, toY: to.y,
      progress: 0,
      speed: 0.4 + Math.random() * 0.4,
      color: col,
      size: 1.5 + Math.random(),
    });
  }

  function _updateDataParticles(dt) {
    for (let i = dataParticles.length - 1; i >= 0; i--) {
      const dp = dataParticles[i];
      dp.progress += dt * dp.speed;
      if (dp.progress >= 1) dataParticles.splice(i, 1);
    }
    // Limit
    if (dataParticles.length > 60) dataParticles.splice(0, dataParticles.length - 60);
  }

  // ── Draw ────────────────────────────────────────────────
  function _draw() {
    ctx.clearRect(0, 0, W, H);

    // Consensus flash background (Upgrade 1)
    if (consensusFlash.active && consensusFlash.alpha > 0.005) {
      ctx.save();
      ctx.fillStyle = _hex2rgba(consensusFlash.color, consensusFlash.alpha);
      ctx.fillRect(0, 0, W, H);
      ctx.restore();
    }

    _drawDotGrid();
    _drawAmbientParticles();
    _drawShockwaves();
    _drawConnections();
    _drawDataParticles();
    _drawTribeLabels();

    for (const n of nodes) {
      _drawNode(n);
    }

    _drawThoughtBubbles();

    // Network stat
    const voted = nodes.filter(n => n.dir !== "NEUTRAL").length;
    const statEl = document.getElementById("network-stat");
    if (statEl) statEl.textContent = voted + "/24 active";
  }

  function _drawDotGrid() {
    if (dotGridCanvas) {
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(dotGridCanvas, 0, 0);
      ctx.restore();
    }
  }

  function _drawAmbientParticles() {
    for (const p of particles) {
      ctx.globalAlpha = p.alpha;
      ctx.fillStyle = "#40c4ff";
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function _drawShockwaves() {
    for (const sw of shockwaves) {
      const col = sw.color || "#40c4ff";
      const lw = sw.lineWidth || 2;

      // Outer ring
      ctx.beginPath();
      ctx.arc(sw.x, sw.y, sw.radius, 0, Math.PI * 2);
      ctx.strokeStyle = _hex2rgba(col, sw.alpha);
      ctx.lineWidth = lw;
      ctx.stroke();

      // Inner glow ring (gradient, no shadowBlur)
      if (sw.radius > 4) {
        const innerR = Math.max(0, sw.radius - lw * 3);
        const grad = ctx.createRadialGradient(sw.x, sw.y, innerR, sw.x, sw.y, sw.radius);
        grad.addColorStop(0, _hex2rgba(col, 0));
        grad.addColorStop(0.7, _hex2rgba(col, 0));
        grad.addColorStop(1, _hex2rgba(col, sw.alpha * 0.2));
        ctx.beginPath();
        ctx.arc(sw.x, sw.y, sw.radius, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.fill();
      }
    }
  }

  function _drawConnections() {
    ctx.save();

    // Intra-tribe connections (ALL pairs within a tribe)
    for (const [tribe, info] of Object.entries(TRIBES)) {
      const tribeNodes = nodes.filter(n => n.tribe === tribe);
      for (let i = 0; i < tribeNodes.length; i++) {
        for (let j = i + 1; j < tribeNodes.length; j++) {
          const a = tribeNodes[i], b = tribeNodes[j];
          const bothVoted = a.dir !== "NEUTRAL" && b.dir !== "NEUTRAL";
          const agree = a.dir === b.dir;

          if (!bothVoted && a.dir === "NEUTRAL" && b.dir === "NEUTRAL") {
            // Both neutral: very faint line
            ctx.strokeStyle = "rgba(40, 40, 60, 0.12)";
            ctx.lineWidth = 0.5;
            ctx.setLineDash([]);
            ctx.shadowBlur = 0;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
            continue;
          }

          if (agree && bothVoted) {
            // Both same direction: glowing colored line
            const col = DIR_COLORS[a.dir];
            const avgConv = (a.conv + b.conv) / 200;
            ctx.strokeStyle = _hex2rgba(col, 0.15 + avgConv * 0.35);
            ctx.lineWidth = 1 + avgConv * 1.5;
            ctx.setLineDash([]);
            ctx.shadowBlur = 8 + avgConv * 12;
            ctx.shadowColor = col;
          } else if (bothVoted && !agree) {
            // Disagree: dim gray dashed
            ctx.strokeStyle = "rgba(60, 60, 80, 0.15)";
            ctx.lineWidth = 0.5;
            ctx.setLineDash([4, 6]);
            ctx.shadowBlur = 0;
          } else {
            // One voted, one neutral
            ctx.strokeStyle = "rgba(40, 40, 60, 0.1)";
            ctx.lineWidth = 0.5;
            ctx.setLineDash([]);
            ctx.shadowBlur = 0;
          }

          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }

    // Cross-tribe connections: same direction, conviction > 70
    ctx.setLineDash([]);
    const strong = nodes.filter(n => n.conv > 70 && n.dir !== "NEUTRAL");
    for (let i = 0; i < strong.length; i++) {
      for (let j = i + 1; j < strong.length; j++) {
        if (strong[i].tribe === strong[j].tribe) continue;
        if (strong[i].dir !== strong[j].dir) continue;
        const col = DIR_COLORS[strong[i].dir];
        const avgConv = (strong[i].conv + strong[j].conv) / 200;
        ctx.strokeStyle = _hex2rgba(col, 0.05 + avgConv * 0.1);
        ctx.lineWidth = 0.6;
        ctx.shadowBlur = 4;
        ctx.shadowColor = col;
        ctx.beginPath();
        ctx.moveTo(strong[i].x, strong[i].y);
        ctx.lineTo(strong[j].x, strong[j].y);
        ctx.stroke();
      }
    }

    // Consensus glow: briefly make ALL connections glow bright (Upgrade 1)
    if (consensusGlow.active && consensusGlow.alpha > 0.05) {
      ctx.setLineDash([]);
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          if (nodes[i].tribe !== nodes[j].tribe) continue;
          const glowCol = consensusGlow.alpha > 0.5 ? "#ffffff" : consensusGlow.color;
          ctx.strokeStyle = _hex2rgba(glowCol, consensusGlow.alpha * 0.3);
          ctx.lineWidth = 1.5 * consensusGlow.alpha;
          ctx.shadowBlur = 12 * consensusGlow.alpha;
          ctx.shadowColor = glowCol;
          ctx.beginPath();
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.stroke();
        }
      }
    }

    ctx.restore();
  }

  function _drawDataParticles() {
    for (const dp of dataParticles) {
      const x = dp.fromX + (dp.toX - dp.fromX) * dp.progress;
      const y = dp.fromY + (dp.toY - dp.fromY) * dp.progress;
      const alpha = Math.sin(dp.progress * Math.PI); // Fade in/out

      ctx.save();
      ctx.shadowBlur = 6;
      ctx.shadowColor = dp.color;
      ctx.fillStyle = _hex2rgba(dp.color, alpha * 0.8);
      ctx.beginPath();
      ctx.arc(x, y, dp.size, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }

  function _drawTribeLabels() {
    const cx = W / 2;
    const cy = H / 2;
    const orbitR = Math.min(W, H) * 0.30;
    const positions = {
      technical:   -Math.PI / 2,
      macro:       0,
      sentiment:   Math.PI / 2,
      strategists: Math.PI,
    };

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = "600 9px 'JetBrains Mono', monospace";

    for (const [tribe, info] of Object.entries(TRIBES)) {
      const a = positions[tribe];
      const lx = cx + orbitR * Math.cos(a);
      const ly = cy + orbitR * Math.sin(a);
      ctx.fillStyle = _hex2rgba(info.color, 0.2);
      ctx.fillText(info.label, lx, ly);
    }
  }

  // ── ELO Scaling ─────────────────────────────────────────
  function _applyEloToNodes() {
    const DEFAULT_ELO = 1000;
    const MIN_R = 18;  // minimum node radius at low ELO
    const MAX_R = 32;  // maximum node radius at high ELO

    for (const n of nodes) {
      const elo = _eloMap[n.id] || DEFAULT_ELO;
      // Map ELO 850-1150 → radius 18-32
      const t = Math.max(0, Math.min(1, (elo - 850) / 300));
      n.eloRadius = MIN_R + t * (MAX_R - MIN_R);
      n.elo = elo;

      // Hot/cold colour overlay alpha (shown as second fill layer)
      // elo > 1050: green tint;  elo < 950: red tint
      if (elo >= 1050) {
        n.eloTintColor = "#00e676";
        n.eloTintAlpha = Math.min(0.25, (elo - 1050) / 200);
      } else if (elo <= 950) {
        n.eloTintColor = "#ff1744";
        n.eloTintAlpha = Math.min(0.25, (950 - elo) / 200);
      } else {
        n.eloTintColor = null;
        n.eloTintAlpha = 0;
      }
    }
  }

  function _drawNode(n) {
    const col = DIR_COLORS[n.dir] || "#37474f";

    // Breathing animation (Upgrade 2: +-2px over 3s)
    const breathe = Math.sin(time * (Math.PI * 2 / 3) + n.breatheOffset) * 2;
    const drawR = n.r + breathe;

    // Conviction halo (radial gradient glow)
    if (n.conv > 10) {
      const haloR = drawR * (1.8 + (n.conv / 100) * 1.5);
      const haloAlpha = 0.05 + (n.conv / 100) * 0.15;
      const gr = ctx.createRadialGradient(n.x, n.y, drawR * 0.8, n.x, n.y, haloR);
      gr.addColorStop(0, _hex2rgba(col, haloAlpha));
      gr.addColorStop(1, _hex2rgba(col, 0));
      ctx.fillStyle = gr;
      ctx.beginPath();
      ctx.arc(n.x, n.y, haloR, 0, Math.PI * 2);
      ctx.fill();
    }

    // Vote glow pulse
    if (n.glow > 0.05) {
      ctx.save();
      ctx.shadowBlur = 25 * n.glow;
      ctx.shadowColor = col;
      const gr = ctx.createRadialGradient(n.x, n.y, drawR, n.x, n.y, drawR * 3);
      gr.addColorStop(0, _hex2rgba(col, n.glow * 0.5));
      gr.addColorStop(1, _hex2rgba(col, 0));
      ctx.fillStyle = gr;
      ctx.beginPath();
      ctx.arc(n.x, n.y, drawR * 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // Flip flash
    if (n.flipFlash > 0.05) {
      ctx.save();
      ctx.globalAlpha = n.flipFlash;
      ctx.fillStyle = "#ffffff";
      ctx.shadowBlur = 30;
      ctx.shadowColor = "#ffffff";
      ctx.beginPath();
      ctx.arc(n.x, n.y, drawR * 1.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // Ring animation (direction flip)
    if (n.ring) {
      const rr = drawR + n.ringTime * 40;
      const alpha = (1 - n.ringTime) * 0.7;
      ctx.strokeStyle = _hex2rgba(col, alpha);
      ctx.lineWidth = 2.5 * (1 - n.ringTime);
      ctx.beginPath();
      ctx.arc(n.x, n.y, rr, 0, Math.PI * 2);
      ctx.stroke();

      // Second ring, delayed
      if (n.ringTime > 0.2) {
        const rr2 = drawR + (n.ringTime - 0.2) * 40;
        const alpha2 = (1 - n.ringTime) * 0.4;
        ctx.strokeStyle = _hex2rgba(col, alpha2);
        ctx.lineWidth = 1.5 * (1 - n.ringTime);
        ctx.beginPath();
        ctx.arc(n.x, n.y, rr2, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    // ── UPGRADE 2: Premium Node Design ───────────────────

    // Outer dashed ring (slowly rotating)
    ctx.save();
    const outerR = drawR + 5;
    const dashRotation = time * 0.3 + n.breatheOffset;
    ctx.setLineDash([4, 4]);
    ctx.lineDashOffset = -dashRotation * outerR;
    ctx.strokeStyle = _hex2rgba(col, n.dir === "NEUTRAL" ? 0.12 : 0.3);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(n.x, n.y, outerR, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();

    // Inner solid ring
    ctx.strokeStyle = _hex2rgba(col, n.dir === "NEUTRAL" ? 0.2 : 0.5 + n.glow * 0.3);
    ctx.lineWidth = n.dir !== "NEUTRAL" ? 2 : 1;
    ctx.beginPath();
    ctx.arc(n.x, n.y, drawR + 1, 0, Math.PI * 2);
    ctx.stroke();

    // Main circle: radial gradient (bright center -> darker edge)
    const grad = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, drawR);
    if (n.dir === "NEUTRAL") {
      grad.addColorStop(0, "rgba(75, 91, 99, 0.4)");
      grad.addColorStop(1, "rgba(55, 71, 79, 0.1)");
    } else if (n.dir === "BULL") {
      grad.addColorStop(0, _hex2rgba("#00ff88", 0.55));
      grad.addColorStop(1, _hex2rgba("#004d29", 0.25));
    } else {
      grad.addColorStop(0, _hex2rgba("#ff4466", 0.55));
      grad.addColorStop(1, _hex2rgba("#4d0014", 0.25));
    }

    ctx.save();
    ctx.shadowBlur = n.dir !== "NEUTRAL" ? 12 : 0;
    ctx.shadowColor = col;
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(n.x, n.y, drawR, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    // ELO hot/cold tint overlay
    if (n.eloTintColor && n.eloTintAlpha > 0.005) {
      ctx.save();
      ctx.globalAlpha = n.eloTintAlpha;
      ctx.fillStyle = n.eloTintColor;
      ctx.beginPath();
      ctx.arc(n.x, n.y, drawR * 0.7, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.restore();
    }

    // Conviction ARC (glowing arc around node, like a loading spinner)
    if (n.conv > 5) {
      const arcR = drawR + 3;
      const arcAngle = (n.conv / 100) * Math.PI * 2;
      const startA = -Math.PI / 2;
      ctx.save();
      ctx.shadowBlur = 8;
      ctx.shadowColor = col;
      ctx.strokeStyle = _hex2rgba(col, 0.8);
      ctx.lineWidth = 2.5;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.arc(n.x, n.y, arcR, startA, startA + arcAngle);
      ctx.stroke();
      ctx.restore();
    }

    // Abbreviation text (bold white with slight shadow)
    ctx.save();
    ctx.shadowBlur = 4;
    ctx.shadowColor = "rgba(0,0,0,0.6)";
    ctx.fillStyle = n.dir === "NEUTRAL" ? _hex2rgba("#ffffff", 0.5) : "#ffffff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const fontSize = Math.max(10, drawR * 0.55);
    ctx.font = `700 ${fontSize}px 'JetBrains Mono', monospace`;
    ctx.fillText(n.abbr, n.x, n.y);
    ctx.restore();

    // Short name below node (Upgrade 2)
    const meta = AGENT_META[n.id];
    if (meta) {
      const shortN = _shortName(meta.name);
      ctx.fillStyle = _hex2rgba(col, n.dir === "NEUTRAL" ? 0.25 : 0.5);
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.font = `500 ${Math.max(7, drawR * 0.32)}px 'JetBrains Mono', monospace`;
      ctx.fillText(shortN, n.x, n.y + drawR + 8);
    }
  }

  function _drawThoughtBubbles() {
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";

    for (const tb of thoughtBubbles) {
      const alpha = Math.min(1, tb.alpha);
      if (alpha <= 0) continue;

      const y = tb.y + tb.offsetY;
      const text = '"' + tb.text + '"';
      const metrics = ctx.measureText(text);
      const pad = 6;
      const w = metrics.width + pad * 2;
      const h = 16;
      const bx = tb.x - w / 2;
      const by = y - h;

      // Background
      ctx.fillStyle = _hex2rgba("#0a0a1a", alpha * 0.85);
      _roundRect(ctx, bx, by, w, h, 4);
      ctx.fill();
      ctx.strokeStyle = _hex2rgba("#40c4ff", alpha * 0.2);
      ctx.lineWidth = 0.5;
      _roundRect(ctx, bx, by, w, h, 4);
      ctx.stroke();

      // Text
      ctx.fillStyle = _hex2rgba("#c0c0d0", alpha * 0.8);
      ctx.fillText(text, bx + pad, by + h - 3);
    }
  }

  // ── Utils ───────────────────────────────────────────────
  function _hex2rgba(hex, alpha) {
    const r = parseInt(hex.slice(1,3), 16);
    const g = parseInt(hex.slice(3,5), 16);
    const b = parseInt(hex.slice(5,7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  function _roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  // ── Hover Card (Upgrade 2) ──────────────────────────────
  function _initHoverCard() {
    hoverCardEl = document.getElementById("agent-hover-card");
    if (!hoverCardEl || !canvas) return;

    canvas.addEventListener("mousemove", (e) => {
      const now = performance.now();
      if (now - hoverThrottleTime < 16) return; // ~60fps max
      hoverThrottleTime = now;

      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      let found = null;
      for (const n of nodes) {
        const dx = mx - n.x;
        const dy = my - n.y;
        if (dx * dx + dy * dy < (n.r + 6) * (n.r + 6)) {
          found = n;
          break;
        }
      }

      if (found) {
        if (hoveredNode !== found) {
          hoveredNode = found;
          dirty = true;
          _showHoverCard(found, e.clientX, e.clientY, rect);
        } else {
          _positionHoverCard(e.clientX, e.clientY, rect);
        }
      } else {
        if (hoveredNode) {
          hoveredNode = null;
          dirty = true;
          hoverCardEl.classList.remove("visible");
        }
      }
    });

    canvas.addEventListener("mouseleave", () => {
      hoveredNode = null;
      if (hoverCardEl) hoverCardEl.classList.remove("visible");
    });
  }

  function _showHoverCard(n, cx, cy, canvasRect) {
    if (!hoverCardEl) return;
    const meta = AGENT_META[n.id] || { name: n.name, tribe: n.tribe, strategy: "" };
    const dirClass = n.dir === "BULL" ? "border-bull" : n.dir === "BEAR" ? "border-bear" : "border-neutral";
    const dirColor = n.dir === "BULL" ? "bull" : n.dir === "BEAR" ? "bear" : "neut";

    const elo = n.elo || _eloMap[n.id];
    const eloStr = elo ? ` &bull; ELO ${Math.round(elo)}` : "";
    const eloColor = elo >= 1050 ? "var(--bull)" : elo <= 950 ? "var(--bear)" : "var(--text-dim)";

    hoverCardEl.className = "agent-hover-card visible " + dirClass;
    hoverCardEl.innerHTML = `
      <div class="ahc-name">${_escHtml(meta.name)}</div>
      <div class="ahc-tribe">${_escHtml(meta.tribe)}</div>
      <div class="ahc-strategy">${_escHtml(meta.strategy)}</div>
      <div class="ahc-vote">
        <span class="${dirColor}">${n.dir}</span>
        <span style="color:var(--text-dim);">${Math.round(n.conv)}% conviction</span>
        ${elo ? `<span style="color:${eloColor};font-size:.62rem;">${eloStr}</span>` : ""}
      </div>
      ${n.reasoning ? `<div class="ahc-reasoning">${_escHtml(n.reasoning.length > 140 ? n.reasoning.slice(0, 137) + "..." : n.reasoning)}</div>` : ""}
    `;
    _positionHoverCard(cx, cy, canvasRect);
  }

  function _positionHoverCard(cx, cy, canvasRect) {
    if (!hoverCardEl) return;
    const wrap = canvas.parentElement;
    const wrapRect = wrap.getBoundingClientRect();
    let left = cx - wrapRect.left + 16;
    let top = cy - wrapRect.top - 10;

    // Keep within wrap bounds
    const cardW = hoverCardEl.offsetWidth || 240;
    const cardH = hoverCardEl.offsetHeight || 160;
    if (left + cardW > wrapRect.width) left = cx - wrapRect.left - cardW - 16;
    if (top + cardH > wrapRect.height) top = wrapRect.height - cardH - 8;
    if (top < 0) top = 8;

    hoverCardEl.style.left = left + "px";
    hoverCardEl.style.top = top + "px";
  }

  function _escHtml(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  // ── Cinematic Mode (Upgrade 3) ─────────────────────────
  function _initCinematicMode() {
    const btn = document.getElementById("cinematic-btn");
    if (btn) {
      btn.addEventListener("click", (e) => { e.preventDefault(); _toggleCinematic(); });
    }

    document.addEventListener("keydown", (e) => {
      // Don't capture if user is typing in an input
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (e.key === "f" || e.key === "F") {
        _toggleCinematic();
      }
      if (e.key === "Escape" && isCinematic) {
        _toggleCinematic();
      }
    });

    // Keep cinematic overlays updated
    document.addEventListener("market:update", (e) => _updateCinematicOverlay(e.detail));
    document.addEventListener("consensus:reached", (e) => _updateCinematicConsensus(e.detail));
    document.addEventListener("state:full", (e) => {
      if (e.detail.market_context) _updateCinematicOverlay(e.detail.market_context);
      if (e.detail.consensus) _updateCinematicConsensus(e.detail.consensus);
    });
  }

  function _toggleCinematic() {
    isCinematic = !isCinematic;
    document.body.classList.toggle("cinematic-mode", isCinematic);

    // Resize canvas after layout change
    setTimeout(() => {
      _resize();
      _layoutNodes();
    }, 50);
  }

  function _updateCinematicOverlay(ctx) {
    if (!ctx) return;
    const spx = document.getElementById("cin-spx");
    const vix = document.getElementById("cin-vix");
    const regime = document.getElementById("cin-regime");
    if (spx) spx.textContent = "SPX " + (parseFloat(ctx.spx_price) || 0).toFixed(2);
    if (vix) vix.textContent = "VIX " + (parseFloat(ctx.vix_level) || 0).toFixed(2);
    if (regime && ctx.market_regime) regime.textContent = ctx.market_regime;
  }

  function _updateCinematicConsensus(c) {
    if (!c) return;
    const dir = document.getElementById("cin-direction");
    const conf = document.getElementById("cin-confidence");
    const d = (c.direction || "").toUpperCase();
    if (dir) {
      dir.textContent = d || "--";
      dir.style.color = d === "BULL" ? "var(--bull)" : d === "BEAR" ? "var(--bear)" : "var(--text-dim)";
    }
    if (conf) conf.textContent = (parseFloat(c.confidence) || 0).toFixed(0) + "% confidence";
  }

  // ── Public ──────────────────────────────────────────────
  return { init };
})();

// Also expose as initAgentNetwork for external callers
function initAgentNetwork(canvasId) {
  AgentNetwork.init(canvasId);
}

document.addEventListener("DOMContentLoaded", () => {
  AgentNetwork.init("agent-canvas");
});
