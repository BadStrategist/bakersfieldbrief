// Cloudflare Pages Function: Caltrans traffic cameras in Kern County.
//
// /api/cameras            the camera list (JSON), from Caltrans' District 6 and 9 CCTV feeds
// /api/cameras?img=<id>   one camera's current still, fetched from Caltrans and held 60 s
//
// Why the stills are proxied instead of hotlinked: one copy per minute at the edge serves
// every reader, Caltrans sees this site and not each reader, and a failed picture becomes a
// plain 502 the page can turn into words.
//
// The picture address is always the `currentImageURL` Caltrans publishes for that camera.
// It is looked up in the feed, never assembled from the id: the two districts name their
// files differently and guessed addresses fail. <id> is only the key the lookup uses, the
// file name Caltrans itself gave the picture.
//
// Stills only. The feeds also list streaming video; this function never touches it.
//
// Honesty: a camera the feed marks out of service gets no picture (404), a picture Caltrans
// does not return is a 502, and the frame time passed on is Caltrans' own Last-Modified.

const FEEDS = [
  { district: "6", url: "https://cwwp2.dot.ca.gov/data/d6/cctv/cctvStatusD06.json" },
  { district: "9", url: "https://cwwp2.dot.ca.gov/data/d9/cctv/cctvStatusD09.json" },
];
const COUNTY = "Kern";
const IMAGE_HOST = "cwwp2.dot.ca.gov";
const UA = "BakersfieldDailyBrief/1.0 (+https://bakersfieldbrief.com)";
const LIST_FRESH_MS = 10 * 60 * 1000;   // re-read the feeds this often
const LIST_KEEP = 86400;                // and keep the last good list this long (seconds)
const IMG_TTL = 60;
const FAIL_TTL = 30;

function clean(v) {
  return String(v == null ? "" : v).replace(/\s+/g, " ").trim();
}

// Same key as build/sources/cameras.py camera_id(): the picture's file name without its extension.
function cameraId(imageUrl) {
  try {
    const name = new URL(imageUrl).pathname.split("/").pop() || "";
    return name.replace(/\.[a-z0-9]+$/i, "");
  } catch (e) {
    return "";
  }
}

function normalize(row) {
  const loc = row.location || {};
  const st = (row.imageData || {}).static || {};
  let url = clean(st.currentImageURL);
  try {
    const u = new URL(url);
    if (u.protocol !== "https:" || u.hostname !== IMAGE_HOST) url = "";
  } catch (e) {
    url = "";
  }
  const id = cameraId(url);
  if (!id) return null;
  const every = parseFloat(st.currentImageUpdateFrequency);
  return {
    id,
    district: clean(loc.district),
    caltrans_name: clean(loc.locationName),
    route: clean(loc.route),
    direction: clean(loc.direction),
    near: clean(loc.nearbyPlace),
    in_service: clean(row.inService).toLowerCase() === "true",
    update_min: every > 0 ? Math.round(every) : null,
    image_url: url,
  };
}

function kern(payload) {
  const out = [];
  for (const item of (payload && payload.data) || []) {
    const row = item && item.cctv ? item.cctv : item;
    if (!row || clean((row.location || {}).county) !== COUNTY) continue;
    const cam = normalize(row);
    if (cam) out.push(cam);
  }
  return out;
}

function listKey(request) {
  return new Request(new URL("/api/cameras?__list", request.url).toString());
}

