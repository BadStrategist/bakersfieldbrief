/* Bakersfield Daily Brief — fires.js (Kern County + California wildfire map)
   Renders active CAL FIRE incidents from JSON baked into the page at build
   time (no client-side data fetching). Same Voyager basemap and dark
   deflock.css chrome as the ALPR map, with flame markers. Kern County fires
   are orange; other California fires are a cooler slate. */
(function () {
  "use strict";

  var dataEl = document.getElementById("tracker-data");
  if (!dataEl) return;
  var DATA;
  try { DATA = JSON.parse(dataEl.textContent); }
  catch (e) { console.error("fires data parse failed", e); return; }

  var mapDiv = document.getElementById("fires-map");
  if (!mapDiv || !window.L || !DATA.incidents) return;

  var map = L.map("fires-map", { scrollWheelZoom: true }).setView([36.0, -119.3], 6);
  window._firesMap = map; // exposed for automated verification

  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
    attribution: '&copy; <a href="https://www.esri.com">Esri</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19
  }).addTo(map);

  /* Flame pin — a stylized flame glyph, colored by county. */
  var FLAME_SVG = '<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">' +
    '<path d="M12 2c.3 3-1.5 4.6-3 6.2C7.2 10 6 11.6 6 13.6A6 6 0 0 0 12 19.7a6 6 0 0 0 6-6.1c0-2.6-1.6-4.8-3.1-6.5C13.3 5.3 12.6 3.7 12 2z" fill="__FILL__" stroke="#fff" stroke-width="1.2"/>' +
    '<path d="M12 9c.5 1.8-.8 2.8-1.7 3.9-.7.8-1.3 1.7-1.3 2.7A3.3 3.3 0 0 0 12 19c1.8 0 3.2-1.5 3.2-3.3 0-1.3-.7-2.4-1.6-3.4-.4-.4-.6-1-.6-1.6-.9.4-1.6 1.1-2 2.4.3-1.2.8-3 1-4z" fill="#fff" opacity="0.85"/>' +
    '</svg>';

  function fireIcon(i) {
    var kern = (i.county || "").toLowerCase().indexOf("kern") !== -1;
    var fill = kern ? "#DC9A1F" : "#D4552E";
    return L.divIcon({
      html: '<div class="fire-marker' + (kern ? " kern" : "") + '">' + FLAME_SVG.replace("__FILL__", fill) + "</div>",
      className: "",
      iconSize: [28, 28], iconAnchor: [14, 14],
      popupAnchor: [0, -16]
    });
  }

  var markers = L.markerClusterGroup({
    iconCreateFunction: function (cluster) {
      var n = cluster.getChildCount();
      var size = n > 25 ? 40 : n > 8 ? 34 : 30;
      return L.divIcon({
        html: '<div class="cluster-dot fire" style="width:' + size + "px;height:" + size + 'px">' + n + "</div>",
        className: "", iconSize: [size, size]
      });
    },
    maxClusterRadius: 40,
    spiderfyOnMaxZoom: true,
    disableClusteringAtZoom: 9,
    chunkedLoading: true
  });

  var kernCount = 0;
  DATA.incidents.forEach(function (i) {
    if (!i.lat || !i.lon) return;
    var kern = (i.county || "").toLowerCase().indexOf("kern") !== -1;
    if (kern) kernCount++;
    var acres = (i.acres !== undefined && i.acres !== null && i.acres !== "")
      ? Number(i.acres).toLocaleString() : "n/a";
    var cont = (i.contained !== undefined && i.contained !== null && i.contained !== "")
      ? Number(i.contained).toFixed(0) + "%" : "n/a";
    var m = L.marker([i.lat, i.lon], { icon: fireIcon(i) });
    var countyTag = kern ? "<strong>Kern County</strong>" : (i.county || "");
    m.bindPopup(
      "<strong>" + (i.name || "Wildfire") + "</strong><br>" +
      countyTag + "<br>" +
      "Acres: " + acres + " &middot; Contained: " + cont + "<br>" +
      (i.started ? "Started: " + i.started + "<br>" : "") +
      '<a href="' + (i.url || "https://www.fire.ca.gov/") + '" target="_blank" rel="noopener">View on CAL FIRE ↗</a>'
    );
    markers.addLayer(m);
  });
  map.addLayer(markers);

  if (kernCount > 0) {
    // zoom to Kern fires if any
    var kernBounds = [];
    DATA.incidents.forEach(function (i) {
      if (i.lat && i.lon && (i.county || "").toLowerCase().indexOf("kern") !== -1)
        kernBounds.push([i.lat, i.lon]);
    });
    if (kernBounds.length) map.fitBounds(kernBounds, { padding: [40, 40], maxZoom: 10 });
  }

  /* legend */
  var legend = document.getElementById("map-legend-stats");
  if (legend) {
    legend.innerHTML =
      '<span><span class="sw" style="background:#DC9A1F"></span>Kern County</span>' +
      '<span><span class="sw" style="background:#D4552E"></span>Other California</span>' +
      "<span>" + DATA.incidents.length + " active statewide</span>";
  }

  /* "as of" stamps */
  Array.prototype.forEach.call(document.querySelectorAll("[data-asof]"), function (el) {
    el.textContent = DATA.asof || "";
  });
})();
