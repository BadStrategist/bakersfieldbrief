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

## 2. Cloudflare free (15 minutes, once) — spike-proof serving + analytics

Cloudflare sits in front of GitHub Pages: unlimited bandwidth (removes the
100GB/month Pages cap — relevant at ~10k visitors/day), edge caching, free
analytics. Zero downtime if done in this order.

1. Create a free account at https://dash.cloudflare.com/sign-up.
2. Add site → enter **bakersfieldbrief.com** → select the **Free** plan.
3. Cloudflare scans your current DNS and imports every record. **Verify the
   list** — you must see at least:
   - CNAME `www` → `badstrategist.github.io` (or whatever GH Pages shows)
   - The apex (root) record for the site
   - Any MX / email records (email forwarding keeps working through these)
   Click "Continue".
4. Cloudflare shows two nameservers like `amy.ns.cloudflare.com`. **Copy
   them.**
5. Log in at **GoDaddy** → Domain → bakersfieldbrief.com → DNS →
   Nameservers → **Change** → enter Cloudflare's two nameservers → Save.
6. Back in Cloudflare: wait ~15–30 min for "Active" status. When active,
   confirm:
   - SSL/TLS → mode **Full** (default) — HTTPS keeps working.
   - Security level → **Essentially off** or **Low**. Do NOT enable
     "Under Attack Mode" (it captchas real humans).
   - Caching → leave defaults. The site's `?v=build-date` cache-busting
     already refreshes CSS/JS on every build.
7. Verify after activation:
   - https://bakersfieldbrief.com loads (HTTPS, padlock).
   - https://bakersfieldbrief.com/feed.xml still 200.
   - Send yourself an email to `corrections@bakersfieldbrief.com` — it
     still arrives (MX records pass through Cloudflare).

Rollback: change the GoDaddy nameservers back to GoDaddy's defaults. The
old DNS is ready to serve again within ~30 min.

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

---

## What each failure mode now does

| Failure | Recovery |
|---|---|
| Power out at 3am, back at 6am | BIOS RTC wakes PC at 02:45 → pipeline runs normally |
| PC dies mid-transcription | Checkpoint commits pushed the partial night → backfill when PC returns |
| PC dead all day | 06:00 GH Actions build still publishes the brief from cloud sources |
| 10k-visitor spike | Cloudflare edge absorbs it; GH Pages bandwidth cap gone |
| Silent staleness | UptimeRobot email alert within ~5 min of the feed breaking |
