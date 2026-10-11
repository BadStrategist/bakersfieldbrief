// Caltrans camera cards (/traffic-cameras/ and the blocks on the road trackers).
//
// The static HTML is the crawlable base: every camera's name, route and place, the plain
// <img> for each one, and the two empty states. This script adds three things:
//  - the age of each picture, read from the Last-Modified header Caltrans sends with it;
//  - a new picture on the camera's own schedule while its card is on screen;
//  - a larger picture when a card is tapped.
//
// Honesty rules:
//  - A picture that does not load shows "Picture unavailable right now". The card keeps its
//    name, route and place, and is tried again on the next round.
//  - A picture with no Last-Modified says its time is not available. It never prints a zero.
//  - Caltrans sometimes sends its own "Temporarily Unavailable" card for a camera it still
//    lists as in service. The card is shown as it arrives and the line under it says so.
//  - Pictures come from /api/cameras?img=<id>, which looks the address up in Caltrans' list.
//  - Auto-refresh stops after twenty minutes so a forgotten tab does not keep asking.
(function () {
  "use strict";
  var cards = Array.prototype.slice.call(document.querySelectorAll(".cam[data-cam]"))
    .filter(function (el) { return !el.classList.contains("is-out") && el.querySelector("img"); });
  if (!cards.length || !window.fetch) return;

  var TICK_MS = 30000;
  var AUTO_MS = 20 * 60000;
  var OLD_MIN = 30;
  var started = Date.now();
  var state = {};            // camera id -> { at: Date|null, loaded: ms, url: objectURL, busy }
  var open = null;           // the card shown in the larger view

  function img(card) { return card.querySelector("img"); }
  function ageEl(card) { return card.querySelector(".cam-age"); }

  function clock(d) {
    return d.toLocaleTimeString("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit" });
  }

  function ago(mins) {
    if (mins < 1) return "under a minute ago";
    if (mins < 60) return mins + " min ago";
    var h = Math.floor(mins / 60);
    if (h < 24) return h + " hr ago";
    var d = Math.floor(h / 24);
    return d + (d === 1 ? " day ago" : " days ago");
  }

  function ageText(s) {
    if (!s || !s.loaded) return null;
    if (s.notice) return { text: "Caltrans is showing a notice in place of this picture", old: false, notice: true };
    if (!s.at) return { text: "Picture time not available", old: false };
    var mins = Math.max(0, Math.floor((Date.now() - s.at.getTime()) / 60000));
    return { text: (mins > OLD_MIN ? "Old picture: " : "Picture from ") + clock(s.at) + ", " + ago(mins),
             old: mins > OLD_MIN };
  }

  function paint(card) {
    var s = state[card.dataset.cam];
    var a = ageText(s);
    var el = ageEl(card);
    if (el && a && !card.classList.contains("is-error")) el.textContent = a.text;
    card.classList.toggle("is-old", !!(a && a.old));
    card.classList.toggle("is-notice", !!(a && a.notice));
    if (open === card) paintBox();
  }

  function fail(card) {
    card.classList.add("is-error");
    card.classList.remove("is-old");
    card.classList.remove("is-notice");
    var el = ageEl(card);
    if (el) el.textContent = "Caltrans did not return a picture. It is tried again shortly.";
    if (open === card) paintBox();
  }

  // Caltrans' notice card is white with dark blue words above the usual time bar. A road in
  // fog or snow is pale too but has no dark blue in it, so both tests must pass.
  function isNotice(url, done) {
    var im = new Image();
    im.onload = function () {
      try {
        var cv = document.createElement("canvas");
        cv.width = im.naturalWidth; cv.height = im.naturalHeight;
        var cx = cv.getContext("2d");
        cx.drawImage(im, 0, 0);
        var h = Math.floor(cv.height * 0.79);
        var px = cx.getImageData(0, 0, cv.width, h).data, n = px.length / 4, white = 0, navy = 0;
        for (var i = 0; i < px.length; i += 4) {
          var r = px[i], g = px[i + 1], b = px[i + 2];
          if (r > 235 && g > 235 && b > 235) white++;
          else if (b > r + 40 && r < 70) navy++;
        }
        done(white / n > 0.8 && navy / n > 0.01);
      } catch (e) { done(false); }
    };
    im.onerror = function () { done(false); };
    im.src = url;
  }

  function load(card, force) {
    var id = card.dataset.cam;
    var s = state[id] || (state[id] = { at: null, loaded: 0, url: "", busy: false, notice: false });
    if (s.busy) return;
    s.busy = true;
    fetch("/api/cameras?img=" + encodeURIComponent(id), force ? { cache: "no-cache" } : {})
      .then(function (r) {
        if (!r.ok) throw new Error("http " + r.status);
        var lm = r.headers.get("Last-Modified");
        var at = lm ? new Date(lm) : null;
        s.at = at && !isNaN(at.getTime()) ? at : null;
        return r.blob();
      })
      .then(function (blob) {
        if (!blob.size) throw new Error("empty picture");
        var old = s.url;
        s.url = URL.createObjectURL(blob);
        s.loaded = Date.now();
        var el = ageEl(card);
        if (card.classList.contains("is-error") && el && el.dataset.default) el.textContent = el.dataset.default;
        card.classList.remove("is-error");
        img(card).src = s.url;
        if (old) setTimeout(function () { URL.revokeObjectURL(old); }, 5000);
        paint(card);
        isNotice(s.url, function (yes) { s.notice = yes; paint(card); });
      })
      .catch(function () { fail(card); })
      .then(function () { s.busy = false; });
  }

  // The page's own <img> has already asked for the picture. Wait for it, so the request
  // that reads the picture's time is answered from the browser cache and not sent twice.
  function first(card) {
    var im = img(card);
    if (im.complete) { load(card, false); return; }
    var once = function () {
      im.removeEventListener("load", once);
      im.removeEventListener("error", once);
      if (!(state[card.dataset.cam] && state[card.dataset.cam].loaded)) load(card, false);
    };
    im.addEventListener("load", once);
    im.addEventListener("error", once);
  }

  // ---------- which cards are on screen
  var visible = {};
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        var id = e.target.dataset.cam;
        visible[id] = e.isIntersecting;
        if (e.isIntersecting && !(state[id] && state[id].loaded)) first(e.target);
      });
    }, { rootMargin: "200px 0px" });
    cards.forEach(function (c) { io.observe(c); });
  } else {
    cards.forEach(function (c) { visible[c.dataset.cam] = true; first(c); });
  }

  function everyMs(card) {
    var m = parseFloat(card.dataset.every);
    return (m > 0 ? m : 1) * 60000;
  }

  function tick() {
    if (document.hidden) return;
    var auto = Date.now() - started < AUTO_MS;
    cards.forEach(function (card) {
      var s = state[card.dataset.cam];
      paint(card);
      if (!auto || !visible[card.dataset.cam]) return;
      var due = card.classList.contains("is-error") ? TICK_MS : everyMs(card);
      if (!s || Date.now() - s.loaded >= due) load(card, false);
    });
    if (!auto) refreshButtons.forEach(function (b) { b.textContent = "Paused. Refresh pictures"; });
  }
  setInterval(tick, TICK_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) tick(); });

  var refreshButtons = Array.prototype.slice.call(document.querySelectorAll(".cam-refresh"));
  refreshButtons.forEach(function (b) {
    b.hidden = false;
    b.addEventListener("click", function () {
      started = Date.now();
      b.textContent = "Refresh pictures";
      cards.forEach(function (card) { if (visible[card.dataset.cam]) load(card, true); });
    });
  });

  // ---------- the larger picture
  var box = null, boxImg, boxTitle, boxAge, boxFacts, boxFlag;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function buildBox() {
    box = el("dialog", "lb");
    box.setAttribute("aria-labelledby", "lb-title");
    box.appendChild(el("div", "lb-bar"));
    var head = el("div", "lb-head");
    boxTitle = el("h2", "", "");
    boxTitle.id = "lb-title";
    var close = el("button", "lb-close", "\u00d7");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.addEventListener("click", function () { box.close(); });
    head.appendChild(boxTitle);
    head.appendChild(close);
    box.appendChild(head);
    var pic = el("div", "lb-pic");
    boxImg = el("img");
    boxImg.width = 320;
    boxImg.height = 260;
    boxFlag = el("span", "cam-flag", "Picture unavailable right now");
    pic.appendChild(boxImg);
    pic.appendChild(boxFlag);
    box.appendChild(pic);
    boxAge = el("p", "lb-cap", "");
    boxAge.setAttribute("aria-live", "polite");
    box.appendChild(boxAge);
    boxFacts = el("ul", "lb-facts");
    box.appendChild(boxFacts);
    box.appendChild(el("p", "lb-src", "Picture: Caltrans. It is 320 by 260 pixels at the source and is shown here enlarged."));
    box.addEventListener("click", function (e) { if (e.target === box) box.close(); });
    box.addEventListener("close", function () { open = null; });
    document.body.appendChild(box);
  }

  function fact(k, v) {
    if (!v) return;
    var li = el("li");
    li.appendChild(el("span", "k", k));
    li.appendChild(el("span", "v", v));
    boxFacts.appendChild(li);
  }

  function paintBox() {
    if (!open) return;
    var s = state[open.dataset.cam];
    var bad = open.classList.contains("is-error") || !s || !s.url;
    boxImg.hidden = bad;
    boxFlag.hidden = !bad;
    if (!bad && boxImg.getAttribute("src") !== s.url) boxImg.src = s.url;
    boxImg.alt = img(open).alt;
    var a = ageText(s);
    boxAge.textContent = bad ? "Caltrans did not return a picture. It is tried again shortly."
      : (a ? a.text : "");
  }

  function show(card) {
    if (!box) buildBox();
    open = card;
    var d = card.dataset;
    boxTitle.textContent = d.label || card.querySelector(".cam-name").textContent;
    boxFacts.textContent = "";
    var meta = card.querySelector(".cam-meta");
    fact("Where", meta ? meta.textContent : "");
    fact("Elevation", d.elev ? Number(d.elev).toLocaleString("en-US") + " ft" : "");
    fact("New picture", d.every ? (d.every === "1" ? "about every minute" : "about every " + d.every + " minutes") : "");
    fact("Caltrans name", d.caltransName || "");
    fact("Run by", d.district ? "Caltrans District " + d.district : "");
    paintBox();
    box.showModal();
    if (!(state[d.cam] && state[d.cam].loaded)) load(card, false);
  }

  if (typeof HTMLDialogElement === "function") {
    cards.forEach(function (card) {
      var link = card.querySelector(".cam-open");
      if (!link) return;
      link.addEventListener("click", function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;   // let a new-tab click through
        e.preventDefault();
        show(card);
      });
    });
  }

  // ---------- a newer Caltrans road report than the one this page was built with
  var answer = document.getElementById("road-answer");
  var newer = document.getElementById("road-newer");
  if (answer && newer && answer.dataset.asof) {
    fetch("/api/pass-conditions", { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.ok || !Array.isArray(data.routes)) return;
        var live = "";
        data.routes.forEach(function (rte) { if (!live && rte.reported_as_of) live = rte.reported_as_of; });
        if (!live || live === answer.dataset.asof) return;
        newer.textContent = "Caltrans has posted a newer road report (" + live + ") than the one above. ";
        var a = el("a", "", "See current Kern County road conditions");
        a.href = "/roads/";
        newer.appendChild(a);
        newer.appendChild(document.createTextNode("."));
        newer.hidden = false;
      })
      .catch(function () { /* the built status stays as it is */ });
  }
})();
