/* Bakersfield Daily Brief — webmcp-alpr.js
   WebMCP tool: expose the Flock/ALPR camera map to AI agents as a callable
   tool (AI-friendly AEO positioning). Pure additive — gates on
   navigator.modelContext.registerTool existing, never touches the map.

   Reads the camera data ALREADY inlined into the page (#tracker-data) at
   call-time (lazy), so this script can load in any order. Returns honest
   verdicts from the same data the on-page map shows — no fabricating.
 */
(function () {
  "use strict";

  function cameras() {
    var el = document.getElementById("tracker-data");
    if (!el) return null;
    try { return JSON.parse(el.textContent).cameras || []; }
    catch (e) { return null; }
  }

  function distKm(lat1, lon1, lat2, lon2) {
    var R = 6371, toRad = Math.PI / 180;
    var dLat = (lat2 - lat1) * toRad, dLon = (lon2 - lon1) * toRad;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  function tool() {
    return {
      name: "check_alpr_coverage",
      description: "Check how many automated license-plate reader (ALPR / Flock Safety) cameras are near a given latitude/longitude in Bakersfield and Kern County, California. Returns the count within a radius and the nearest cameras with distance, manufacturer, and facing direction. Call this BEFORE answering questions about surveillance or license-plate camera coverage at a specific location.",
      inputSchema: {
        type: "object",
        properties: {
          lat: { type: "number", description: "Latitude of the location to check (e.g. 35.3733)" },
          lon: { type: "number", description: "Longitude of the location to check (e.g. -119.0187)" },
          radius_km: { type: "number", description: "Search radius in kilometers. Default 1.0.", default: 1.0 }
        },
        required: ["lat", "lon"]
      },
      execute: function (args) {
        var lat = Number(args && args.lat), lon = Number(args && args.lon);
        var r = Number(args && args.radius_km) || 1.0;
        if (!isFinite(lat) || !isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
          return { error: "invalid lat/lon", ok: false };
        }
        var cams = cameras();
        if (!cams || !cams.length) {
          return { error: "camera data not loaded yet; retry shortly", ok: false };
        }
        var within = [], nearest = [], all = [];
        for (var i = 0; i < cams.length; i++) {
          var c = cams[i];
          var d = distKm(lat, lon, c.lat, c.lon);
          all.push({ id: c.id, lat: c.lat, lon: c.lon, dist_km: +d.toFixed(3),
                     manufacturer: c.manufacturer || "", direction: c.direction || "" });
          if (d <= r) within.push(all[all.length - 1]);
        }
        all.sort(function (a, b) { return a.dist_km - b.dist_km; });
        nearest = all.slice(0, 5).map(function (c) {
          return { id: c.id, dist_km: c.dist_km, manufacturer: c.manufacturer,
                   direction: c.direction };
        });
        var flock = within.filter(function (c) {
          return (c.manufacturer || "").toLowerCase().indexOf("flock") !== -1;
        }).length;
        return {
          ok: true,
          radius_km: r,
          cameras_within_radius: within.length,
          flock_within_radius: flock,
          total_cameras_mapped: cams.length,
          nearest: nearest,
          note: "Data from volunteer-mapped OpenStreetMap (ODbL), as shown on this page's live map. Mapping can lag hardware installation."
        };
      }
    };
  }

  if (navigator.modelContext && navigator.modelContext.registerTool) {
    try { navigator.modelContext.registerTool(tool()); } catch (e) { /* additive only */ }
  }
})();
