/**
 * Grapevine liveliness watchdog — Cloudflare Worker with a Cron Trigger.
 *
 * Port of the Hermes cron script `grapevine_watchdog.py`, moved off the PC so
 * the always-on box is no longer needed for this check.
 *
 * What it does every 3 hours (cron `17 * /3 * * *`):
 *   1. Fetch the live /grapevine/ page.
 *   2. Extract the "Caltrans report:" timestamp and compute its age.
 *   3. Post to Discord if the page is unreachable, is not the tracker, has no
 *      readable timestamp, or the report is older than MAX_AGE_HOURS.
 *   4. Stay silent when healthy (no channel spam).
 *
 * The `fetch` handler runs the same check and returns JSON, so the check can be
 * verified from a browser or curl without waiting for a cron tick.
 *
 * Secrets: DISCORD_WEBHOOK_URL (Worker secret). Absent, the alert cannot be
 * delivered; the JSON says so explicitly, and the cron logs an error.
 */

const URL = "https://bakersfieldbrief.com/grapevine/";
const MAX_AGE_HOURS = 10; // the longest legitimate overnight gap is ~8h
const MARKER = "Is the Grapevine closed right now?";

// Same pattern as the Python watchdog: the page renders
// 'Caltrans report: <span class="updated">Monday, September 21st, 2026 at 07:06 PM</span>'
// and the parenthetical age hint is stripped before parsing.
const TS_RE =
  /(?:Caltrans report:|reported as of|as of)\s*([A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s*[AP]M)/i;
const MONTHS = {
  january: 0, february: 1, march: 2, april: 3, may: 4, june: 5,
  july: 6, august: 7, september: 8, october: 9, november: 10, december: 11,
};

function stripTags(html) {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

function reportTimestamp(page) {
  const m = TS_RE.exec(stripTags(page));
  return m ? m[1].trim() : "";
}

/** Offset in ms between Los Angeles wall clock and UTC at a given instant. */
function ptOffsetMs(instantMs) {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles", hour12: false,
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(new Date(instantMs)).map((x) => [x.type, x.value]),
  );
  const asUTC = Date.UTC(
    Number(p.year), Number(p.month) - 1, Number(p.day),
    Number(p.hour) % 24, Number(p.minute), Number(p.second),
  );
  return asUTC - instantMs;
}

/** Minutes since the report, or null when the string cannot be read. */
function ageMinutes(ts) {
  const m = /([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})\s+at\s+(\d{1,2}):(\d{2})\s*([AP])M/i
    .exec(ts.replace(/\([^)]*\)/g, " "));
  if (!m) return null;
  const mon = MONTHS[m[1].toLowerCase()];
  if (mon === undefined) return null;
  let hour = Number(m[4]) % 12;
  if (/p/i.test(m[6])) hour += 12;
  const wall = Date.UTC(Number(m[3]), mon, Number(m[2]), hour, Number(m[5]));
  let instant = wall - ptOffsetMs(wall); // first pass guesses the offset
  instant = wall - ptOffsetMs(instant);  // second pass settles DST
  return Math.max(Math.floor((Date.now() - instant) / 60000), 0);
}

async function check() {
  const now = new Date().toISOString();
  let res;
  try {
    res = await fetch(URL, {
      headers: { "user-agent": "BakersfieldBrief-GrapevineWatchdog/1.0" },
      cf: { cacheTtl: 0 },
    });
  } catch (e) {
    return { state: "unreachable", alert: true, now, detail: String(e),
      text: `🚨 **Grapevine Watchdog — ${now}**\n❌ <${URL}> is UNREACHABLE — the site is down or Cloudflare is blocking.\n🔧 Check GH Actions deploy / Cloudflare.` };
  }
  if (!res.ok) {
    return { state: "unreachable", alert: true, now, detail: `HTTP ${res.status}`,
      text: `🚨 **Grapevine Watchdog — ${now}**\n❌ <${URL}> returned HTTP ${res.status}.\n🔧 Check GH Actions deploy / Cloudflare.` };
  }
  const page = await res.text();

  if (!page.includes(MARKER)) {
    return { state: "not_tracker", alert: true, now,
      text: `🚨 **Grapevine Watchdog — ${now}**\n⚠️ Page is reachable but doesn't look like the tracker — unexpected HTML.\n🔧 Inspect <${URL}>.` };
  }

  const ts = reportTimestamp(page);
  if (!ts) {
    return { state: "no_timestamp", alert: true, now,
      text: `⚠️ **Grapevine Watchdog — ${now}**\nPage is up but no 'Caltrans report' timestamp found — it may be showing a broken/empty state. Inspect the page.` };
  }

  const mins = ageMinutes(ts);
  if (mins === null) {
    return { state: "unparseable", alert: true, now, report: ts,
      text: `⚠️ **Grapevine Watchdog — ${now}**\nFound report timestamp '${ts}' but could not read its age, so this run cannot vouch for how fresh the page is. The page is up; suspect the watchdog's timestamp parsing, not the build.\n🔧 Check the 'Caltrans report:' line format on <${URL}>.` };
  }

  const hrs = mins / 60;
  if (hrs > MAX_AGE_HOURS) {
    return { state: "stale", alert: true, now, report: ts, ageMinutes: mins,
      text: `🚨 **Grapevine Watchdog — ${now}**\n⚠️ Grapevine page is **stale** — last Caltrans report ${hrs.toFixed(1)}h ago (${mins} min ago). CI likely stopped rebuilding.\n🔧 Check GH Actions daily.yml runs + Caltrans fetch success.` };
  }

  return { state: "ok", alert: false, now, report: ts, ageMinutes: mins };
}

async function deliver(env, text) {
  const hook = env.DISCORD_WEBHOOK_URL;
  if (!hook) {
    console.error("ALERT NOT DELIVERED: DISCORD_WEBHOOK_URL is not set on this Worker");
    return "not_deliverable";
  }
  try {
    const r = await fetch(hook, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ content: text.slice(0, 1900) }),
    });
    if (!r.ok) {
      console.error(`discord post failed: HTTP ${r.status}`);
      return "failed";
    }
    return "sent";
  } catch (e) {
    console.error(`discord post threw: ${e}`);
    return "failed";
  }
}

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil((async () => {
      const r = await check();
      const delivery = r.alert ? await deliver(env, r.text) : "not_needed";
      console.log(JSON.stringify({ ...r, text: undefined, delivery }));
    })());
  },

  async fetch(_req, env) {
    const r = await check();
    const delivery = r.alert ? await deliver(env, r.text) : "not_needed";
    return new Response(
      JSON.stringify({ ok: r.state === "ok", ...r, delivery, worker: "grapevine-watchdog" }, null, 2),
      { headers: { "content-type": "application/json", "cache-control": "no-store" } },
    );
  },
};