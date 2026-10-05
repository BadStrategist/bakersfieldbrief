// Fog-delays live board (/fog-delays/).
//
// The static HTML is the crawlable base: the board as of the last build, with
// that build's check time. Districts post between about 4:30 and 6:30 AM, so
// this script asks /api/fog-delays (a Cloudflare Pages Function that reads the
// Kern County schools AlertLine) and redraws the board, the big count and the
// check time in place, then rechecks every three minutes while the page is open.
//
// Honesty rules:
//  - Rows are the districts' own words and timestamps, set with textContent.
//  - On any failure the static board stays exactly as built. We never guess.
(function () {
  "use strict";
  var board = document.getElementById("fog-board");
  if (!board) return;
  var big = document.getElementById("fog-big");
  var spoken = document.querySelectorAll(".fog-spoken");
  var filter = document.getElementById("fog-filter");
  var updated = document.querySelectorAll(".updated");
  var TAGS = { closure: ["red", "Closed"], delay: ["amber", "Delayed"], other: ["", "Alert"] };
  var FILTER_MIN = 8;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function slug(site) {
    return site.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  }

  // "2026-11-17 05:05:16" -> "5:05 AM". AlertLine stamps are Kern County local time.
  function clock(stamp) {
    var m = /(\d{2}):(\d{2})/.exec(stamp || "");
    if (!m) return "";
    var h = parseInt(m[1], 10);
    return ((h % 12) || 12) + ":" + m[2] + (h < 12 ? " AM" : " PM");
  }

  function statusText(a) {
    var desc = a.description || a.category || "Alert";
    if (desc.toLowerCase() === "custom" && a.info) return a.info;
    return a.info ? desc + ": " + a.info : desc;
  }

  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

  function headline(alerts) {
    var d = 0, c = 0, o = 0;
    alerts.forEach(function (a) {
      if (a.kind === "delay") d++; else if (a.kind === "closure") c++; else o++;
    });
    if (!alerts.length) {
      return { word: "No alerts posted", cls: "big-open", spoken: "no delays or closures are posted" };
    }
    var bits = [];
    if (d) bits.push(plural(d, "delay", "delays"));
    if (c) bits.push(plural(c, "closure", "closures"));
    if (o) bits.push(plural(o, "other alert", "other alerts"));
    return { word: bits.join(" · "), cls: c ? "big-closed" : "big-restrict",
             spoken: bits.join(" and ") + (alerts.length === 1 ? " is posted" : " are posted") };
  }

  function drawBoard(alerts) {
    board.textContent = "";
    if (!alerts.length) {
      board.appendChild(el("p", "note", "Nothing is posted on AlertLine right now."));
      return;
    }
    var wrap = el("div", "table-wrap");
    var table = el("table", "data");
    var head = el("tr");
    head.appendChild(el("th", "", "District or school"));
    head.appendChild(el("th", "", "Status"));
    head.appendChild(el("th", "num", "Posted"));
    var thead = el("thead");
    thead.appendChild(head);
    var tbody = el("tbody");
    alerts.forEach(function (a) {
      var tag = TAGS[a.kind] || TAGS.other;
      var tr = el("tr");
      tr.id = slug(a.site);
      var name = el("td");
      name.appendChild(el("strong", "", a.site));
      var status = el("td");
      status.appendChild(el("span", "tag " + tag[0], tag[1]));
      status.appendChild(document.createTextNode(" " + statusText(a)));
      tr.appendChild(name);
      tr.appendChild(status);
      tr.appendChild(el("td", "num", clock(a.updated_at)));
      tbody.appendChild(tr);
    });
    table.appendChild(thead);
    table.appendChild(tbody);
    wrap.appendChild(table);
    board.appendChild(wrap);
  }

  function applyFilter() {
    if (!filter) return;
    var q = filter.value.toLowerCase().trim();
    var rows = board.querySelectorAll("tbody tr");
    for (var i = 0; i < rows.length; i++) {
      rows[i].hidden = !!q && rows[i].textContent.toLowerCase().indexOf(q) === -1;
    }
  }

  function showFilter() {
    if (filter) filter.hidden = board.querySelectorAll("tbody tr").length < FILTER_MIN;
  }

  function apply(data) {
    var h = headline(data.alerts);
    var now = new Date(data.fetched_at || Date.now());
    var checked = now.toLocaleTimeString("en-US", {
      hour: "numeric", minute: "2-digit", timeZone: "America/Los_Angeles" })
      + " on " + now.toLocaleDateString("en-US", {
        weekday: "long", month: "long", day: "numeric", timeZone: "America/Los_Angeles" });
    drawBoard(data.alerts);
    showFilter();
    applyFilter();
    if (big) {
      if (!big.classList.contains("big-status")) {
        // Built while AlertLine was unreachable: swap the error box for the count.
        big.textContent = "";
        big.appendChild(el("p", "big-label", "Kern County schools · today"));
        big.appendChild(el("p", "big-word", ""));
        big.appendChild(el("p", "big-note", "Checked " + checked
          + ". A school that is not listed has posted nothing to AlertLine."));
      }
      big.className = "big-status " + h.cls;
      big.querySelector(".big-word").textContent = h.word;
    }
    var i;
    for (i = 0; i < spoken.length; i++) spoken[i].textContent = h.spoken;
    for (i = 0; i < updated.length; i++) updated[i].textContent = checked;
    // Someone sent a link to one district: bring its row into view once it exists.
    if (location.hash && !apply.jumped) {
      var target = document.getElementById(location.hash.slice(1));
      if (target) { target.scrollIntoView({ block: "center" }); apply.jumped = true; }
    }
  }

  function poll() {
    fetch("/api/fog-delays", { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.ok && Array.isArray(data.alerts)) apply(data);
      })
      .catch(function () { /* leave the static board as built */ });
  }

  if (filter) filter.addEventListener("input", applyFilter);
  showFilter();
  poll();
  setInterval(poll, 180000);
})();
