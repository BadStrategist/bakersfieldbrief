// Lake Isabella newer-reading notice (/water/).
//
// The lake is reported once a day, and every figure on this page (the level,
// the chart, the week-over-week change, the FAQ) is computed from the reading
// the page was built with. Rewriting some of those in the browser and not the
// rest would leave the page disagreeing with itself.
//
// So this script does one thing: it asks /api/lake-isabella (a Cloudflare Pages
// Function that reads the same CDEC series) and, when CDEC has posted a day the
// page does not have yet, adds a notice above the level card with that reading
// and says plainly that the rest of the page is a day behind.
//
// On any failure, or when there is nothing newer, the page is left untouched.
(function () {
  "use strict";
  var card = document.getElementById("isb-now");
  if (!card) return;
  var built = card.getAttribute("data-reading-date") || "";
  if (!built) return;

  function longDate(iso) {
    var p = iso.split("-");
    return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])).toLocaleDateString("en-US", {
      month: "long", day: "numeric", timeZone: "UTC" });
  }

  function num(n, digits) {
    return n.toLocaleString("en-US", { minimumFractionDigits: digits || 0,
                                       maximumFractionDigits: digits || 0 });
  }

  fetch("/api/lake-isabella", { headers: { "Accept": "application/json" } })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d || !d.ok || !d.storage || d.storage.date <= built) return;
      var note = document.createElement("div");
      note.className = "card";
      var p = document.createElement("p");
      var lead = document.createElement("strong");
      lead.textContent = "Newer reading, " + longDate(d.storage.date) + ": ";
      p.appendChild(lead);
      var level = d.elev && d.elev.date === d.storage.date
        ? num(d.elev.value, 2) + " feet elevation, " : "";
      p.appendChild(document.createTextNode(
        level + num(d.storage.value) + " acre-feet (" + d.pct + "% of capacity). "
        + "The rest of this page still shows the " + longDate(built)
        + " reading and catches up at the next rebuild."));
      note.appendChild(p);
      card.parentNode.insertBefore(note, card);
    })
    .catch(function () { /* nothing newer to show */ });
})();
