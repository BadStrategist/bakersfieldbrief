// Tehachapi weather live reading (/tehachapi-weather/).
//
// The static HTML carries the NWS observation from the last build. This script
// asks /api/tehachapi-weather (a Cloudflare Pages Function that reads the same
// NWS station) and, when the station has reported since the build, rewrites the
// direct answer, the "Right now" card and the observation time in place. It
// rechecks every ten minutes while the page is open.
//
// Honesty rules:
//  - Only a NEWER observation replaces the built one; an older or equal reading
//    is ignored, so the page never steps backwards.
//  - A variable the station did not report is left out of the sentence.
//  - On any failure the built reading stays exactly as it is.
(function () {
  "use strict";
  var now = document.getElementById("tw-now");
  if (!now) return;
  var answer = document.getElementById("tw-answer");
  var observed = document.getElementById("tw-observed");
  var shownTs = Date.parse(now.getAttribute("data-ts") || "") || 0;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function apply(d) {
    var wind = d.wind_mph != null
      ? d.wind_mph + " mph" + (d.gust_mph ? " (gusts to " + d.gust_mph + " mph)" : "")
        + " from " + (d.wind_dir || "?")
      : "";
    var bits = [d.temperature + "°F"];
    if (d.humidity != null) bits.push("humidity " + d.humidity + "%");
    if (wind) bits.push(wind);
    if (d.condition) bits.push(d.condition);

    now.className = "card";
    now.textContent = "";
    now.appendChild(el("h3", "", "Right now in Tehachapi"));
    var big = el("p", "big-word", bits.join(" · "));
    big.style.fontSize = "2rem";
    now.appendChild(big);
    var note = el("p", "note", "NWS station ");
    note.appendChild(el("strong", "", d.station));
    note.appendChild(document.createTextNode(" (Tehachapi), observed " + d.observed + "."));
    now.appendChild(note);

    if (answer) {
      answer.textContent = "";
      answer.appendChild(el("strong", "", "Right now it is " + d.temperature + "°F in Tehachapi"));
      answer.appendChild(document.createTextNode(
        (d.wind_mph != null ? " with " + d.wind_mph + " mph wind from " + (d.wind_dir || "?") : "")
        + (d.condition ? ", " + d.condition : "")
        + ". Observed by the NWS " + d.station + " at " + d.observed + "."));
    }
    if (observed) observed.textContent = d.observed;
  }

  function poll() {
    fetch("/api/tehachapi-weather", { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok || d.temperature == null) return;
        var ts = Date.parse(d.timestamp || "") || 0;
        if (ts <= shownTs) return;
        shownTs = ts;
        apply(d);
      })
      .catch(function () { /* keep the built reading */ });
  }

  poll();
  setInterval(poll, 600000);
})();
