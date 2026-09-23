/* Bakersfield Daily Brief: alpr-explorer.js
   The Flock & ALPR camera map and land ownership explorer on /surveillance/.

   Progressive enhancement. The page already carries every camera, owner and parcel as HTML lists
   (crawlable, and readable with JavaScript off). This script adds:
     - the Leaflet map of every OSM camera (from #tracker-data, inlined at build time), with
       clusters, a "new in 28 days" ring and facing cones at street zoom;
     - filters that drive the lists and the map together;
     - full records at #camera/<id>, #owner/<n>, #parcel/<n>, opened from the data file named in
       #explorer[data-src]. Hash routes are not pages: /surveillance/ is the only ALPR url.
   Wheel zoom is off so a wheel over the map scrolls the page; Ctrl (or Cmd) + wheel zooms.
   Copy rule: a camera stands "at or beside" an owner's land. Never "the parcel under it".
*/
(function () {
  "use strict";

  var root = document.getElementById("explorer");
  if (!root) return;

  /* ---------------- data ---------------- */
  var T = {};
  try { T = JSON.parse((document.getElementById("tracker-data") || {}).textContent || "{}") || {}; }
  catch (e) { T = {}; }
  var ASOF = T.asof || "";
  var CUTOFF = "";
  if (ASOF) {
    var d0 = new Date(String(ASOF).slice(0, 10) + "T00:00:00Z");
    if (!isNaN(d0)) { d0.setUTCDate(d0.getUTCDate() - 28); CUTOFF = d0.toISOString().slice(0, 10); }
  }

  var CAM = {};            // id -> camera (OSM facts + list item + marker)
  var CAM_LIST = [];
  (T.cameras || []).forEach(function (c) {
    if (c.lat == null || c.lon == null) return;
    var id = String(c.id);
    var cam = {
      id: id, lat: +c.lat, lon: +c.lon, manu: c.manufacturer || "Unspecified",
      op: c.operator || "", dir: c.direction || "", mapped: c.mapped || "",
      isNew: !!(CUTOFF && c.mapped && c.mapped >= CUTOFF),
      flock: String(c.manufacturer || "").toLowerCase().indexOf("flock") > -1
    };
    CAM[id] = cam; CAM_LIST.push(cam);
  });

  var OWN = null, OWN_CAM = {};
  var src = root.getAttribute("data-src");
  var ownReady = (src && window.fetch)
    ? fetch(src, { credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) { OWN = d; (d.cams || []).forEach(function (c) { OWN_CAM[String(c.id)] = c; }); return d; })
        .catch(function () { return null; })
    : Promise.resolve(null);

  /* ---------------- helpers ---------------- */
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return (s == null ? "" : String(s)).replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m];
    });
  }
  function fmt(n) { return (n === null || n === undefined || n === "") ? "not stated" : Number(n).toLocaleString("en-US"); }
  function money(n) { return Number(n).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }); }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
  var wide = window.matchMedia ? window.matchMedia("(min-width: 960px)") : { matches: true };

  var C16 = ["north", "north-northeast", "northeast", "east-northeast", "east", "east-southeast", "southeast",
    "south-southeast", "south", "south-southwest", "southwest", "west-southwest", "west", "west-northwest",
    "northwest", "north-northwest"];
  function dirArcs(v) {
    var out = [];
    String(v || "").split(";").forEach(function (part) {
      part = part.trim(); if (!part) return;
      var m = part.match(/^(\d{1,3})\s*[-:]\s*(\d{1,3})$/);
      if (m) out.push({ a: +m[1] % 360, b: +m[2] % 360 });
      else if (/^\d{1,3}$/.test(part)) { var d = +part % 360; out.push({ a: d, b: d }); }
    });
    return out;
  }
  function dirText(v) {
    return dirArcs(v).map(function (x) {
      return x.a === x.b ? (x.a + "° " + C16[Math.round(x.a / 22.5) % 16]) : (x.a + "° to " + x.b + "°");
    }).join(", ");
  }
  function shortAddr(a) {
    var keep = [];
    String(a || "").split(",").forEach(function (p) {
      p = p.trim();
      if (!p || /^(Bakersfield|Kern County|California|CA|United States|USA|US)$/i.test(p) || /^\d{5}(-\d{4})?$/.test(p)) return;
      keep.push(p);
    });
    if (keep.length > 1 && /^\d+$/.test(keep[0])) keep.splice(0, 2, keep[0] + " " + keep[1]);
    return keep.join(", ");
  }
  function locOf(id) {
    var o = OWN_CAM[id];
    return (o && (o.loc || shortAddr(o.addr))) || "Camera " + id;
  }
  function kindOf(t) {
    t = String(t || "").toLowerCase();
    if (t === "government") return "agency";
    if (t === "entity") return "entity";
    if (t === "individual" || t === "person" || t === "trust") return "private";
    return "other";
  }
  var KIND_LABEL = { agency: "public agency", entity: "company", private: "private owner", other: "owner" };
  function kindChip(t) { var k = kindOf(t); return '<span class="ax-chip ' + k + '">' + KIND_LABEL[k] + "</span>"; }
  function relation(c) {
    if (/Street\/ROW/.test(c.land || "")) return "in the street beside";
    if (/inside/.test(c.match || "")) return "on";
    return "beside";
  }
  function link(u, label) {
    return '<a href="' + esc(u) + '" target="_blank" rel="noopener">' + esc(label || u.replace(/^https?:\/\//, "")) + "</a>";
  }
  function contactLink(v) {
    if (!v) return "";
    return (v.indexOf("@") > -1 && v.indexOf("://") === -1) ? '<a href="mailto:' + esc(v) + '">' + esc(v) + "</a>" : link(v);
  }
  function tel(ph, label) {
    return '<a href="tel:+1' + esc(String(ph).replace(/[^0-9]/g, "").replace(/^1(?=\d{10}$)/, "")) + '">' + esc(label || ph) + "</a>";
  }
  var liveEl = document.createElement("p");
  liveEl.className = "sr"; liveEl.setAttribute("role", "status"); liveEl.setAttribute("aria-live", "polite");
  root.appendChild(liveEl);
  function say(m) { liveEl.textContent = m; }

  /* ---------------- lists, tabs, filters ---------------- */
  var lists = { cams: $("ax-l-cams"), owners: $("ax-l-owners"), parcels: $("ax-l-parcels") };
  var tabs = { cams: $("ax-t-cams"), owners: $("ax-t-owners"), parcels: $("ax-t-parcels") };
  var countEl = $("ax-count"), emptyEl = $("ax-empty"), moreEl = $("ax-more");
  var detailEl = $("ax-detail"), scrollEl = $("ax-scroll"), panel = $("ax-panel");
  var state = { tab: "cams", filter: "all", expanded: false, record: null };
  var NOUN = { cams: ["camera", "cameras"], owners: ["owner", "owners"], parcels: ["parcel", "parcels"] };
  var PAGE = 20;   // rows shown on a phone before "Show all"

  [].forEach.call(lists.cams.querySelectorAll("li[data-id]"), function (li) {
    var c = CAM[li.getAttribute("data-id")];
    if (c) { c.li = li; c.k = li.getAttribute("data-k"); }
  });

  // Filters only: there is no search box on this page. Every chip pairs with a data-k on the
  // server-rendered lists, so a filter works with the map and with JavaScript off.
  function passes(li, name) {
    var f = state.filter, k = li.getAttribute("data-k");
    if (f === "all") return true;
    if (f === "new" || f === "flock") {
      if (name === "cams" && !li.hasAttribute("data-" + f)) return false;
    } else if (k !== f) return false;
    return true;
  }

  function apply(fromSearch) {
    // An open record owns the panel: re-filtering (a resize, a filter tap) must not paint the list
    // controls over it.
    if (state.record) { moreEl.hidden = true; emptyEl.hidden = true; drawMarkers(fromSearch); return; }
    var name = state.tab, list = lists[name], shown = 0, total = 0;
    var cut = !wide.matches && !state.expanded;
    [].forEach.call(list.children, function (li) {
      total++;
      var ok = passes(li, name);
      if (ok) shown++;
      li.hidden = !ok || (cut && shown > PAGE);
    });
    var noun = NOUN[name];
    var filtered = state.filter !== "all" && !(name !== "cams" && (state.filter === "new" || state.filter === "flock"));
    countEl.textContent = filtered
      ? plural(shown, noun[0], noun[1]) + " this filter"
      : "All " + total + " " + noun[1] + (name === "cams" ? ", newest first" : ", most cameras first");
    emptyEl.hidden = shown > 0;
    if (!shown) emptyEl.textContent = "Nothing matches this filter. Choose All to see every record.";
    moreEl.hidden = !(cut && shown > PAGE);
    if (!moreEl.hidden) moreEl.textContent = "Show all " + shown + " " + noun[1];
    drawMarkers(fromSearch);
  }

  function setTab(name, focus) {
    if (!lists[name]) return;
    state.tab = name; state.expanded = false;
    Object.keys(lists).forEach(function (k) {
      lists[k].hidden = k !== name;
      tabs[k].setAttribute("aria-selected", k === name ? "true" : "false");
      tabs[k].tabIndex = k === name ? 0 : -1;
    });
    if (focus) tabs[name].focus();
    showLists();
    apply();
  }
  Object.keys(tabs).forEach(function (k) {
    tabs[k].addEventListener("click", function () {
      if (state.record) leaveRecord(true);
      setTab(k);
    });
    tabs[k].addEventListener("keydown", function (e) {
      var order = ["cams", "owners", "parcels"], i = order.indexOf(k);
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        setTab(order[(i + (e.key === "ArrowRight" ? 1 : 2)) % 3], true);
      }
    });
  });

  [].forEach.call(root.querySelectorAll(".ax-f"), function (b) {
    b.addEventListener("click", function () {
      state.filter = b.getAttribute("data-f");
      [].forEach.call(root.querySelectorAll(".ax-f"), function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      if (state.record) leaveRecord(true);
      state.expanded = false;
      apply(true);
      say(countEl.textContent);
    });
  });

  moreEl.addEventListener("click", function () { state.expanded = true; apply(); });

  function showLists() {
    detailEl.hidden = true;
    lists[state.tab].hidden = false;
    countEl.hidden = false;
  }

  /* ---------------- map ---------------- */
  var map = null, cluster = null, coneLayer = null, markers = {}, selected = {};
  var CAM_SVG = '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">' +
    '<path d="M4 7a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1.2l3.2-1.6a.6.6 0 0 1 .8.55V14a.6.6 0 0 1-.8.55L16 13v1a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7z" fill="__F__" stroke="#fff" stroke-width="1.4"/>' +
    '<circle cx="10" cy="9.5" r="2.4" fill="#fff"/><circle cx="10" cy="9.5" r="1.1" fill="__L__"/></svg>';
  function camIcon(c) {
    var sel = !!selected[c.id];
    var svg = CAM_SVG.replace("__F__", c.flock ? "#DC9A1F" : "#7C8B86").replace("__L__", c.flock ? "#7A5A0E" : "#3F4B47");
    return L.divIcon({
      html: '<div class="cam-marker' + (c.isNew ? " new" : "") + (sel ? " sel" : "") + '">' + svg + "</div>",
      className: "", iconSize: [26, 26], iconAnchor: [13, 13]
    });
  }

  function conePoints(lat, lon, a, b) {
    var R = 6371000, D = 85, latR = lat * Math.PI / 180, lonR = lon * Math.PI / 180;
    function dest(br) {
      var dLat = Math.asin(Math.sin(latR) * Math.cos(D / R) + Math.cos(latR) * Math.sin(D / R) * Math.cos(br));
      var dLon = lonR + Math.atan2(Math.sin(br) * Math.sin(D / R) * Math.cos(latR), Math.cos(D / R) - Math.sin(latR) * Math.sin(dLat));
      return [dLat * 180 / Math.PI, dLon * 180 / Math.PI];
    }
    var span = 24 * Math.PI / 180, s = a * Math.PI / 180;
    if (a === b) return [[lat, lon], dest(s - span), dest(s + span)];
    var sweep = (b - a) * Math.PI / 180;
    while (sweep <= 0) sweep += 2 * Math.PI;
    var n = Math.max(2, Math.ceil(sweep / (10 * Math.PI / 180))), pts = [[lat, lon]];
    for (var i = 0; i <= n; i++) pts.push(dest(s + sweep * (i / n)));
    return pts;
  }

  function visibleCams() {
    return CAM_LIST.filter(function (c) { return !c.li || passes(c.li, "cams"); });
  }

  function drawCones() {
    if (!map) return;
    coneLayer.clearLayers();
    if (map.getZoom() < 15) return;
    var vb = map.getBounds().pad(0.15);
    visibleCams().forEach(function (c) {
      if (!vb.contains([c.lat, c.lon])) return;
      dirArcs(c.dir).forEach(function (arc) {
        L.polygon(conePoints(c.lat, c.lon, arc.a, arc.b), {
          color: "#DC9A1F", weight: 1, opacity: 0.6, fillColor: "#DC9A1F", fillOpacity: 0.22,
          className: "cam-cone", interactive: false
        }).addTo(coneLayer);
      });
    });
  }

  function drawMarkers(fit) {
    if (!map) return;
    var vis = visibleCams();
    cluster.clearLayers();
    cluster.addLayers(vis.map(function (c) { return markers[c.id]; }));
    drawCones();
    if (fit && vis.length && state.filter !== "all") {
      if (vis.length === 1) map.setView([vis[0].lat, vis[0].lon], Math.max(map.getZoom(), 16));
      else map.fitBounds(L.latLngBounds(vis.map(function (c) { return [c.lat, c.lon]; })).pad(0.15), { maxZoom: 16 });
    }
  }

  function setSelected(ids) {
    var prev = selected; selected = {};
    ids.forEach(function (id) { selected[id] = true; });
    Object.keys(prev).concat(ids).forEach(function (id) {
      if (markers[id]) markers[id].setIcon(camIcon(CAM[id]));
    });
  }

  function initMap() {
    if (!window.L || !$("alpr-map") || !CAM_LIST.length) {
      var box = root.querySelector(".ax-mapbox");
      if (box) box.innerHTML = '<p class="ax-mapfail">The map could not load. Every camera is listed beside it, with its record.</p>';
      return;
    }
    map = L.map("alpr-map", { scrollWheelZoom: false, zoomControl: true, tap: true });
    window._alprMap = map;
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.esri.com">Esri</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    coneLayer = L.layerGroup().addTo(map);
    cluster = L.markerClusterGroup({
      maxClusterRadius: 42, disableClusteringAtZoom: 16, spiderfyOnMaxZoom: true,
      showCoverageOnHover: false, chunkedLoading: true,
      iconCreateFunction: function (cl) {
        var n = cl.getChildCount(), size = n > 100 ? 48 : n > 25 ? 42 : n > 8 ? 36 : 32;
        return L.divIcon({
          html: '<div class="cluster-dot" style="width:' + size + "px;height:" + size + 'px">' + n + "</div>",
          className: "", iconSize: [size, size]
        });
      }
    });
    CAM_LIST.forEach(function (c) {
      var m = L.marker([c.lat, c.lon], { icon: camIcon(c), keyboard: true, title: c.manu + " camera", alt: c.manu + " camera" });
      m.on("click", function () { pickFromMap(c.id); });
      markers[c.id] = m;
    });
    map.addLayer(cluster);
    map.fitBounds(L.latLngBounds(CAM_LIST.map(function (c) { return [c.lat, c.lon]; })).pad(0.04));
    map.on("zoomend moveend", drawCones);
    map.on("click", hidePeek);

    // Wheel over the map scrolls the page. Ctrl or Cmd + wheel zooms, and a plain wheel says so.
    var hint = $("ax-maphint"), hintT = 0, wheelT = 0;
    map.getContainer().addEventListener("wheel", function (e) {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        var now = Date.now();
        if (now - wheelT < 180) return;
        wheelT = now;
        map.setZoomAround(map.mouseEventToLatLng(e), map.getZoom() + (e.deltaY < 0 ? 1 : -1));
      } else if (hint && wide.matches) {
        hint.hidden = false;
        clearTimeout(hintT);
        hintT = setTimeout(function () { hint.hidden = true; }, 1300);
      }
    }, { passive: false });
    if (window.ResizeObserver) new ResizeObserver(function () { map.invalidateSize(); }).observe($("alpr-map"));
  }

  function focusCamOnMap(id, zoom) {
    var c = CAM[id]; if (!map || !c) return;
    var m = markers[id];
    if (m && cluster.hasLayer(m)) cluster.zoomToShowLayer(m, function () { map.setView([c.lat, c.lon], Math.max(map.getZoom(), zoom || 17)); });
    else map.setView([c.lat, c.lon], Math.max(map.getZoom(), zoom || 17));
  }
  function fitCams(ids) {
    if (!map) return;
    var pts = ids.map(function (id) { return CAM[id]; }).filter(Boolean).map(function (c) { return [c.lat, c.lon]; });
    if (pts.length === 1) map.setView(pts[0], Math.max(map.getZoom(), 17));
    else if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.25), { maxZoom: 17 });
  }

  /* ---------------- peek card (phones): tap a camera, read it without leaving the map ---------------- */
  var peek = $("ax-peek");
  function hidePeek() { if (peek) peek.hidden = true; }
  function pickFromMap(id) {
    if (wide.matches) { go("camera/" + id); return; }
    setSelected([id]);
    var c = CAM[id];
    ownReady.then(function () {
      var o = OWN_CAM[id];
      peek.innerHTML =
        '<div class="ax-peek-row"><strong>' + esc(locOf(id)) + '</strong>' +
        '<button type="button" class="ax-x" aria-label="Close">&#10005;</button></div>' +
        '<p>' + esc(c.manu) + (dirText(c.dir) ? " &middot; facing " + esc(dirText(c.dir)) : "") +
        (c.mapped ? " &middot; mapped " + esc(c.mapped) : "") + "</p>" +
        (o ? "<p>" + esc(relation(o)).replace(/^./, function (x) { return x.toUpperCase(); }) + " parcel " + esc(o.apn) +
             ": <b>" + esc(o.owner) + "</b></p>" : "<p>Ownership not joined yet.</p>") +
        '<a class="ax-btn" href="#camera/' + esc(id) + '">Full record</a>';
      peek.hidden = false;
      peek.querySelector(".ax-x").addEventListener("click", hidePeek);
      say("Camera selected: " + locOf(id));
    });
  }

  /* ---------------- records ---------------- */
  var stack = [];     // record hashes opened in this visit, so Back follows the browser history
  function go(h) { if (location.hash !== "#" + h) location.hash = h; else route(); }

  function openRecord(kind, key) {
    return ownReady.then(function () {
      var html = null, ids = [];
      if (kind === "camera") {
        if (CAM[key] || OWN_CAM[key]) { html = camRecord(key); ids = [key]; }
      } else if (kind === "owner" && OWN) {
        var o = OWN.owners[+key];
        if (o && /^\d+$/.test(key)) { html = ownerRecord(o); ids = o.cams.slice(); }
      } else if (kind === "parcel" && OWN) {
        var p = /^\d+$/.test(key) ? OWN.parcels[+key] : null;
        if (!p) p = OWN.parcels.filter(function (x) { return x.apn === key; })[0];
        if (p) { html = parcelRecord(p); ids = p.cams.slice(); }
      }
      if (html === null) html = missing(kind, key);
      state.record = kind + "/" + key;
      [].forEach.call(Object.keys(lists), function (k) { lists[k].hidden = true; });
      countEl.hidden = true; emptyEl.hidden = true; moreEl.hidden = true;
      detailEl.innerHTML = '<button type="button" class="ax-back" id="ax-back">&larr; Back to the list</button>' + html;
      detailEl.hidden = false;
      $("ax-back").addEventListener("click", function () { leaveRecord(false); });
      [].forEach.call(detailEl.querySelectorAll("[data-showmap]"), function (b) {
        b.addEventListener("click", function () {
          root.querySelector(".ax-mapbox").scrollIntoView({ behavior: "smooth", block: "start" });
          if (ids.length === 1) focusCamOnMap(ids[0]); else fitCams(ids);
        });
      });
      scrollEl.scrollTop = 0;
      hidePeek();
      setSelected(ids);
      if (ids.length === 1) focusCamOnMap(ids[0]); else if (ids.length) fitCams(ids);
      var t = detailEl.querySelector("h4");
      say("Opened " + (t ? t.textContent : "record"));
      return true;
    });
  }

  function leaveRecord(silent) {
    if (!state.record) return;
    state.record = null;
    setSelected([]);
    showLists();
    if (!silent) {
      if (stack.length > 1) { history.back(); return; }
      history.replaceState(null, "", location.pathname + location.search);
    } else if (/^#(camera|owner|parcel)\//.test(location.hash)) {
      stack = [];
      history.replaceState(null, "", location.pathname + location.search);
    }
    apply();
  }

  function missing(kind, key) {
    return '<h4 class="ax-d-title">No ' + esc(kind) + " matches that link</h4>" +
      '<p class="ax-d-m">The link asked for ' + esc(kind) + " <b>" + esc(key) + "</b>, which is not in this build. " +
      "It may come from an older version of the page, or the number may be mistyped.</p>";
  }

  function kv(rows) {
    return '<dl class="ax-kv">' + rows.filter(Boolean).map(function (r) {
      return "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>";
    }).join("") + "</dl>";
  }
  function sec(title, inner) { return inner ? '<section class="ax-d-sec"><h5>' + title + "</h5>" + inner + "</section>" : ""; }
  function row(href, title, meta) {
    return '<li><a href="' + href + '"><span class="ax-it">' + title + '</span>' + (meta ? '<span class="ax-im">' + meta + "</span>" : "") + "</a></li>";
  }
  function districtLine(value, phone, disp, mail) {
    if (!value || value === "None") return "not published for this parcel";
    var out = esc(value);
    if (phone) out += " &middot; office " + tel(phone, disp || phone);
    if (mail) out += " &middot; " + contactLink(mail);
    return out;
  }

  function camRecord(id) {
    var c = CAM[id] || {}, o = OWN_CAM[id];
    var facing = dirText(c.dir || (o && o.dir));
    var arc = dirArcs(c.dir || (o && o.dir))[0];
    var lat = c.lat != null ? c.lat : o && o.lat, lon = c.lon != null ? c.lon : o && o.lon;
    var h = '<h4 class="ax-d-title">' + esc(locOf(id)) + "</h4>" +
      '<div class="ax-chips"><span class="ax-chip b">' + esc(c.manu || (o && o.manu) || "Unspecified") + "</span>" +
      (o ? (o.incity ? '<span class="ax-chip">in city limits</span>' : '<span class="ax-chip">outside city limits</span>') : "") +
      (c.isNew ? '<span class="ax-chip new">mapped in the last 28 days</span>' : "") + "</div>" +
      kv([
        facing ? ["Facing", '<span class="ax-arrow" style="transform:rotate(' + arc.a + 'deg)"></span>' + esc(facing) + " <span class=ax-dim>(the amber cone at street zoom)</span>"] : ["Facing", "not tagged in OpenStreetMap"],
        ["Mapped on OSM", esc(c.mapped || (o && o.mapped) || "date not stated") + " <span class=ax-dim>(not the install date)</span>"],
        (c.op || (o && o.op)) ? ["Operator", esc(c.op || o.op)] : null,
        ["Coordinates", esc(Number(lat).toFixed(6) + ", " + Number(lon).toFixed(6))],
        ["OSM node", link("https://www.openstreetmap.org/node/" + id, "node " + id)]
      ]) +
      '<button type="button" class="ax-btn ghost ax-onlyphone" data-showmap>Show on the map</button>';
    if (!o) {
      return h + sec("Whose land this is", '<p class="ax-d-m">This camera was mapped after the county records snapshot, ' +
        "so it is not joined to a parcel yet. It joins at the next records refresh.</p>");
    }
    var owner = OWN.owners[o.oid], parcel = o.pid != null ? OWN.parcels[o.pid] : null;
    var land = (owner ? '<a class="ax-ownercard" href="#owner/' + owner.oid + '"><span class="ax-it">' + esc(owner.name) + "</span>" +
        '<span class="ax-im">' + KIND_LABEL[kindOf(owner.type)] + " &middot; " + plural(owner.n, "camera") +
        " at or beside their land. Open the owner</span></a>" : '<p class="ax-d-m">No owner name on the tax roll.</p>') +
      kv([
        ["Parcel", parcel ? '<a href="#parcel/' + parcel.pid + '">' + esc(o.apn) + "</a>" + (parcel.n > 1 ? " (" + parcel.n + " cameras on or beside it)" : "") : esc(o.apn || "not stated")],
        ["Where", "The camera stands " + esc(relation(o)) + " this parcel" + (o.dist != null ? ", " + esc(o.dist) + " m from it" : "") + ". <span class=ax-dim>" + esc(o.match || "") + "</span>"],
        ["Land class", esc(o.land)],
        ["Use", esc(o.use || "not stated")],
        ["Assessed", esc(o.val || "not stated") + (o.landval != null ? " <span class=ax-dim>(land " + fmt(o.landval) + ", buildings " + fmt(o.impval) + ")</span>" : "")],
        o.prop13 ? ["Prop. 13 value", fmt(o.prop13)] : null,
        ["City check", esc(o.gis || "not stated")],
        ["County supervisor", districtLine(o.district, o.dphone, o.dphone_disp, o.dmail)],
        ["Recorded doc", esc(o.docs || "county shows none for this parcel")],
        ["Street at the pin", esc(o.loc || "not stated") + (o.trusted ? " <span class=ax-dim>(measured at the pin)</span>" :
          " <span class=ax-dim>(nearest named road" + (o.near_m != null ? ", " + esc(o.near_m) + " m away" : "") + ")</span>")],
        ["Block address", esc(o.addr || "not stated")]
      ]) + (o.onote ? '<p class="ax-d-m">' + esc(o.onote) + "</p>" : "");
    var sib = parcel ? parcel.cams.filter(function (x) { return x !== id; }) : [];
    return h + sec("Whose land this is", land) +
      cityRoutes(o, owner) +
      sec("Company record", entityBlock(o, owner)) +
      sec("How to reach the owner", contactBlock(o)) +
      (sib.length ? sec("Other cameras on or beside this parcel", '<ol class="ax-list ax-mini">' + sib.map(function (x) {
        return row("#camera/" + x, esc(locOf(x)), esc((CAM[x] || {}).manu || ""));
      }).join("") + "</ol>") : "") +
      sec("Sources", srcBlock(o, id));
  }

  function ownerRecord(o) {
    var k = kindOf(o.type);
    var h = '<h4 class="ax-d-title">' + esc(o.name) + "</h4>" +
      '<div class="ax-chips">' + kindChip(o.type) + ((o.phone || o.email) ? '<span class="ax-chip ok">contact published</span>' : "") +
      (o.value ? '<span class="ax-chip">' + money(o.value) + " total assessed</span>" : "") + "</div>" +
      '<p class="ax-d-m"><b>' + plural(o.n, "camera") + "</b> at or beside their land in Bakersfield, across " + plural(o.nparcel, "parcel") + ". " +
      "Each camera is joined to the nearest tax-roll parcel. Where a camera stands in a street or right of way, that parcel is " +
      "only the nearest one, not land the owner holds, so read the match line on each camera.</p>" +
      (o.withheld ? '<p class="ax-d-m">This owner is a private ' + (String(o.type).toLowerCase() === "trust" ? "trust" : "individual") +
        ". The page does not publish private owners&rsquo; names or contact routes; the parcel numbers below lead to the county record.</p>" : "") +
      '<button type="button" class="ax-btn ghost ax-onlyphone" data-showmap>Show their cameras on the map</button>';
    var cams = o.cams.map(function (id) {
      var c = OWN_CAM[id] || {};
      return row("#camera/" + id, esc(locOf(id)), "parcel " + esc(c.apn || "") + " &middot; " + esc(relation(c)) + " it");
    }).join("");
    var parcels = o.parcels.map(function (apn) {
      var p = OWN.parcels.filter(function (x) { return x.apn === apn; })[0];
      return p ? row("#parcel/" + p.pid, "Parcel " + esc(apn), plural(p.n, "camera") + " &middot; " + esc(p.use || "")) : "<li>Parcel " + esc(apn) + "</li>";
    }).join("");
    return h + sec("Cameras at or beside this owner&rsquo;s land", '<ol class="ax-list ax-mini">' + cams + "</ol>") +
      (o.withheld ? "" : cityRoutes(o, o) + sec("Company record", entityBlock(o, o)) + sec("How to reach them", contactBlock(o))) +
      sec("Parcels", '<ol class="ax-list ax-mini">' + parcels + "</ol>") +
      sec("Sources", srcBlock(o, null, k === "entity"));
  }

  function parcelRecord(p) {
    var disagree = /disagree/i.test(p.gis || "");
    var h = '<h4 class="ax-d-title">Parcel ' + esc(p.apn) + "</h4>" +
      '<div class="ax-chips"><span class="ax-chip b">' + esc(p.use || "use not stated") + "</span>" +
      (p.val ? '<span class="ax-chip">' + esc(p.val) + " assessed</span>" : "") +
      (disagree ? '<span class="ax-chip warn">city records disagree on the owner</span>' : "") + "</div>" +
      '<p class="ax-d-m"><b>' + plural(p.n, "camera") + "</b> on or beside this parcel.</p>" +
      '<button type="button" class="ax-btn ghost ax-onlyphone" data-showmap>Show on the map</button>';
    var owners = (p.owners || []).map(function (nm, i) {
      var oid = (p.oids || [])[i], o = oid != null ? OWN.owners[oid] : null;
      return o ? row("#owner/" + oid, esc(nm), KIND_LABEL[kindOf(o.type)] + " &middot; " + plural(o.n, "camera") + " in Bakersfield")
        : "<li>" + esc(nm) + "</li>";
    }).join("");
    var cams = p.cams.map(function (id) {
      var c = OWN_CAM[id] || {};
      return row("#camera/" + id, esc(locOf(id)), (c.dist != null ? esc(c.dist) + " m &middot; " : "") + esc(c.match || ""));
    }).join("");
    return h + sec("Owner" + ((p.owners || []).length > 1 ? "s" : "") + " of record", '<ol class="ax-list ax-mini">' + owners + "</ol>") +
      sec("Cameras here", '<ol class="ax-list ax-mini">' + cams + "</ol>") +
      sec("Parcel facts", kv([
        ["Use", esc(p.use || "not stated")],
        ["County supervisor", districtLine(p.district, p.dphone, p.dphone_disp, p.dmail)],
        ["Recorded doc", esc(p.docs || "county shows none")],
        ["City check", esc(p.gis || "not stated")]
      ]) + (p.land ? '<p class="ax-d-m">' + esc(p.land) + "</p>" : ""));
  }

  function cityRoutes(x, owner) {
    var src = (x.l1 || x.l2 || x.l3) ? x : (owner || {});
    var lines = [src.l1, src.l2, src.l3].map(function (v) { try { return JSON.parse(v); } catch (e) { return null; } })
      .filter(function (d) { return d && d.role; });
    if (!lines.length) return "";
    lines.sort(function (a, b) { return (a.line || 9) - (b.line || 9); });
    var isCity = /CITY OF BAKERSFIELD/i.test(String((owner && owner.name) || x.owner || ""));
    return sec(isCity ? "Who to call at the city" : "City offices for this location",
      (isCity ? "" : '<p class="ax-d-m">This land is not city owned. These are the City of Bakersfield offices that handle this location.</p>') +
      '<ul class="ax-routes">' + lines.map(function (d) {
        return "<li><b>" + esc(d.role) + "</b>" + (d.name ? " &middot; " + esc(d.name) : "") +
          (d.phone ? " &middot; " + tel(String(d.phone).split(" ")[0], d.phone) : "") +
          (d.email ? " &middot; " + contactLink(d.email) : "") +
          (d.source ? ' <span class="ax-dim">(' + link(d.source, "source") + ")</span>" : "") + "</li>";
      }).join("") + "</ul>");
  }

  function entityBlock(x, owner) {
    var t = String(x.otype || x.type || "").toLowerCase();
    if (x.withheld || (owner && owner.withheld)) {
      return '<p class="ax-d-m">A private owner. The page does not publish private owners&rsquo; names; the county assessor and recorder hold them under the parcel number above.</p>';
    }
    var sos = x.sos || (owner && owner.sos), off = x.officers || (owner && owner.officers), agent = x.agent || (owner && owner.agent);
    if (t === "government") return '<p class="ax-d-m">A public agency. It answers through its own offices, listed on this record.</p>';
    if (!sos && !off && !agent) {
      return '<p class="ax-d-m">No registry page matched this name as written. The assessor roll copies the owner name from the ' +
        "recorded deed character for character, and registries index by the registered name, so one added or dropped word " +
        "is enough to miss. The name shown is unchanged from the roll.</p>" +
        kv([["State record", link("https://bizfileonline.sos.ca.gov/search/business", "California business search") + ", entered exactly as shown"],
            ["Recorded deed", "names this owner and the address used at signing"]]);
    }
    var src = owner || x;
    return kv([
      ["CA entity no.", esc(sos || "not found") + (src.sos_note ? ' <span class="ax-dim">(' + esc(src.sos_note) + ")</span>" : "")],
      ["Status", esc(src.status || x.sos_status || "not stated")],
      ["Registered agent", esc(agent || "not stated")],
      ["Principal office", esc(x.principal || src.principal || "not stated")]
    ]) + (off ? '<p class="ax-d-m"><b>Officers and managers</b> (from public registry mirrors, not the state system directly): ' +
      esc(off).replace(/;\s*/g, "; ") + "</p>" : "");
  }

  function contactBlock(x) {
    if (x.withheld) return '<p class="ax-d-m">Not published for a private owner.</p>';
    var ph = x.phone, em = x.email, mail = x.mail ? String(x.mail).replace(/,\s*,/g, ",") : "";
    var isGov = String(x.otype || x.type || "").toLowerCase() === "government" ||
      x.cstat === "government_agency" || x.cstat === "city_escalation_chain";
    if (isGov) {
      var isCity = /CITY OF BAKERSFIELD/i.test(x.name || x.owner || "");
      return kv([
        isCity ? ["Main line", tel("6613263000", "(661) 326-3000") + " city switchboard"] : null,
        ph ? ["Phone", tel(ph)] : null,
        em ? ["Email", contactLink(em)] : null,
        mail ? ["Mailing", esc(mail)] : null,
        ["Route", "A public agency: use the department and elected-office lines on this record. They answer for the land and the camera program."]
      ]);
    }
    var out = kv([
      ["Phone", ph ? tel(ph) + (x.plabel === "company office" ? " (company office, not a local line)" : "") : "not published"],
      ["Email", em ? contactLink(em) : "not published"],
      ["Mailing", mail ? esc(mail) : "not published"]
    ]);
    if (x.listed && (ph || em || mail)) {
      out += '<p class="ax-d-m">Shown in a public source: ' + (x.csource ? link(x.csource, x.listed) : esc(x.listed)) +
        ". Open the source before you rely on it.</p>";
    }
    if (x.court) out += '<p class="ax-d-m">Public court record: ' + esc(x.court) + (x.court_url ? " " + link(x.court_url, "view the case") : "") + "</p>";
    if (!ph && !em && !mail) {
      out += '<p class="ax-d-m">No phone, email or mailing address is published with this record. That means the record is not ' +
        "public, not that the owner cannot be reached: the recorded deed" + (x.docs ? " (document " + esc(String(x.docs).split(/[; ]+/)[0]) + ")" : "") +
        " names the address used at signing, the " + link("https://bizfileonline.sos.ca.gov/search/business", "California business search") +
        " lists a registered agent for a company, and the " + link("https://www.kcttc.co.kern.ca.us/", "treasurer-tax collector") +
        " mails the tax bill to the address on file" + (x.taxnum ? " (tax number " + esc(x.taxnum) + ")" : "") + ".</p>";
    } else if (!ph && !em) {
      out += '<p class="ax-d-m">This is the mailing address the county roll holds. No phone or email is published. ' +
        "To reach a company, use the registered agent in the company record.</p>";
    }
    return out;
  }

  function srcBlock(x, camId, isEntity) {
    var urls = [x.csource, x.ent_src, x.src].filter(Boolean).join(" ").split(/\s+/).filter(function (u) { return /^https?:/.test(u); });
    if (camId) urls.push("https://www.openstreetmap.org/node/" + camId);
    urls.push("https://www.kerndata.com/");
    if (x.incity) urls.push("https://gis.bakersfieldcity.us");
    if (isEntity || String(x.otype || "").toLowerCase() === "entity") urls.push("https://bizfileonline.sos.ca.gov/search/business");
    var seen = {}, out = [];
    urls.forEach(function (u) { if (!seen[u]) { seen[u] = 1; out.push(u); } });
    return '<ul class="ax-src">' + out.map(function (u) { return "<li>" + link(u) + "</li>"; }).join("") + "</ul>" +
      '<p class="ax-d-m">Camera point from OpenStreetMap. Owner, parcel, value and recorded document numbers from the Kern County ' +
      "assessor and recorder through kerndata.com, whose search is a form, so enter the parcel number shown here." +
      (x.incity ? " City land check from the City of Bakersfield GIS." : "") + "</p>";
  }

  /* ---------------- routing ---------------- */
  function route() {
    var h = "";
    try { h = decodeURIComponent(location.hash.replace(/^#/, "")); } catch (e) { h = location.hash.replace(/^#/, ""); }
    var m = h.match(/^(camera|owner|parcel)\/(.+)$/);
    if (!m) { if (state.record) { state.record = null; setSelected([]); showLists(); apply(); } stack = []; return; }
    if (stack.length > 1 && stack[stack.length - 2] === h) stack.pop(); else stack.push(h);
    openRecord(m[1], m[2]).then(function () {
      // On a phone the record sits below the map: bring it into view. On a wide screen the panel
      // is beside the map, so only scroll when the explorer is off screen.
      var r = panel.getBoundingClientRect();
      if (!wide.matches || r.top > window.innerHeight || r.bottom < 0) {
        (wide.matches ? root : detailEl).scrollIntoView({ behavior: firstRoute ? "auto" : "smooth", block: "start" });
      }
      firstRoute = false;
    });
  }
  var firstRoute = true;
  window.addEventListener("hashchange", route);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { if (peek && !peek.hidden) hidePeek(); else if (state.record) leaveRecord(false); }
  });
  wide.addEventListener && wide.addEventListener("change", function () { apply(); if (map) map.invalidateSize(); });

  /* ---------------- boot ---------------- */
  root.classList.add("ax-js");
  initMap();
  setTab("cams");
  if (/^#(camera|owner|parcel)\//.test(location.hash)) route();
  else firstRoute = false;
})();
