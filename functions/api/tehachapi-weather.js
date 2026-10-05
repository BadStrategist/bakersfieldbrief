// Cloudflare Pages Function: the current Tehachapi observation.
//
// /api/tehachapi-weather
// Server-side fetch of the National Weather Service's latest observation for
// KTSP (Tehachapi Municipal Airport), with the same fallback stations and the
// same unit handling as build/sources/tehachapi_weather.py. The static page
// carries the reading from its last build; scheduled builds start late, so
// this gives visitors the reading as it stands now.
//
// Held in the edge cache for five minutes (a failure for one): NWS stations
// report about every twenty minutes, so nothing is gained by asking more often.
//
// Honesty: values are the station's own. A variable the station did not report
// is left out, never filled in. On failure we return ok:false and the page
// keeps the reading it was built with.

const STATIONS = ["KTSP", "SE067", "C1020"];
const OK_TTL = 300;
const FAIL_TTL = 60;
const UA = "BakersfieldDailyBrief/1.0 (+https://bakersfieldbrief.com; contact: editor@bakersfieldbrief.com)";
const DIRS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

// NWS has served wind in km/h, m/s and knots. Convert from the unitCode that
// ships with the value; never assume (a blind m/s factor once showed 19 mph as 66).
const TO_MPH = {
  "wmoUnit:m_s-1": 2.23694,
  "wmoUnit:km_h-1": 0.621371,
  "wmoUnit:mi_h-1": 1.0,
  "wmoUnit:mile_h-1": 1.0,
  "wmoUnit:kt": 1.150779,
  "wmoUnit:kt_i": 1.150779,
};

function windMph(node) {
  if (!node || node.value == null) return null;
  const factor = TO_MPH[node.unitCode] || TO_MPH["wmoUnit:km_h-1"];
  return Math.round(node.value * factor);
}

function observedLabel(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    timeZone: "America/Los_Angeles",
  });
}

async function load() {
  for (const st of STATIONS) {
    let props;
    try {
      const resp = await fetch(`https://api.weather.gov/stations/${st}/observations/latest`, {
        headers: { "Accept": "application/geo+json", "User-Agent": UA },
      });
      if (!resp.ok) continue;
      props = (await resp.json()).properties || {};
    } catch (e) {
      continue;
    }
    const c = props.temperature && props.temperature.value;
    if (c == null) continue; // empty observation: try the next station
    const out = { ok: true, station: st, temperature: Math.round(c * 9 / 5 + 32) };
    const wind = windMph(props.windSpeed);
    const gust = windMph(props.windGust);
    if (wind != null) out.wind_mph = wind;
    if (gust != null) out.gust_mph = gust;
    const deg = props.windDirection && props.windDirection.value;
    if (deg != null) out.wind_dir = DIRS[Math.floor(deg / 22.5) % 16];
    const rh = props.relativeHumidity && props.relativeHumidity.value;
    if (rh != null) out.humidity = Math.round(rh);
    out.condition = (props.textDescription || "").trim();
    out.timestamp = props.timestamp || "";
    out.observed = observedLabel(out.timestamp);
    return out;
  }
  return { ok: false, status: "no_station_reported" };
}

export async function onRequestGet(context) {
  const cache = caches.default;
  const cacheKey = new Request(new URL("/api/tehachapi-weather", context.request.url).toString());
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
