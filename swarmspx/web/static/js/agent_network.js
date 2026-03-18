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

  // ── Init ────────────────────────────────────────────────
  function init(canvasId) {
    canvas = document.getElementById(canvasId || "agent-canvas");
    if (!canvas) return;
    ctx = canvas.getContext("2d");

    _resize();
    _buildNodes();
    _initAmbientParticles();
    _listen();
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
          r: 18, tr: 18,
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
      // Shockwave from center
      shockwaves.push({ x: W / 2, y: H / 2, radius: 0, maxRadius: Math.max(W, H) * 0.6, alpha: 0.3 });
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

      // Target radius: 18-22 based on conviction
      n.tr = 18 + (n.conv / 100) * 4;
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

    // Ambient particles
    for (const p of particles) {
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0) p.x = W;
      if (p.x > W) p.x = 0;
      if (p.y < 0) p.y = H;
      if (p.y > H) p.y = 0;
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
    ctx.fillStyle = "rgba(20, 20, 40, 0.25)";
    const step = 35;
    for (let x = step; x < W; x += step) {
      for (let y = step; y < H; y += step) {
        ctx.beginPath();
        ctx.arc(x, y, 0.6, 0, Math.PI * 2);
        ctx.fill();
      }
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
      ctx.beginPath();
      ctx.arc(sw.x, sw.y, sw.radius, 0, Math.PI * 2);
      ctx.strokeStyle = _hex2rgba("#40c4ff", sw.alpha);
      ctx.lineWidth = 2;
      ctx.stroke();

      // Inner glow
      const grad = ctx.createRadialGradient(sw.x, sw.y, sw.radius * 0.95, sw.x, sw.y, sw.radius);
      grad.addColorStop(0, "rgba(64,196,255,0)");
      grad.addColorStop(1, _hex2rgba("#40c4ff", sw.alpha * 0.3));
      ctx.fillStyle = grad;
      ctx.fill();
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

  function _drawNode(n) {
    const col = DIR_COLORS[n.dir] || "#37474f";

    // Breathing animation
    const breathe = Math.sin(time * 1.2 + n.breatheOffset) * 1.2;
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

    // Main circle
    const grad = ctx.createRadialGradient(
      n.x - drawR * 0.25, n.y - drawR * 0.25, 0,
      n.x, n.y, drawR
    );
    if (n.dir === "NEUTRAL") {
      grad.addColorStop(0, "rgba(55, 71, 79, 0.35)");
      grad.addColorStop(1, "rgba(55, 71, 79, 0.1)");
    } else {
      grad.addColorStop(0, _hex2rgba(col, 0.45));
      grad.addColorStop(1, _hex2rgba(col, 0.15));
    }

    ctx.save();
    ctx.shadowBlur = n.dir !== "NEUTRAL" ? 8 : 0;
    ctx.shadowColor = col;
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(n.x, n.y, drawR, 0, Math.PI * 2);
    ctx.fill();

    // Border
    ctx.strokeStyle = _hex2rgba(col, 0.5 + n.glow * 0.5);
    ctx.lineWidth = n.dir !== "NEUTRAL" ? 1.5 : 1;
    ctx.stroke();
    ctx.restore();

    // Abbreviation text
    ctx.fillStyle = _hex2rgba(col, n.dir === "NEUTRAL" ? 0.5 : 0.9);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const fontSize = Math.max(9, drawR * 0.65);
    ctx.font = `700 ${fontSize}px 'JetBrains Mono', monospace`;
    ctx.fillText(n.abbr, n.x, n.y);

    // Conviction bar under node
    if (n.conv > 5) {
      const barW = drawR * 1.6;
      const barH = 2;
      const barX = n.x - barW / 2;
      const barY = n.y + drawR + 5;
      ctx.fillStyle = "rgba(255,255,255,0.04)";
      _roundRect(ctx, barX, barY, barW, barH, 1);
      ctx.fill();
      ctx.fillStyle = _hex2rgba(col, 0.6);
      _roundRect(ctx, barX, barY, barW * (n.conv / 100), barH, 1);
      ctx.fill();
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
