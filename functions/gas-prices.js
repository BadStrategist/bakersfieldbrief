// Cloudflare Pages Function: /gas-prices/ is GONE.
//
// The page was deleted on 2026-08-10 (commit e02e0d4, "remove Openings/Gas
// Prices/Weather stubs + their data pulls") along with its builder and source,
// but a bare 404 leaves the URL sitting in Google's index: Search Console still
// reports it for two named queries over 180 days. Answer with a real 410 Gone so
// the removal is unambiguous, and point the visitor at what we do publish.
//
// Route: functions/gas-prices.js -> /gas-prices (and /gas-prices/).
export async function onRequest() {
  return gone("Gas prices");
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
<p>This page was removed from Bakersfield Daily Brief. It is gone, not moved.</p>
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
