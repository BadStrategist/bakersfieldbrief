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
