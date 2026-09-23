// Live-conditions widget for the /roads/ hub (I-5 Grapevine, SR-58 Tehachapi, SR-99).
//
// The static HTML is the crawlable/AI base. This script upgrades it to REAL
// live data in the visitor's browser: it polls /api/pass-conditions (a
// Cloudflare Pages Function that server-side fetches Caltrans) and patches each
// route card's status tag, condition text, and timestamp in place. No cron, no
// LLM, no token spend.
//
// Honesty rules (same as live-pass.js):
//  - Always show Caltrans' own reported_as_of, never build time.
//  - On a fetch/API failure we leave the static content untouched and mark the
//    widget "unavailable" — we never guess a status.
//  - Each card is matched by data-route; only routes present in the payload
//    are patched.
(function () {
  "use strict";
  var path = location.pathname || "/";
  if (path.indexOf("/roads/") !== 0) return; // only run on the roads hub

  var LABELS = { OPEN: "Open", RESTRICTIONS: "Restrictions", CLOSED: "Closed" };
  var TAG_CLS = { OPEN: "green", RESTRICTIONS: "amber", CLOSED: "red" };

  var answer = document.querySelector("p.answer");
  var metaUpdated = document.querySelector(".meta .updated");

  var liveBadge = document.createElement("span");
  liveBadge.className = "live-badge";
  liveBadge.textContent = "● live";

  function cardFor(slug) {
    return document.querySelector('.card[data-route="' + slug + '"]');
  }

  function poll() {
    fetch("/api/pass-conditions", { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.ok || !Array.isArray(data.routes)) throw new Error("bad payload");
        applyRoutes(data.routes);
        liveBadge.classList.add("is-live");
      })
      .catch(function () { markUnavailable(); });
  }

  function applyRoutes(routes) {
    var parts = [];
    var newest = "";
    routes.forEach(function (rte) {
      var card = cardFor(rte.slug);
      var status = rte.pass_status || rte.status || "OPEN";
      var label = LABELS[status] || "Open";
      if (card) {
        var tag = card.querySelector(".tag");
        if (tag) { tag.textContent = status; tag.className = "tag " + (TAG_CLS[status] || "amber"); }
        var updated = card.querySelector(".updated");
        if (updated && rte.reported_as_of) {
          updated.textContent = rte.reported_as_of + ageHint(rte.reported_as_of);
        }
        // patch the condition list with verbatim section text
        if (rte.sections && rte.sections.length) {
          var ul = card.querySelector("ul.hl");
          if (ul) {
            ul.innerHTML = rte.sections.map(function (s) {
              return "<li><span class=\"tag " + (TAG_CLS[s.status] || "amber") + "\">" +
                     esc(s.status) + "</span><strong>" + esc(s.region) +
                     ":</strong> " + esc(s.text) + "</li>";
            }).join("");
          }
        }
      }
      if (rte.reported_as_of) {
        // keep the direct answer compact: route + status only (one shared
        // timestamp for the whole set, applied below) so it doesn't balloon on
        // mobile where the full per-route timestamps wrapped into a long block.
        parts.push(rte.slug.toUpperCase() + " " + status);
        if (!newest || rte.reported_as_of > newest) newest = rte.reported_as_of;
      }
    });
    if (answer && parts.length) {
      answer.innerHTML = "<strong>Live Caltrans report:</strong> " + esc(parts.join("; ")) +
        (newest ? " (as of " + esc(newest) + ")." : ".");
    }
    // refresh the header timestamp to match the cards so they never disagree
    if (metaUpdated && newest) {
      metaUpdated.textContent = newest + ageHint(newest);
    }
  }

  function markUnavailable() {
    if (metaUpdated) metaUpdated.textContent =
      metaUpdated.textContent + " (live check unavailable, showing the last update)";
    liveBadge.textContent = "○ showing the last update";
    liveBadge.classList.add("is-off");
  }

  function ageHint(asOf) {
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

  if (document.querySelector('.card[data-route]')) {
    poll();
    setInterval(poll, 60_000);
    var hero = document.querySelector(".pagehead .meta") ||
               document.querySelector(".hero .meta");
    if (hero && !document.querySelector(".live-badge")) hero.appendChild(liveBadge);
  }
})();
