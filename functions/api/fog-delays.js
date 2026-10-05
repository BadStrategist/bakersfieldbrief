// Cloudflare Pages Function: live Kern County school delays and closures.
//
// /api/fog-delays
// Server-side fetch of the Kern County Superintendent of Schools' AlertLine
// (https://alertline.kern.org/api/1.0/posted/alerts/today/{key}). The static
// page (rebuilt a few times a day) is the crawlable base; districts post
// between about 4:30 and 6:30 AM, long before the next build, so this function
// gives visitors the board as it stands now.
//
// The key is the Pages secret ALERTLINE_API_KEY. It rides in the upstream URL
// path, so no upstream URL or error text is ever returned to the browser.
//
// AlertLine allows 1,000 requests a day per key. Responses are held in the edge
// cache for three minutes (and failures for one), so each Cloudflare location
// asks at most 480 times a day however many parents have the page open.
//
// Honesty: rows are the districts' own words and timestamps. On any failure we
// return ok:false and the page keeps its build-time board. We never guess.

const BASE = "https://alertline.kern.org/api/1.0/posted/alerts/";
const OK_TTL = 180;
const FAIL_TTL = 60;
const CLOSURE = 99;

function clean(v) {
  return String(v == null ? "" : v).replace(/\s+/g, " ").trim();
}

// Same classification as build/sources/alertline.py normalize().
function normalize(row) {
  const site = clean(row.site_name);
  if (!site) return null;
  const severity = parseInt(row.severity, 10) || 0;
  const category = clean(row.alert_category);
  const description = clean(row.description);
  const info = clean(row.additional_info);
  const label = (category + " " + description).toLowerCase();
  let kind = "other";
  if (severity === CLOSURE || label.includes("closure")) kind = "closure";
  else if ((severity > 0 && severity < CLOSURE) || label.includes("delay")) kind = "delay";
  return { site, description, info, category, severity, kind,
           fog: (label + " " + info.toLowerCase()).includes("fog"),
           updated_at: clean(row.updated_at) };
}

async function upstream(path) {
  const resp = await fetch(BASE + path, {
    headers: { "Accept": "application/json",
               "User-Agent": "BakersfieldDailyBrief/1.0 (+https://bakersfieldbrief.com)" },
  });
  const text = await resp.text();
  return { status: resp.status, text };
}

async function load(env) {
  const key = (env.ALERTLINE_API_KEY || "").trim();
  if (!key) {
    // No key yet: say so, and report whether AlertLine is reachable from here
    // at all (its public sample endpoint), without returning the sample rows.
    let reachable = false;
    try { reachable = (await upstream("test")).status === 200; } catch (e) { reachable = false; }
    return { ok: false, status: "no_key", upstream_reachable: reachable };
  }
  let res;
  try {
    res = await upstream("today/" + encodeURIComponent(key));
  } catch (e) {
    return { ok: false, status: "unreachable" };
  }
  if (res.status === 403) return { ok: false, status: "key_rejected" };
  if (res.status !== 200) return { ok: false, status: "http_" + res.status };
  let rows;
  try { rows = JSON.parse(res.text); } catch (e) {
    // The daily request limit answers 200 with a plain-text notice.
    return { ok: false, status: /limit/i.test(res.text) ? "limit_reached" : "not_json" };
  }
  if (!Array.isArray(rows)) return { ok: false, status: "not_a_list" };
  const alerts = rows.map(normalize).filter(Boolean)
    .sort((a, b) => (b.severity - a.severity) || a.site.localeCompare(b.site));
  return { ok: true, status: "ok", alerts, count: alerts.length };
}

export async function onRequestGet(context) {
  const cache = caches.default;
  const cacheKey = new Request(new URL("/api/fog-delays", context.request.url).toString());
  const hit = await cache.match(cacheKey);
  if (hit) return hit;

  const data = await load(context.env);
  data.fetched_at = new Date().toISOString();
  const resp = new Response(JSON.stringify(data), {
    // Always 200: Cloudflare will not edge-cache an error status, and a failure
    // has to be held too or every page load would spend a request on it.
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": `public, max-age=${data.ok ? OK_TTL : FAIL_TTL}`,
    },
  });
  context.waitUntil(cache.put(cacheKey, resp.clone()));
  return resp;
}
