// Active-fires live widget (daily brief Conditions strip + optional fires list).
//
// The static HTML is the crawlable/AI base (honest build-time count). This
// script upgrades it to REAL live data in the visitor's browser: it polls
// /api/fires (a Cloudflare Pages Function that server-side fetches CAL FIRE)
// and patches the "Active fires" chip count and — when a fires-list container
// exists — each fire's line (name, acres, containment, location) in place.
// No cron, no LLM, no token spend.
//
// Honesty rules baked in:
//  - We ALWAYS show CAL FIRE's own values via the API, never build time,
//    never our own guess.
//  - On a fetch/API failure we leave the static content untouched and mark
//    the widget as "unavailable" — we never fabricate a count or a fire.
//  - We only patch the fire chip (matched by its "Active fires" label), so
//    the other condition chips still read their static state.
(function () {
  "use strict";

  // Locate the "Active fires" chip in the Conditions strip.
  function fireChip() {
    var chips = document.querySelectorAll(".cond-chip");
    for (var i = 0; i < chips.length; i++) {
      var l = chips[i].querySelector(".l");
      if (l && /active fires/i.test(l.textContent || "")) return chips[i];
    }
    return null;
  }

  var chip = fireChip();
  var chipValue = chip && chip.querySelector(".v");
  // Optional per-fire list container (wired in by the page template). If it
  // is absent we still live-update the count chip and skip the list.
  var listEl = document.querySelector("[data-fires-list]") ||
               document.querySelector(".fires-list") ||
               document.querySelector("#fires-list");

  // add a lightweight live indicator next to the Conditions section head
  var liveBadge = document.createElement("span");
  liveBadge.className = "live-badge";
  liveBadge.textContent = "● live";

  var started = false;
  function poll() {
    fetch("/api/fires", { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.ok || !Array.isArray(data.incidents)) throw new Error("bad payload");
        apply(data);
        // keep the badge subtle once we've successfully gone live once
        liveBadge.classList.add("is-live");
      })
      .catch(function () {
        // fail-open: leave static content, mark unavailable
        markUnavailable();
      });
  }

  function apply(data) {
    var kern = data.kern || [];
    var n = kern.length;
    var word = n + " in Kern";

    // On the /fires/ tracker page, update the map-overlay counts + asof and
    // render the per-fire list into #fires-list.
    var kernEl = document.querySelector("#fire-kern-count");
    var caEl = document.querySelector("#fire-ca-count");
    var asofEl = document.querySelector("#fire-asof");
    if (kernEl) kernEl.textContent = data.kern_count;
    if (caEl) caEl.textContent = data.total;
    if (asofEl) {
      asofEl.textContent = data.fetched_at ? ago(data.fetched_at) : "";
      // keep the "data as of" label honest
    }

    // Homepage Conditions-strip chip (if present).
    if (chipValue) chipValue.textContent = word;

    if (listEl) {
      var html;
      if (n === 0) {
        html = '<p class="note">No active CAL FIRE incidents in Kern County right now.</p>';
      } else {
        var rows = kern.map(function (f) {
          var line = esc(f.name || "Unnamed incident");
          var parts = [];
          if (f.acres !== "") parts.push(f.acres + " acres");
          if (f.contained !== "") parts.push(f.contained + "% contained");
          if (f.location !== "") parts.push(esc(String(f.location)));
          if (parts.length) line += " &mdash; " + parts.join(" · ");
          if (f.url) line = '<a href="' + esc(f.url) + '" rel="noopener" target="_blank">' + line + "</a>";
          return '<li>' + line + "</li>";
        }).join("");
        html = "<ul class=\"fires-list-rows\">" + rows + "</ul>";
      }
      listEl.innerHTML = html;
    }

    liveBadge.textContent = "● live · updated " + (data.fetched_at ? ago(data.fetched_at) : "now");
  }

  function markUnavailable() {
    if (chipValue && chipValue.textContent.indexOf("Unavailable") === -1) {
      chipValue.textContent = chipValue.textContent + " (live feed unavailable — showing last static build)";
    }
    // On the /fires/ page, mark the overlay counts honestly too.
    var kernEl = document.querySelector("#fire-kern-count");
    var caEl = document.querySelector("#fire-ca-count");
    if (kernEl) kernEl.textContent = "unavailable";
    if (caEl) caEl.textContent = "unavailable";
    liveBadge.textContent = "○ live feed unavailable";
    liveBadge.classList.add("is-off");
  }

  function ago(iso) {
    // iso: ISO 8601 UTC e.g. "2026-09-07T18:04:11.000Z"
    try {
      var t = new Date(iso);
      if (isNaN(t)) return "";
      var mins = Math.max(0, Math.round((Date.now() - t.getTime()) / 60000));
      if (mins < 1) return "just now";
      if (mins < 60) return mins + " min ago";
      var h = Math.floor(mins / 60);
      if (h < 24) return h + " hr" + (h === 1 ? "" : "s") + " ago";
      return Math.floor(h / 24) + " day" + (h >= 48 ? "s" : "") + " ago";
    } catch (e) { return ""; }
  }

  function esc(s) {
    var d = document.createElement("div"); d.textContent = String(s); return d.innerHTML;
  }

  // Run when we're on the /fires/ tracker page (has the overlay ids) OR the
  // homepage Conditions strip (has the chip). Both get live-updated.
  var onFires = !!document.querySelector("#fire-kern-count");
  if ((chip && chipValue) || onFires) {
    if (!started) {
      poll();
      setInterval(poll, 60_000);
      started = true;
    }
    // inject the badge into the Conditions section head if present
    var head = document.querySelector("#h-conditions");
    if (head && !document.querySelector(".live-badge")) {
      head.appendChild(liveBadge);
    }
  }
})();
