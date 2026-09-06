// Cloudflare Pages Function: live road conditions for the pass pages.
//
// /api/pass-conditions
// Server-side fetch of Caltrans (roads.dot.ca.gov) for I-5, SR-58, SR-99.
// The static site (rebuilt every 3h) stays as the crawlable/AI base; this
// function gives visitors the CURRENT Caltrans report on-demand, with the
// agency's own verbatim timestamp — never invented, never build-time.
//
// Cost/ops: fires only when a page with the live widget is opened. No cron,
// no LLM, no token spend. A short in-function + HTTP cache keeps Caltrans
// fetch volume to ~1/min at most.
//
// Honesty: we return Caltrans' own `reported_as_of` and status string; the
// client displays it verbatim with the age. If the fetch fails we fail open
// (return the last-good static impression via a 503 signal) — we never guess.

const ROUTES = [
  { number: "5",  slug: "i5",   name: "Interstate 5 (Grapevine / Tejon Pass)", pass: true },
  { number: "58", slug: "sr58", name: "State Route 58 (Tehachapi)",           pass: false },
  { number: "99", slug: "sr99", name: "State Route 99 (Central Valley)",      pass: false },
];

const URL = (n) => `https://roads.dot.ca.gov/roadscell.php?roadnumber=${n}`;

// in-flight/result cache: at most one Caltrans pass/60s across all visitors
let CACHE = { at: 0, data: null };
const CACHE_MS = 60_000;

async function fetchCaltrans(route) {
  const resp = await fetch(URL(route.number), {
    headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36" },
    redirect: "follow",
  });
  if (!resp.ok) throw new Error("status " + resp.status);
  return await resp.text();
}

// Parse one route's HTML: status word + verbatim `reported_as_of` + sections.
function parseRoute(html, route) {
  const text = html
    .replace(/<!--|-->/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&#160;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/[ \u00a0]+/g, " ")
    .trim();

  let reportedAsOf = "";
  const ts = text.match(/latest reported as of (.+?)(?=\.\s|\.$)/i);
  if (ts) reportedAsOf = ts[1].trim();

  // sections: [IN THE X AREA] ... (up to next [IN THE or end)
  const sectionRe = /\[IN THE ([A-Z ]+?) AREA\](.*?)(?=\[IN THE |$)/gs;
  const sections = [];
  let m;
  while ((m = sectionRe.exec(text)) !== null) {
    let body = m[2].replace(/\s+/g, " ").trim().replace(/^[. ]+|[. ]+$/g, "");
    if (!body) continue;
    if (/no traffic restrictions/i.test(body)) body = "No traffic restrictions reported.";
    sections.push({ region: m[1].trim(), text: body, status: sectionStatus(body) });
  }

  const status = classify(sections);
  let passStatus = status;
  if (route.pass) {
    const central = sections.find((s) => /CENTRAL/i.test(s.region));
    if (central) passStatus = central.status;
  }
  return {
    slug: route.slug, name: route.name, reported_as_of: reportedAsOf,
    status, pass_status: passStatus, sections,
  };
}

function sectionStatus(t) {
  if (/no (traffic )?(restrictions|closures?|incidents?|delays?)/i.test(t)) return "OPEN";
  if (/\bis\s+closed\b|\bare\s+closed\b|will be closed|is currently closed/i.test(t)) return "CLOSED";
  if (/\bclosed\b|\brestrictions?\b|chains|reduced to \d lane|one lane|two lanes closed|\bwind\b|\bfog\b|snow|traffic hazard|collision|disabled vehicle/i.test(t)) return "RESTRICTIONS";
  return "OPEN";
}

function classify(sections) {
  let worst = "OPEN";
  for (const s of sections) {
    const t = s.text;
    if (/no (traffic )?(restrictions|closures?|incidents?|delays?)/i.test(t)) continue;
    if (/\bis\s+closed\b|\bare\s+closed\b|will be closed|is currently closed/i.test(t)) return "CLOSED";
    if (/\bclosed\b|\brestrictions?\b|chains|reduced to \d lane|one lane|two lanes closed|\bwind\b|\bfog\b|snow|traffic hazard|collision|disabled vehicle/i.test(t)) worst = "RESTRICTIONS";
  }
  return worst;
}

export async function onRequestGet(context) {
  // serve from cache if fresh
  if (CACHE.data && Date.now() - CACHE.at < CACHE_MS) {
    return json(CACHE.data);
  }

  const routes = [];
  let lastErr = "";
  for (const r of ROUTES) {
    try {
      const html = await fetchCaltrans(r);
      if (html) routes.push(parseRoute(r, html));
    } catch (e) {
      lastErr = String(e && e.message ? e.message : e).slice(0, 120);
    }
  }

  const ok = routes.length > 0;
  const data = {
    ok, routes,
    status: ok ? "ok" : "unavailable",
    fetched_at: new Date().toISOString(),
    err: ok ? undefined : (lastErr || "fetch failed"),
    note: ok
      ? "Caltrans conditions, live via /api/pass-conditions."
      : "Caltrans unreachable right now — showing the last static build. Confirm before driving.",
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