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

  /* camera glyph marker: a CCTV body + lens; the whole marker rotates so the
     lens points along the camera's facing. Cleaner and more intuitive than a
     bare dot — reads as "camera" at a glance. */
  function cameraIcon(c, isNew) {
    var dir = parseFloat(c.direction);
    var rot = isNaN(dir) ? 0 : (dir + 90);   // lens faces the bearing
    var cls = "cam-marker" +
      ((c.manufacturer || "").toLowerCase().indexOf("flock") !== -1 ? "" : " other") +
      (isNew ? " new" : "");
    return L.divIcon({
      html: '<div class="' + cls + '" style="transform:rotate(' + rot + 'deg)">' +
            '<div class="cam-body"></div></div>',
      className: "", iconSize: [30, 26], iconAnchor: [15, 20]
    });
  }

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
    var m = L.marker([c.lat, c.lon], { icon: cameraIcon(c, isNew) });
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
      var m = L.marker([c.lat, c.lon], { icon: cameraIcon(c, isNew) });
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
     they appear so you can read the facing. On mobile, require a higher
     zoom (15+) so small screens don't get cluttered. */
  var CONE_MIN_ZOOM = (window.innerWidth && window.innerWidth <= 700) ? 15 : 14;
  function updateCones() {
    var z = map.getZoom();
    var show = z >= CONE_MIN_ZOOM;
    CAMERA_CONES.forEach(function (cone) {
      if (show) { if (!map.hasLayer(cone)) cone.addTo(map); }
      else if (map.hasLayer(cone)) map.removeLayer(cone);
    });
  }
  map.on("zoomend", updateCones);
  updateCones();

  /* ---------- address search ----------
     Geocode a Bakersfield address via Nominatim (free, no key), drop a
     marker, and list the nearest cameras with distances. */
  var searchInput = document.getElementById("addr-search");
  var searchResult = document.getElementById("addr-result");
  var searchMarker = null;
  var searchCircle = null;

  function haversine(a, b) {
    var R = 6371000, dLat = (b[0] - a[0]) * Math.PI / 180, dLon = (b[1] - a[1]) * Math.PI / 180;
    var s = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(a[0] * Math.PI / 180) * Math.cos(b[0] * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.atan2(Math.sqrt(s), Math.sqrt(1 - s));
  }
  function fmtDist(m) { return m < 1000 ? Math.round(m) + " m" : (m / 1000).toFixed(2) + " km"; }

  function showSearchError(msg) {
    if (searchResult) searchResult.innerHTML = '<div class="ov-err">' + msg + "</div>";
  }

  if (searchInput && searchResult) {
    var searchTimer = null;
    var suggestions = [];

    // render a selectable dropdown of address suggestions
    function renderSuggestions(items) {
      suggestions = items;
      if (!items.length) { searchResult.innerHTML = ""; return; }
      var html = '<div class="ov-sug" role="listbox">' + items.map(function (it, i) {
        var label = it.display_name.split(",").slice(0, 2).join(",").trim();  // "1234 Truxtun Ave, Bakersfield"
        return '<button type="button" class="ov-sug-item" data-i="' + i + '" role="option">' +
               '<span class="ov-sug-pin">📍</span>' + label + "</button>";
      }).join("") + "</div>";
      searchResult.innerHTML = html;
      // wire clicks
      searchResult.querySelectorAll(".ov-sug-item").forEach(function (btn) {
        btn.addEventListener("click", function () {
          selectSuggestion(parseInt(btn.getAttribute("data-i"), 10));
        });
      });
    }

    // pick a suggestion → place marker + nearest cameras
    function selectSuggestion(i) {
      var hit = suggestions[i];
      if (!hit) return;
      var lat = parseFloat(hit.lat), lon = parseFloat(hit.lon);
      var name = hit.display_name || searchInput.value.trim();
      searchInput.value = name.split(",").slice(0, 2).join(",").trim();

      // clear previous
      if (searchMarker) map.removeLayer(searchMarker);
      if (searchCircle) map.removeLayer(searchCircle);

      searchMarker = L.circleMarker([lat, lon], {
        radius: 8, color: "#B3472F", weight: 2, fillColor: "#B3472F", fillOpacity: 0.9
      }).addTo(map).bindPopup("<strong>Your search</strong><br>" + name);
      searchCircle = L.circle([lat, lon], { radius: 400, color: "#B3472F", weight: 1, opacity: 0.5, fillOpacity: 0.05 }).addTo(map);

      map.flyTo([lat, lon], 15, { duration: 0.9 });
      searchMarker.openPopup();

      // nearest cameras within ~800m, sorted by distance
      var near = [];
      DATA.cameras.forEach(function (c) {
        if (!c.lat || !c.lon) return;
        var d = haversine([lat, lon], [c.lat, c.lon]);
        if (d <= 800) near.push({ c: c, d: d });
      });
      near.sort(function (a, b) { return a.d - b.d; });
      var dirTxt = function (c) {
        var deg = parseFloat(c.direction);
        if (isNaN(deg)) return "";
        return "facing " + ["N","NE","E","SE","S","SW","W","NW"][Math.round(deg / 45) % 8] + " ";
      };
      var html = '<div class="ov-sr"><b>' + (near.length ? near.length + " camera" + (near.length > 1 ? "s" : "") + " within 800 m" : "No cameras within 800 m") + "</b></div>";
      if (near.length) {
        html += '<ul class="ov-near">' + near.slice(0, 8).map(function (n) {
          return '<li><span class="dist">' + fmtDist(n.d) + "</span> &middot; " +
                 (n.c.manufacturer || "ALPR") + " " + dirTxt(n.c) +
                 " &middot; <a href=\"https://www.openstreetmap.org/node/" + n.c.id + "\" target=\"_blank\" rel=\"noopener\">node</a></li>";
        }).join("") + "</ul>";
      }
      searchResult.innerHTML = html;
      suggestions = [];
    }

    searchInput.addEventListener("input", function () {
      clearTimeout(searchTimer);
      var q = searchInput.value.trim();
      if (q.length < 3) { searchResult.innerHTML = ""; suggestions = []; return; }
      searchTimer = setTimeout(function () {
        // streets only: strip a leading house number ("6425 euclid" -> "euclid")
        var street = q.replace(/^\s*\d+\s*/, "").trim();
        if (!street) { showSearchError("Type a street name."); return; }
        // structured Nominatim query — reliable for street-level results
        var url = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=6&addressdetails=1&" +
                  "street=" + encodeURIComponent(street) + "&city=Bakersfield&state=CA&countrycodes=us";
        fetch(url, { headers: { "Accept": "application/json" } })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (!data || !data.length) { showSearchError("Street not found — try the street name only."); return; }
            // streets come back with type secondary/primary/residential/etc
            var streets = data.filter(function (r) {
              return (r.class === "highway" || !r.class) && r.type && r.type !== "house";
            });
            if (!streets.length) { showSearchError("Street not found — try the street name only."); return; }
            renderSuggestions(streets);
          })
          .catch(function () { showSearchError("Search failed — try again."); });
      }, 350);
    });

    // Enter picks the first suggestion (mobile keyboards have no click)
    searchInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && suggestions.length) {
        e.preventDefault();
        selectSuggestion(0);
      }
    });

    // click outside the search area clears the dropdown
    document.addEventListener("click", function (e) {
      var box = document.querySelector(".ov-search");
      if (box && !box.contains(e.target)) {
        if (suggestions.length) { searchResult.innerHTML = ""; suggestions = []; }
      }
    });
  }

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
