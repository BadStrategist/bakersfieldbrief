// Cloudflare Pages Function: /weather/ is GONE.
//
// The generic weather stub was deleted on 2026-08-10 (commit e02e0d4). Weather
// still appears on the site, but as real live data: the brief's conditions block
// (NWS) and /tehachapi-weather/. This URL is not moved, it is removed, so answer
// 410 rather than letting a 404 linger in the index.
//
// Route: functions/weather.js -> /weather (and /weather/).
export async function onRequest() {
  return gone("The old weather page");
}

function gone(what) {
  return new Response(
    `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="robots" content="noindex">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>410 Gone | Bakersfield Daily Brief</title>
<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:38rem;
margin:12vh auto;padding:0 1.25rem;line-height:1.6;color:#1a1a1a}
a{color:#b3261e}h1{font-size:1.5rem;margin:0 0 .5rem}p{margin:.75rem 0}</style></head>
<body><h1>${what} is no longer published</h1>
<p>This page was removed from Bakersfield Daily Brief. For weather, the
<a href="/">daily brief</a> carries current conditions and alerts, and
<a href="/tehachapi-weather/">Tehachapi weather</a> covers the pass.</p>
<p>What we do publish: <a href="/trackers/">live Kern County data trackers</a>,
<a href="/roads/">highway conditions</a>, or <a href="/">today&rsquo;s brief</a>.</p>
</body></html>`,
    {
      status: 410,
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "public, max-age=86400",
        "x-robots-tag": "noindex",
      },
    }
  );
}
