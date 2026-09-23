// Pass-conditions live widget (grapevine + tehachapi-pass pages).
//
// The static HTML is the crawlable/AI base (FAQ schema, direct answer, honest
// "as of" timestamp). This script upgrades it to REAL live data in the
// visitor's browser: it polls /api/pass-conditions (a Cloudflare Pages
// Function that server-side fetches Caltrans) and patches the status word,
// color, and timestamp in place. No cron, no LLM, no token spend.
//
// Honesty rules baked in:
//  - We ALWAYS show Caltrans' own reported_as_of (via the API), never build time.
//  - On a fetch/API failure we leave the static content untouched and mark the
//    widget as "unavailable" — we never guess a status.
//  - We only patch the route this page is about (i5 vs sr58), so the alternate
//    cards still read their static state.
(function () {
  "use strict";
  // Determine which pass this page is about from the URL (no template changes).
  var path = location.pathname || "/";
  var ROUTE = path.indexOf("/tehachapi-pass/") === 0 ? "sr58"
             : (path.indexOf("/grapevine/") === 0 ? "i5" : null);
  if (!ROUTE) return;
  var LABELS = { OPEN: "Open", RESTRICTIONS: "Restrictions", CLOSED: "Closed" };
  var CLS = { OPEN: "big-open", RESTRICTIONS: "big-restrict", CLOSED: "big-closed" };

  var bigStatus = document.querySelector(".big-status");
  var bigWord = bigStatus && bigStatus.querySelector(".big-word");
  var metaUpdated = document.querySelector(".meta .updated");
  // the direct quotable answer (first text after H1)
  var answer = document.querySelector("p.answer");

  // add a lightweight live indicator next to the header
  var liveBadge = document.createElement("span");
  liveBadge.className = "live-badge";
  liveBadge.textContent = "● live";

  var started = false;
  function poll() {
    fetch("/api/pass-conditions", { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.ok || !Array.isArray(data.routes)) throw new Error("bad payload");
        var rte = data.routes.filter(function (r) { return r.slug === ROUTE; })[0];
        if (!rte) throw new Error("route missing: " + ROUTE);
        apply(rte);
        // keep the badge subtle once we've successfully gone live once
        liveBadge.classList.add("is-live");
      })
      .catch(function () {
        // fail-open: leave static content, mark unavailable
        markUnavailable();
      });
  }

  function apply(rte) {
    var status = rte.pass_status || rte.status || "OPEN";
    var label = LABELS[status] || "Open";
    if (bigStatus && bigWord) {
      bigStatus.className = "big-status " + (CLS[status] || "big-open");
      bigWord.textContent = label;
    }
    if (rte.reported_as_of && metaUpdated) {
      metaUpdated.textContent = rte.reported_as_of + ageHint(rte.reported_as_of);
    }
    if (rte.sections && rte.sections.length && answer) {
      // refresh the verbatim condition text under the answer
      var note = rte.sections.map(function (s) { return s.text; }).join(" ").trim();
      if (note) answer.innerHTML = "SR-58 is reported <strong>" + label + "</strong> by Caltrans " +
        "(Central California area) — live. " + esc(note);
    }
    liveBadge.textContent = "● live · updated " + (rte.reported_as_of || "now");
  }

  function markUnavailable() {
    if (metaUpdated) metaUpdated.textContent =
      metaUpdated.textContent + " (live check unavailable, showing the last update)";
    liveBadge.textContent = "○ showing the last update";
    liveBadge.classList.add("is-off");
  }

  function ageHint(asOf) {
    // asOf: "Saturday, September 5th, 2026 at 08:16 PM" (Pacific)
    try {
      var clean = asOf.replace(" at ", ", ").replace(/(\d+)(st|nd|rd|th)/, "$1");
      var t = new Date(clean + " GMT-07:00");
      if (isNaN(t)) return "";
      var mins = Math.max(0, Math.round((Date.now() - t.getTime()) / 60000));
      if (mins < 1) return " (just now)";
      if (mins < 60) return " (" + mins + " min ago)";
      var h = Math.floor(mins / 60);
      if (h < 24) return " (" + h + " hr" + (h === 1 ? "" : "s") + " ago)";
      return " (" + Math.floor(h / 24) + " day" + (h >= 48 ? "s" : "") + " ago)";
    } catch (e) { return ""; }
  }

  function esc(s) {
    var d = document.createElement("div"); d.textContent = s; return d.innerHTML;
  }

  if (bigStatus && bigWord && metaUpdated) {
    if (!started) {
      poll();
      setInterval(poll, 60_000);
      started = true;
    }
    // inject the badge into the hero meta
    var hero = document.querySelector(".pagehead .meta") ||
               document.querySelector(".hero .meta");
    if (hero && !document.querySelector(".live-badge")) {
      hero.appendChild(liveBadge);
    }
  }
})();