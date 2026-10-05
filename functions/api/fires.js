// Cloudflare Pages Function: live CAL FIRE active wildfires for BakersfieldBrief.com.
//
// /api/fires
// Server-side fetch of CAL FIRE's public incident feed
// (https://www.fire.ca.gov/umbraco/api/IncidentApi/List?inactive=false).
// The static site (rebuilt every 3h) stays as the crawlable/AI base; this
// function gives visitors the CURRENT CAL FIRE incident list on-demand, with
// the agency's own verbatim timestamps and field values — never invented,
// never build-time.
//
// Cost/ops: fires only when a page with the live fires widget is opened. No
// cron, no LLM, no token spend. A short in-function cache keeps CAL FIRE
// fetch volume to ~1/min at most.
//
// Honesty: we return CAL FIRE's own Name/County/acres/containment/location
// and updated timestamp verbatim. If the fetch fails we fail open (return a
// 503 signal) — we never guess a count or a fire.

// CAL FIRE moved this API to incidents.fire.ca.gov; www.fire.ca.gov now only
// redirects there, and refuses (403) any request that claims to be a desktop
// browser. That is why this function failed for weeks while the Python build,
// which names itself honestly and follows the redirect, kept working.
const URL = "https://incidents.fire.ca.gov/umbraco/api/IncidentApi/List?inactive=false";
const UA = "BakersfieldDailyBrief/1.0 (+https://bakersfieldbrief.com; contact: editor@bakersfieldbrief.com)";

// in-flight/result cache: at most one CAL FIRE fetch/60s across all visitors
let CACHE = { at: 0, data: null };
const CACHE_MS = 60_000;

// Case-tolerant key lookup — the API uses 'County', 'Name', 'acresBurned',
// 'percentContained', 'StartedDateOnly', … exactly as the site's builder does.
function get(item, ...names) {
  for (const n of names) {
    const v = item[n];
    if (v !== undefined && v !== null && v !== "") return v;
  }
  return "";
}

function parseIncidents(raw) {
  const incidents = [];
  for (const i of raw) {
    incidents.push({
      name: get(i, "Name", "name") || "Unnamed incident",
      county: get(i, "County", "county"),
      acres: get(i, "acresBurned", "AcresBurned", "Acres"),
      contained: get(i, "percentContained", "PercentContained", "Containment"),
      lat: get(i, "Latitude", "latitude"),
      lon: get(i, "Longitude", "longitude"),
      started: get(i, "StartedDateOnly", "Started", "StartedDate"),
      updated: get(i, "UpdatedDateOnly", "Updated", "LastUpdated"),
      location: get(i, "Location", "location"),
      type: get(i, "Type", "type"),
      url: get(i, "url", "Url", "URL")
        || `https://www.fire.ca.gov/incidents/${get(i, "slug", "Slug") || ""}`,
    });
  }
  const kern = incidents.filter((f) => /Kern/i.test(String(f.county || "")));
  return { incidents, kern, total: incidents.length, kern_count: kern.length };
}

export async function onRequestGet(context) {
  // serve from cache if fresh
  if (CACHE.data && Date.now() - CACHE.at < CACHE_MS) {
    return json(CACHE.data);
  }

  let ok = false;
  let lastErr = "";
  let probes = [];
  let incidents = [];
  let kern = [];
  let total = 0;
  let kernCount = 0;

  try {
    const resp = await fetch(URL, {
      headers: {
        "User-Agent": UA,
        "Accept": "application/json",
      },
      redirect: "follow",
    });
    const ct = (resp.headers.get("content-type") || "").slice(0, 20);
    probes.push(`calfire:${resp.status}:${ct}`);
    const text = await resp.text();
    if (!resp.ok) {
      lastErr = `calfire http ${resp.status}`;
    } else {
      let raw = null;
      try { raw = JSON.parse(text); } catch (e) { lastErr = "calfire invalid JSON"; }
      if (raw && Array.isArray(raw)) {
        const parsed = parseIncidents(raw);
        incidents = parsed.incidents;
        kern = parsed.kern;
        total = parsed.total;
        kernCount = parsed.kern_count;
        ok = true;
      } else {
        lastErr = "calfire payload not a list";
      }
    }
  } catch (e) {
    lastErr = `calfire threw ${String(e && e.message ? e.message : e).slice(0, 100)}`;
  }

  const data = {
    ok,
    incidents, kern, total, kern_count: kernCount,
    probes,
    status: ok ? "ok" : "unavailable",
    fetched_at: new Date().toISOString(),
    err: ok ? undefined : (lastErr || "fetch failed"),
    note: ok
      ? "CAL FIRE active incidents, live via /api/fires."
      : "CAL FIRE unreachable right now — showing the last static build.",
  };
  CACHE = { at: Date.now(), data };
  return json(data, ok ? 200 : 503);
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
