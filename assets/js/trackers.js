/* Bakersfield Daily Brief — trackers.js (DeFlock-style ALPR map)
   Renders the Flock & ALPR tracker from JSON baked into the page at build
   time (no client-side data fetching anywhere).

   Map: dark basemap (CARTO Dark Matter) with amber camera markers and
   clusters, scroll-wheel zoom ENABLED on desktop (per user request) and
   standard pinch-zoom on mobile. "Highlight newest" button rings cameras
   mapped in the last 28 days. Popups show manufacturer, operator, facing
   direction, and OSM mapped date.
 */
(function () {
  "use strict";

  var dataEl = document.getElementById("tracker-data");
  if (!dataEl) return;
  var DATA;
  try { DATA = JSON.parse(dataEl.textContent); }
  catch (e) { console.error("tracker data parse failed", e); return; }

  var mapDiv = document.getElementById("alpr-map");
  if (!mapDiv || !window.L || !DATA.cameras) return;

  /* ---------------- map ---------------- */
  var map = L.map("alpr-map", { scrollWheelZoom: true }).setView([35.37, -119.02], 10);
  window._alprMap = map; // exposed for automated verification
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 19
  }).addTo(map);

  // cutoff for "newest" (last 28 days of mapping)
  var asof = DATA.asof || "";
  var cutoff = "";
  if (asof) {
    var d = new Date(asof + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() - 28);
    cutoff = d.toISOString().slice(0, 10);
  }

  var flockDot = L.divIcon({ html: '<div class="cam-dot flock"></div>', className: "", iconSize: [15, 15] });
  var otherDot = L.divIcon({ html: '<div class="cam-dot other"></div>', className: "", iconSize: [15, 15] });
  var flockDotNew = L.divIcon({ html: '<div class="cam-dot flock new"></div>', className: "", iconSize: [17, 17] });
  var otherDotNew = L.divIcon({ html: '<div class="cam-dot other new"></div>', className: "", iconSize: [17, 17] });

  /* ---------- direction cone (DeFlock-style) ----------
     Draw a small wedge (cone) from the camera dot showing which compass
     direction the camera faces. c.direction is a bearing in degrees
     (e.g. "236" = southwest). The cone is a polygon: apex at the dot,
     widening ~24° each side, ~85m long. Rotated by the bearing. */
  var camById = {};          // id -> {lat, lon, dir, marker, cone, isNew, isFlock}
  var CAMERA_CONES = [];     // all cone layers (for show/hide)

  function bearingRad(b) {
    var v = parseFloat(b);
    return isNaN(v) ? null : v * Math.PI / 180;
  }

  function directionCone(lat, lon, bearing) {
    var rad = bearingRad(bearing);
    if (rad === null) return null;               // no direction tagged
    var R = 6371000, d = 85;                      // cone length ~85 m
    var latR = lat * Math.PI / 180, lonR = lon * Math.PI / 180;
    var apex = [lat, lon];
    function dest(bearingOffset) {
      var br = rad + bearingOffset;
      var dLat = Math.asin(Math.sin(latR) * Math.cos(d / R) +
                           Math.cos(latR) * Math.sin(d / R) * Math.cos(br));
      var dLon = lonR + Math.atan2(Math.sin(br) * Math.sin(d / R) * Math.cos(latR),
                                   Math.cos(d / R) - Math.sin(latR) * Math.sin(dLat));
      return [dLat * 180 / Math.PI, dLon * 180 / Math.PI];
    }
    var span = 24 * Math.PI / 180;               // ±24° spread
    return L.polygon([apex, dest(-span), dest(span)], {
      color: "#DC9A1F", weight: 1, opacity: 0.55,
      fillColor: "#DC9A1F", fillOpacity: 0.22,
      className: "cam-cone", interactive: false
    });
  }

  var markers = L.markerClusterGroup({
    iconCreateFunction: function (cluster) {
      var n = cluster.getChildCount();
      var size = n > 100 ? 54 : n > 25 ? 48 : 40;
      var el = L.divIcon({
        html: '<div class="cluster-dot" style="width:' + size + "px;height:" + size + 'px">' + n + "</div>",
        className: "", iconSize: [size, size]
      });
      return el;
    },
    maxClusterRadius: 48,
    spiderfyOnMaxZoom: true
  });

  var flockCount = 0, otherCount = 0, recentCount = 0;
  DATA.cameras.forEach(function (c) {
    if (!c.lat || !c.lon) return;
    var isFlock = (c.manufacturer || "").toLowerCase().indexOf("flock") !== -1;
    var isNew = !!(cutoff && c.mapped && c.mapped >= cutoff);
    if (isFlock) flockCount++; else otherCount++;
    if (isNew) recentCount++;
    c._isNew = isNew;
    var icon = isFlock ? (isNew ? flockDotNew : flockDot) : (isNew ? otherDotNew : otherDot);
    var m = L.marker([c.lat, c.lon], { icon: icon });
    var dir = c.direction ? "Facing: " + c.direction : "Direction not tagged";
    var mapped = c.mapped ? c.mapped : "unknown";
    m.bindPopup(
      "<strong>License plate reader</strong><br>" +
      "Manufacturer: " + (c.manufacturer || "Unspecified") + "<br>" +
      (c.operator ? "Operator: " + c.operator + "<br>" : "") +
      dir + "<br>" +
      "Mapped on OSM: " + mapped + "<br>" +
      '<a href="https://www.openstreetmap.org/node/' + c.id + '" target="_blank" rel="noopener">View node on OSM ↗</a>'
    );
    markers.addLayer(m);
    // direction cone (DeFlock-style): wedge showing the camera's facing
    var cone = directionCone(c.lat, c.lon, c.direction);
    if (cone) {
      cone.addTo(map);
      CAMERA_CONES.push(cone);
    }
    camById[c.id] = { lat: c.lat, lon: c.lon, dir: c.direction, marker: m, cone: cone, isNew: isNew, isFlock: isFlock };
  });
  map.addLayer(markers);

  /* highlight-newest toggle */
  var btn = document.getElementById("toggle-newest");
  var active = false;
  // rebuild markers with the chosen icon set (recent cameras get ring icons)
  function rebuild(highlight) {
    markers.clearLayers();
    DATA.cameras.forEach(function (c) {
      if (!c.lat || !c.lon) return;
      var isFlock = (c.manufacturer || "").toLowerCase().indexOf("flock") !== -1;
      var isNew = !!(cutoff && c.mapped && c.mapped >= cutoff);
      var icon;
      if (highlight && isNew) icon = isFlock ? flockDotNew : otherDotNew;
      else if (!highlight && isNew) icon = isFlock ? flockDot : otherDot;
      else icon = isFlock ? flockDot : otherDot;
      var m = L.marker([c.lat, c.lon], { icon: icon });
      m.bindPopup(
        "<strong>License plate reader</strong><br>" +
        "Manufacturer: " + (c.manufacturer || "Unspecified") + "<br>" +
        (c.operator ? "Operator: " + c.operator + "<br>" : "") +
        (c.direction ? "Facing: " + c.direction + "<br>" : "Direction not tagged<br>") +
        "Mapped on OSM: " + (c.mapped || "unknown") + "<br>" +
        '<a href="https://www.openstreetmap.org/node/' + c.id + '" target="_blank" rel="noopener">View node on OSM ↗</a>'
      );
      markers.addLayer(m);
    });
  }
  if (btn) {
    btn.addEventListener("click", function () {
      active = !active;
      btn.classList.toggle("on", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      rebuild(active);
      var note = document.getElementById("newest-note");
      if (note) note.textContent = active
        ? "Ringing " + recentCount + " cameras mapped in the last 28 days."
        : "All cameras shown; ring markers mark the last 28 days of mapping.";
    });
  }
  rebuild(false);

  /* ---------- click a newest-camera link -> fly to it, zoom to street ----------
     Each .ov-cam link carries data-lat/data-lon/data-dir. On click we fly to
     the camera, zoom to ~16 (street level), open its popup, and flash the
     direction cone so you can see exactly which way it faces. */
  function flyToCamera(id) {
    var c = camById[id];
    if (!c) return;
    map.flyTo([c.lat, c.lon], 16, { duration: 0.9 });
    // open the marker's popup once the fly settles
    setTimeout(function () {
      if (c.marker) c.marker.openPopup();
    }, 950);
  }
  var ovLinks = document.querySelectorAll(".ov-cam");
  ovLinks.forEach(function (a) {
    a.addEventListener("click", function (ev) {
      ev.preventDefault();
      flyToCamera(a.getAttribute("data-id"));
    });
  });

  /* ---------- cones only at street zoom (declutter) ----------
     Below zoom ~14 the cones overlap; hide them. Above 14 (street level)
     they appear so you can read the facing. */
  function updateCones() {
    var z = map.getZoom();
    var show = z >= 14;
    CAMERA_CONES.forEach(function (cone) {
      if (show) { if (!map.hasLayer(cone)) cone.addTo(map); }
      else if (map.hasLayer(cone)) map.removeLayer(cone);
    });
  }
  map.on("zoomend", updateCones);
  updateCones();

  /* legend + stats */
  var legend = document.getElementById("map-legend-stats");
  if (legend) {
    legend.innerHTML =
      '<span><span class="sw" style="background:#DC9A1F"></span>' + flockCount + " Flock Safety</span>" +
      '<span><span class="sw" style="background:#8FA099"></span>' + otherCount + " other / unspecified</span>" +
      '<span><span class="sw ring"></span>' + recentCount + " mapped in last 28 days</span>" +
      "<span>" + DATA.cameras.length + " total mapped nodes</span>";
  }

  /* "as of" stamps */
  Array.prototype.forEach.call(document.querySelectorAll("[data-asof]"), function (el) {
    el.textContent = asof;
  });
})();
