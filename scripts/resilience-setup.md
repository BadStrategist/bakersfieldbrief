# Tier-2 Resilience — one-time setup (3 actions, ~20 minutes)

Goal: the site and the morning pipeline keep working even when the PC is
unplugged, powered down, or broken. Everything here is free. Two of the
three actions are account-level (GoDaddy, UptimeRobot) — do them once.

---

## 1. BIOS: power the PC back on automatically (2 minutes, once)

If the PC loses power and comes back at 6am, the 06:30 publish would miss.
Set the motherboard to power itself on every day at 02:45 — before the
03:00 phase-1 transcribe run.

1. Restart the PC and press **Del** (or F2/F10 — watch the first screen)
   during boot to enter BIOS/UEFI.
2. Find the power-management section (names vary):
   - ASUS: Advanced → APM Configuration → **Power On By RTC**
   - MSI: Settings → Advanced → Wake Up Event Setup → **Resume By RTC Alarm**
   - Gigabyte: Settings → Platform Power → **Erp / RTC Wake**
   - Dell/Lenovo: Power Management → **Auto On Time**
3. Enable it, set **every day** at **02:45**.
4. Save & exit (F10). Verify next day: at ~02:45 the PC boots itself.
5. (Optional) Windows: set a 2-minute startup delay for the Hermes app so
   the 03:00 cron doesn't fire mid-boot:
   - Task Scheduler → Create Task → trigger "At startup", action: delay
     via `timeout /t 120` then start Hermes.

Nothing to verify on the site — this is a physical setting.

---

## 2. Cloudflare Pages (DONE Aug 13, 2026) — host, spike-proof serving + analytics

Cloudflare Pages is now the host (repo made private Aug 12 — GitHub Pages can't
serve private repos on the free plan). Unlimited bandwidth, edge caching, free
analytics. What was done:

1. Cloudflare account (free) → add site `bakersfieldbrief.com` → Free plan
   (imported all DNS records — verify the list).
2. **Porkbun** (NOT GoDaddy — registrar) → Nameservers → Cloudflare's two NS
   (`wilson.ns.cloudflare.com` / `margaret.ns.cloudflare.com`). Zone goes
   Active in ~15–30 min; confirm via https://dns.google/resolve?name=...&type=NS
3. Pages project `bakersfieldbrief` (production branch `main`) created via API:
   `POST /accounts/<ACCT>/pages/projects` (token needs Account→Cloudflare
   Pages→Edit + Zone→DNS→Edit).
4. All 5 workflows (`.github/workflows/*.yml`) deploy with
   `cloudflare/wrangler-action@v3`, `command: pages deploy site
   --project-name=bakersfieldbrief`, secrets passed as **step env vars**
   `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` (wrangler-action v3 does
   NOT reliably export the `apiToken` input when using `command:` — the
   subprocess needs the real env vars; that was the first failed deploy).
   Project must EXIST before first deploy (second failure mode: "Project not
   found").
5. Custom domains `bakersfieldbrief.com` + `www` added to the project, then
   DNS: deleted the 4 dead GitHub `A 185.199.x` records + `CNAME www →
   badstrategist.github.io`, added `CNAME bakersfieldbrief.com` + `CNAME www
   → bakersfieldbrief.pages.dev` (proxied). The Pages API does NOT auto-create
   zone records — you must add them yourself.
6. Verify: `https://bakersfieldbrief.com/` 200 with real title (a few 522s
   right after the CNAME switch are cert propagation — retry), `/map/`,
   `/feed.xml`, `/ads.txt` (real pub ID), `Server: cloudflare` header.

Rollback: repoint the CNAMEs back to the GH Pages IPs and flip the repo public
— or change Porkbun nameservers back to Porkbun's defaults.

---

## 3. UptimeRobot free (5 minutes, once) — catch failures early

Two monitors. The second one is the important one: it alerts when the
overnight publish silently didn't happen (PC dead), before readers notice.

1. Sign up at https://uptimerobot.com (free tier: 50 monitors, 5-min
   checks, email alerts).
2. **Monitor 1 — site up:** Add New Monitor →
   - Monitor Type: **HTTP(s)**
   - URL: `https://bakersfieldbrief.com/`
   - Interval: **5 minutes** → Create.
3. **Monitor 2 — overnight freshness (the "PC died silently" alarm):**
   UptimeRobot's Cron/Heartbeat monitor type is paid, so this uses
   **healthchecks.io** (free dead-man's-switch, 20 checks, email alerts):
   - Sign up at https://healthchecks.io → **Add Check**.
   - Name: "Kern Overnight", Period: **1 day**, Grace: **2 hours** → Save.
   - Copy the check's **Ping URL** (`https://hc-ping.com/<uuid>`).
   - Give the URL to the assistant — it is stored as the GitHub secret
     `UP_OVERNIGHT_PING_URL` (repo Settings → Secrets and variables →
     Actions → New repository secret).
   - The deploy workflow pings this URL **only when today's overnight
     report exists in the repo**. Report published → ping → silence.
     Pipeline dead → no ping → healthchecks.io emails you ~2h after the
     missed deadline (same morning as the failure).
   - (The workflow step is already in `.github/workflows/daily.yml` — it
     activates automatically once the secret exists. Plain HTTP checks on
     /overnight/ would NOT work for this: the old page keeps returning
     200 when stale.)

4. **Monitor 3 — ALPR freshness (the "daily run never started" alarm):**
   Every `daily.yml` run already fails red and alerts ops Discord when the
   camera list on /surveillance/ was not fetched from OpenStreetMap on that
   run (`scripts/check_alpr_fresh.py`). A run that never starts cannot
   report itself, so this second healthchecks.io check covers that case:
   - **Add Check** → Name: "ALPR freshness", Period: **1 day**,
     Grace: **6 hours** → Save.
   - Store its Ping URL as the GitHub secret `UP_ALPR_PING_URL`.
   - The workflow pings it **only after the freshness check passed**. A
     day with no fresh fetch (Overpass down all day, schedule disabled,
     runs dropped) → no ping → healthchecks.io emails you.
   - Until the secret exists the step prints a notice on every run and
     does nothing else; the in-run check and the Discord alert do not
     depend on it.

---

## What each failure mode now does

| Failure | Recovery |
|---|---|
| Power out at 3am, back at 6am | BIOS RTC wakes PC at 02:45 → pipeline runs normally |
| PC dies mid-transcription | Checkpoint commits pushed the partial night → backfill when PC returns |
| PC dead all day | 06:00 GH Actions build still publishes the brief from cloud sources |
| 10k-visitor spike | Cloudflare edge absorbs it; GH Pages bandwidth cap gone |
| Silent staleness | UptimeRobot email alert within ~5 min of the feed breaking |
