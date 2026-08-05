/* Bakersfield Daily Brief — main.js
   - mobile nav toggle (class-based, aria-expanded)
   - consent-gated ad slots: ads render ONLY when ADSENSE_CLIENT is set
     (post-approval) AND the visitor granted consent. Inert placeholders
     before that — the site is fully self-sufficient without ads.
   - site-wide above-footer ad slot injection
   - relative-path safety: resolves root-absolute hrefs for project-page
     subpath hosting (works at any depth, survives the custom-domain switch)
 */
(function () {
  "use strict";

  /* ---------- nav toggle ---------- */
  var toggle = document.querySelector(".nav-toggle");
  var list = document.querySelector(".nav-list");
  if (toggle && list) {
    toggle.addEventListener("click", function () {
      var open = list.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    list.addEventListener("click", function (e) {
      if (e.target.closest("a")) {
        list.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  /* ---------- root-absolute href resolution (safety net) ----------
     All internal links are generated relative at build time, so this only
     catches any hand-written root-absolute hrefs (e.g. "/privacy/") so the
     site also works under the github.io/<repo>/ subpath before the custom
     domain goes live. */
  (function () {
    var dirs = location.pathname.split("/");
    dirs.pop(); // drop the page filename
    var toRoot = new Array(Math.max(dirs.length - 1, 0) + 1).join("../");
    Array.prototype.forEach.call(document.querySelectorAll('a[href^="/"]'), function (a) {
      var href = a.getAttribute("href");
      if (href.charAt(1) === "/") return; // protocol-relative — leave
      a.setAttribute("href", toRoot + href.replace(/^\//, ""));
    });
  })();

  /* ---------- ads (consent-gated, inert until approved) ---------- */
  var ADSENSE_CLIENT = ""; // set post-approval, e.g. "ca-pub-XXXXXXXXXXXXXXXX"
  var CONSENT_KEY = "bdb-consent";

  function consentGranted() {
    try { return localStorage.getItem(CONSENT_KEY) === "granted"; }
    catch (e) { return false; }
  }
  function consentBanner() {
    if (consentGranted() || !ADSENSE_CLIENT) return;
    var bar = document.createElement("div");
    bar.id = "consent-bar";
    bar.style.cssText = "position:fixed;bottom:0;left:0;right:0;background:#20262C;color:#fff;" +
      "padding:12px 18px;z-index:999;font-size:14px;display:flex;gap:14px;align-items:center;" +
      "justify-content:space-between;flex-wrap:wrap;";
    bar.innerHTML = "<span>This site shows ads only with your consent. We never sell your data. " +
      "<a href=\"privacy/\" style=\"color:#F3C76E\">Privacy policy</a></span>";
    var ok = document.createElement("button");
    ok.textContent = "OK, show ads";
    ok.style.cssText = "background:#DC9A1F;color:#20262C;border:0;padding:7px 16px;border-radius:4px;" +
      "font-weight:600;cursor:pointer;";
    ok.addEventListener("click", function () {
      try { localStorage.setItem(CONSENT_KEY, "granted"); } catch (e) {}
      bar.remove();
      injectSlots();
    });
    bar.appendChild(ok);
    document.body.appendChild(bar);
    document.body.style.paddingBottom = "64px";
  }

  function renderSlot(holder) {
    if (!ADSENSE_CLIENT || !consentGranted()) return;
    var label = document.createElement("div");
    label.className = "ad-label";
    label.textContent = "Advertisement";
    holder.appendChild(label);
    try {
      var ins = document.createElement("ins");
      ins.className = "adsbygoogle";
      ins.style.cssText = "display:block";
      ins.setAttribute("data-ad-client", ADSENSE_CLIENT);
      ins.setAttribute("data-ad-slot", holder.getAttribute("data-ad-slot") || "0000000000");
      ins.setAttribute("data-ad-format", "auto");
      ins.setAttribute("data-full-width-responsive", "true");
      holder.appendChild(ins);
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch (e) { /* leave label only */ }
  }

  function injectSlots() {
    document.querySelectorAll(".ad-slot[data-ad-slot]").forEach(function (h) {
      if (!h.hasAttribute("data-rendered")) {
        h.setAttribute("data-rendered", "1");
        renderSlot(h);
      }
    });
  }

  // above-footer slot injected once
  (function () {
    var foot = document.querySelector(".footer");
    if (!foot) return;
    var holder = document.createElement("div");
    holder.className = "ad-slot";
    holder.setAttribute("data-ad-slot", "site-footer");
    foot.parentNode.insertBefore(holder, foot);
    renderSlot(holder);
  })();

  if (ADSENSE_CLIENT) {
    consentBanner();
    window.addEventListener("load", injectSlots);
  }

  // pages pass build date via <html data-built>; expose for meta
  document.documentElement.setAttribute("data-js", "ok");
})();
