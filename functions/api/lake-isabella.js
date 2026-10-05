// Cloudflare Pages Function: the latest Lake Isabella reading.
//
// /api/lake-isabella
// Server-side fetch of the same three CDEC daily series the build reads
// (station ISB: storage, elevation, inflow; see build/sources/isabella.py).
//
// The lake is reported once a day, so this is not a minute-by-minute feed. Its
// job is the gap between CDEC posting a new day's reading and the next site
// build, which can be hours when scheduled builds start late. The page uses it
// only to say "a newer reading exists" and show it; it never rewrites the
// page's own figures.
//
// Held in the edge cache for thirty minutes (a failure for five).
//
// Honesty: values are CDEC's own. -9999 and blanks are CDEC's "missing" and are
// skipped. On failure we return ok:false and the page shows nothing extra.

const URL_BASE = "https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet";
const SENSORS = { storage: 15, elev: 6, inflow: 23 };
const CAPACITY_AF = 568000;
const OK_TTL = 1800;
const FAIL_TTL = 300;
const UA = "BakersfieldDailyBrief/1.0 (+https://bakersfieldbrief.com; contact: editor@bakersfieldbrief.com)";

function pacificDate(offsetDays) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return d.toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" }); // YYYY-MM-DD
}

// CDEC writes "2026-9-5 00:00"; normalise to "2026-09-05".
function dayKey(s) {
  const m = /(\d{4})-(\d{1,2})-(\d{1,2})/.exec(String(s || ""));
  return m ? `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}` : "";
}

async function latest(sensor) {
  const url = `${URL_BASE}?Stations=ISB&SensorNums=${sensor}&dur_code=D`
    + `&Start=${pacificDate(-7)}&End=${pacificDate(1)}`;
  const resp = await fetch(url, { headers: { "Accept": "application/json", "User-Agent": UA } });
  if (!resp.ok) throw new Error("http " + resp.status);
  const rows = await resp.json();
  let best = null;
  for (const row of Array.isArray(rows) ? rows : (rows.data || [])) {
    const v = parseFloat(row.value);
    const day = dayKey(row.date || row.obsDate);
    if (!day || isNaN(v) || v <= -5000) continue;
    if (!best || day >= best.date) best = { date: day, value: v };
  }
  return best;
}

async function load() {
  let storage, elev, inflow;
  try {
    [storage, elev, inflow] = await Promise.all([
      latest(SENSORS.storage),
      latest(SENSORS.elev).catch(() => null),
      latest(SENSORS.inflow).catch(() => null),
    ]);
  } catch (e) {
    return { ok: false, status: "unreachable" };
  }
  if (!storage) return { ok: false, status: "no_reading" };
  return {
    ok: true,
    storage: { date: storage.date, value: Math.round(storage.value) },
    elev: elev ? { date: elev.date, value: Math.round(elev.value * 100) / 100 } : null,
    inflow: inflow ? { date: inflow.date, value: Math.round(inflow.value) } : null,
    pct: Math.round(1000 * storage.value / CAPACITY_AF) / 10,
  };
}

export async function onRequestGet(context) {
  const cache = caches.default;
  const cacheKey = new Request(new URL("/api/lake-isabella", context.request.url).toString());
  const hit = await cache.match(cacheKey);
  if (hit) return hit;

  const data = await load();
  data.fetched_at = new Date().toISOString();
  const resp = new Response(JSON.stringify(data), {
    // Always 200 so the edge cache holds a failure too (see fog-delays.js).
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": `public, max-age=${data.ok ? OK_TTL : FAIL_TTL}`,
    },
  });
  context.waitUntil(cache.put(cacheKey, resp.clone()));
  return resp;
}
