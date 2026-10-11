/* Bakersfield Daily Brief: webmcp-cameras.js
   WebMCP tool: lets an AI agent ask /traffic-cameras/ for the current Kern County road
   status and the Caltrans camera list. Additive only: it gates on
   navigator.modelContext.registerTool existing and never touches the page.

   Everything it returns is read at call time from what the page already shows: the road
   status sentence and its Caltrans report time (#road-answer) and the camera list inlined
   at build (#cam-data). Nothing is made up, and a missing piece is reported as missing.
 */
(function () {
  "use strict";

  function cameras() {
    var el = document.getElementById("cam-data");
    if (!el) return null;
    try { return JSON.parse(el.textContent) || []; }
    catch (e) { return null; }
  }

  function roadStatus() {
    var el = document.getElementById("road-answer");
    if (!el) return null;
    return { text: el.textContent.replace(/\s+/g, " ").trim(),
             caltrans_report_time: el.getAttribute("data-asof") || null };
  }

  function tool() {
    return {
      name: "get_kern_traffic_cameras",
      description: "Get the current Caltrans road status for I-5 over Tejon Pass (the Grapevine), SR-58 over Tehachapi Pass and SR-99 in Kern County, California, with Caltrans' own report time, and the list of Caltrans traffic cameras in Kern County with a link to each current still picture. Optionally filter the cameras to one highway. Call this BEFORE answering questions about Bakersfield or Kern County traffic cameras or whether these highways are open.",
      inputSchema: {
        type: "object",
        properties: {
          route: { type: "string", description: "Optional highway to filter the cameras by, written as Caltrans does: I-5, SR-99, SR-58, SR-14, SR-178, US-395." }
        }
      },
      execute: function (args) {
        var cams = cameras();
        var status = roadStatus();
        if (!cams && !status) return { ok: false, error: "page data not loaded yet; retry shortly" };
        var want = String((args && args.route) || "").toUpperCase().replace(/\s+/g, "");
        var list = (cams || []).filter(function (c) {
          return !want || String(c.route || "").toUpperCase() === want;
        }).map(function (c) {
          return {
            name: c.label, route: c.route, caltrans_direction_label: c.direction || null,
            near: c.near || null, elevation_ft: c.elevation_ft == null ? null : Math.round(c.elevation_ft),
            in_service: !!c.in_service, new_picture_every_minutes: c.update_min || null,
            picture_url: c.in_service ? location.origin + "/api/cameras?img=" + encodeURIComponent(c.id) : null,
            page_url: location.origin + "/traffic-cameras/#cam-" + c.id
          };
        });
        return {
          ok: true,
          road_status: status,
          cameras_total: cams ? cams.length : null,
          cameras_returned: list.length,
          cameras: list,
          note: "Road status is Caltrans' report as of the time given. Pictures are Caltrans stills, 320 by 260 pixels, replaced on the schedule listed for each camera. No video, and no archive of past pictures."
        };
      }
    };
  }

  if (navigator.modelContext && navigator.modelContext.registerTool) {
    try { navigator.modelContext.registerTool(tool()); } catch (e) { /* additive only */ }
  }
})();
