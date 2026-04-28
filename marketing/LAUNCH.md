# SwarmSPX Path B Launch Playbook

**Goal:** Validate demand for the SwarmSPX SaaS product (24-agent debate dashboard + risk subsystem + paper broker) **before** building paid-tier infrastructure. Lean-startup: collect emails, ship the demo, see if the market cares.

---

## This week (Day 0–7) — get the landing page live

### 1. Replace the Formspree placeholder (5 min)
- Sign up at https://formspree.io (free tier: 50 submissions/mo)
- Create a new form, copy the endpoint URL
- In `marketing/index.html` find `https://formspree.io/f/YOUR_FORMSPREE_ID`
- Replace with your real endpoint (single grep-and-replace)
- Test by submitting your own email and confirm it lands in your inbox

Alternative: **ConvertKit** (free up to 1k subs) or **Mailchimp** if you want sequenced onboarding emails. Formspree is fastest for MVP.

### 2. Deploy the static site (10 min)
Pick one — all are free for this scale:

**Option A — Vercel (fastest):**
```bash
cd ~/Projects/swarmspx
npx vercel --cwd marketing
# pick the marketing/ directory as root → Vercel returns swarmspx-xyz.vercel.app
```

**Option B — Cloudflare Pages (best CDN):**
- https://dash.cloudflare.com → Pages → "Create a project"
- Connect to GitHub, point at `marketing/`
- No build command needed

**Option C — GitHub Pages (zero new accounts):**
- Repo Settings → Pages → Source: `main`, folder `/marketing`
- URL: `dhawalc.github.io/swarmSPX/`

### 3. Custom domain (optional, $12/yr)
- Buy `swarmspx.com` (or `.trade`/`.ai`/`.app`) at Cloudflare Registrar
- Point at the host above; SSL automatic
- Update OG meta tags in `index.html`

### 4. Open Graph image
- Generate at https://og-playground.vercel.app
- Save as `marketing/og.png` (1200×630)
- Add `<meta property="og:image" content="https://swarmspx.com/og.png" />`
- Test with https://www.opengraph.xyz/

---

## Week 2 — drive traffic + measure signal

### Distribution channels (priority order)

1. **X/Twitter long-form post** — your existing audience. Lead with the honest backtest table (Friday Pin Sharpe 3.66 with caveats). Don't overhype.
2. **r/options + r/algotrading + r/SecurityAnalysis** — single post per sub. Lead with the open-source angle. Reddit hates marketing — point at GitHub, the waitlist link is in the README.
3. **Hacker News** — "Show HN: SwarmSPX – multi-agent debate engine for SPX 0DTE traders". Submit Tue/Wed 8 AM ET. Mention war-room critique + honest backtest.
4. **YC Startup School / Indie Hackers / Product Hunt** — only when ≥50 waitlist signups.
5. **FinTwit influencer DMs** — Cem Karsan (@jam_croissant), SpotGamma, Bryon Kennedy. Don't pitch — share. "I built an open-source GEX engine inspired by your work, would love feedback."

### Metrics to track
- Waitlist signups per day
- Source attribution (UTM tags on each channel link)
- GitHub stars
- X impressions + replies on the launch thread

### Decision gate at end of Week 2
- **≥100 signups** → graduate to building paid product (Stripe, multi-tenant, hosted dashboard)
- **30–100** → keep iterating on positioning + add more strategies. Re-pitch in 4 weeks.
- **<30** → market doesn't want this. Either pivot positioning (more research-tool, less trading-tool) or accept it's a portfolio piece.

---

## Month 2 (only if ≥100 signups)

### Stripe + multi-tenant minimum
- Stripe Checkout for $99/mo Pro
- Cloudflare Access or Auth0 for dashboard auth
- Per-user DuckDB file (`data/{user_id}/swarmspx.duckdb`)
- Per-user Telegram bot token (users supply their own)
- Per-user Schwab token (BYO broker — we never custody, less regulatory exposure)
- Hosted at `app.swarmspx.com` (separate from marketing)

### Pro-tier features
- **Per-user signal alerts** to user's own Telegram
- **Paper broker private to user** with their own ledger
- **Custom agent slots** — already built
- **Friday Pin auto-fire** — daily 15:30 ET cron, pages the user
- **Audit log download** — zip of `data/decisions/*.jsonl`

---

## Permanent disclaimers / liability

Before paid signups, ship these two static pages:

- `marketing/disclaimer.html` — full legal disclaimer (template from any options-research site)
- `marketing/privacy.html` — minimal GDPR/CCPA: collect email+IP, used for signup, retain until unsubscribe, 3rd parties: Formspree+Stripe+Telegram. Use https://www.privacypolicies.com/ generator.

Keep the site no-cookie static HTML — no Google Analytics. Use Cloudflare/Vercel built-in privacy-respecting analytics.

---

## What NOT to claim

The landing page is intentionally honest. Never add:
- "Beat the market" / "guaranteed returns" / specific dollar figures
- A specific Sharpe without the "14-trade sample" caveat
- Anything implying SwarmSPX is a registered advisor or broker
- That the 24-agent swarm has proven edge (only Friday Pin has, on a small sample)

These claims trigger SEC concerns AND destroy trust the moment a sophisticated user reads the GitHub repo. The brand is "honest research tool with capacity-arb edge." Hold that.

---

## When to revisit

- **Day 7:** count signups. Pivot positioning if low.
- **Day 30:** Stripe live OR pivot to consulting/contracting.
- **Day 90:** First Pro customer. If zero, Path B has failed; pivot to selling the codebase as a one-time license or open-source maintenance contract.

This is a 90-day commitment. If it doesn't validate, the war-room Path A (just walk away) is the right move.