// The Kern list, re-read every ten minutes. A district that cannot be read keeps its rows
// from the last good list, so one feed outage does not take its pictures off the page.
async function loadList(context) {
  const cache = caches.default;
  const key = listKey(context.request);
  let held = null;
  const hit = await cache.match(key);
  if (hit) {
    try { held = await hit.json(); } catch (e) { held = null; }
  }
  if (held && Date.now() - held.at < LIST_FRESH_MS) return held;

  const cameras = [];
  const stale = [];
  let fresh = 0;
  for (const feed of FEEDS) {
    let rows = null;
    try {
      const resp = await fetch(feed.url, { headers: { "Accept": "application/json", "User-Agent": UA } });
      if (resp.ok) rows = kern(await resp.json());
    } catch (e) {
      rows = null;
    }
    if (rows && rows.length) {
      cameras.push(...rows);
      fresh++;
    } else {
      stale.push(feed.district);
      if (held) cameras.push(...held.cameras.filter((c) => c.district === feed.district));
    }
  }
  if (!fresh) return held;      // nothing new: the last good list, or null when there is none
  const list = { at: Date.now(), cameras, stale_districts: stale };
  context.waitUntil(cache.put(key, new Response(JSON.stringify(list), {
    headers: { "Content-Type": "application/json", "Cache-Control": `public, max-age=${LIST_KEEP}` },
  })));
  return list;
}

function json(obj, status, maxAge) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": maxAge ? `public, max-age=${maxAge}` : "no-store",
    },
  });
}

function unavailable(id, reason, status) {
  return new Response(JSON.stringify({ ok: false, id, status: reason }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Camera-State": reason,
    },
  });
}

async function image(context, id) {
  const cache = caches.default;
  const base = new URL(context.request.url);
  const imgKey = new Request(new URL("/api/cameras?img=" + id, base).toString());
  const failKey = new Request(new URL("/api/cameras?fail=" + id, base).toString());

  const hit = await cache.match(imgKey);
  if (hit) return hit;
  // A failure is remembered for 30 s under its own key (an error status is not edge-cached),
  // so a dead camera costs Caltrans one request per half minute however many readers ask.
  const failed = await cache.match(failKey);
  if (failed) return unavailable(id, await failed.text(), 502);

  const list = await loadList(context);
  if (!list) return unavailable(id, "list_unreachable", 502);
  const cam = list.cameras.find((c) => c.id === id);
  if (!cam) return unavailable(id, "unknown_camera", 404);
  if (!cam.in_service) return unavailable(id, "out_of_service", 404);

  let reason = "";
  try {
    const up = await fetch(cam.image_url, { headers: { "Accept": "image/jpeg,image/*", "User-Agent": UA } });
    const type = up.headers.get("Content-Type") || "";
    if (!up.ok) reason = "http_" + up.status;
    else if (!type.toLowerCase().startsWith("image/")) reason = "not_an_image";
    else {
      const headers = {
        "Content-Type": type,
        "Cache-Control": `public, max-age=${IMG_TTL}`,
        "X-Content-Type-Options": "nosniff",
        "X-Camera-State": "ok",
      };
      const modified = up.headers.get("Last-Modified");
      if (modified) headers["Last-Modified"] = modified;
      const resp = new Response(await up.arrayBuffer(), { status: 200, headers });
      context.waitUntil(cache.put(imgKey, resp.clone()));
      return resp;
    }
  } catch (e) {
    reason = "unreachable";
  }
  context.waitUntil(cache.put(failKey, new Response(reason, {
    headers: { "Content-Type": "text/plain", "Cache-Control": `public, max-age=${FAIL_TTL}` },
  })));
  return unavailable(id, reason, 502);
}

export async function onRequestGet(context) {
  const params = new URL(context.request.url).searchParams;
  const id = params.get("img");
  if (id !== null) {
    if (!/^[A-Za-z0-9_-]{1,80}$/.test(id)) return unavailable("", "bad_id", 400);
    return image(context, id);
  }
  const list = await loadList(context);
  if (!list) return json({ ok: false, status: "list_unreachable" }, 200, FAIL_TTL);
  const cameras = list.cameras.map((c) => ({
    id: c.id, district: c.district, caltrans_name: c.caltrans_name, route: c.route,
    direction: c.direction, near: c.near, in_service: c.in_service, update_min: c.update_min,
  }));
  return json({
    ok: true, status: "ok", count: cameras.length,
    in_service: cameras.filter((c) => c.in_service).length,
    stale_districts: list.stale_districts || [],
    list_read_at: new Date(list.at).toISOString(),
    cameras,
  }, 200, IMG_TTL);
}
