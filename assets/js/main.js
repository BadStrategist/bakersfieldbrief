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
  var ADSENSE_CLIENT = "ca-pub-7618641338292119"; // policeradio.org AdSense account
  // Real ad-unit slot IDs from the AdSense dashboard (Ads → By ad unit).
  // "0000000000" = not wired yet; the loader stays dormant until set.
  var SLOT_IDS = { "home-hero": "0000000000", "site-footer": "0000000000" };
  var CONSENT_KEY = "bdb-consent";
  var ADSENSE_LOADED = false;

  function loadAdsense() {
    if (ADSENSE_LOADED) return;
    ADSENSE_LOADED = true;
    var sc = document.createElement("script");
    sc.src = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=" +
             ADSENSE_CLIENT;
    sc.async = true;
    sc.crossOrigin = "anonymous";
    document.head.appendChild(sc);
  }

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
      loadAdsense();   // enables Auto Ads (dashboard-configured) post-consent
      injectSlots();
    });
    bar.appendChild(ok);
    document.body.appendChild(bar);
    document.body.style.paddingBottom = "64px";
  }

  function renderSlot(holder) {
    if (!ADSENSE_CLIENT || !consentGranted()) return;
    if (holder.hasAttribute("data-rendered")) return; // already filled
    var slotId = SLOT_IDS[holder.getAttribute("data-ad-slot") || ""] || "0000000000";
    if (slotId === "0000000000") return; // no real ad unit yet — stay inert
    holder.setAttribute("data-rendered", "1");
    var label = document.createElement("div");
    label.className = "ad-label";
    label.textContent = "Advertisement";
    holder.appendChild(label);
    try {
      var ins = document.createElement("ins");
      ins.className = "adsbygoogle";
      ins.style.cssText = "display:block";
      ins.setAttribute("data-ad-client", ADSENSE_CLIENT);
      ins.setAttribute("data-ad-slot", slotId);
      ins.setAttribute("data-ad-format", "auto");
      ins.setAttribute("data-full-width-responsive", "true");
      holder.appendChild(ins);
      loadAdsense();
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch (e) { /* leave label only */ }
  }

  function injectSlots() {
    document.querySelectorAll(".ad-slot[data-ad-slot]").forEach(renderSlot);
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
    window.addEventListener("load", function () {
      if (consentGranted()) loadAdsense();  // returning consenting visitors
      injectSlots();
    });
  }

  /* ---------- newsletter thank-you modal ----------
     The subscribe form posts to the Cloudflare Pages Function (/api/newsletter)
     which proxies to MailerLite with the server-side token. On submit we show
     the in-page thank-you card (what you'll receive) and suppress the default
     navigation so the visitor stays on the page; the signup goes through via
     the XHR. */
  (function () {
    var form = document.getElementById("nl-form");
    var modal = document.getElementById("nl-modal");

    // If JS is unavailable, the form action (/api/newsletter) is the fallback.

    // On legacy pages (older daily archives) there may be no id="nl-form"
    // and no modal markup — but there CAN be a leftover mailto: form that
    // triggers the browser "this form is not secure" warning and opens the
    // email client. Intercept it: show a lightweight inline notice instead.
    var legacy = document.querySelector('.nl-form[action^="mailto:"]');
    if (!form && legacy) {
      legacy.addEventListener("submit", function (e) {
        e.preventDefault();
        var box = document.createElement("div");
        box.style.cssText = "margin-top:10px;padding:12px 14px;border:1px solid #DC9A1F;" +
          "border-radius:6px;background:#FBEED2;color:#232B30;font-size:14px;";
        box.textContent = "Thanks! Please use the subscribe form on the homepage " +
          "(bakersfieldbrief.com) — it's the secure, one-click way to get the daily brief.";
        legacy.parentNode.insertBefore(box, legacy.nextSibling);
        legacy.querySelector("button").disabled = true;
      });
      return;
    }
    if (!form || !modal) return;

    var lastFocus = null;

    function openModal() {
      lastFocus = document.activeElement;
      modal.classList.add("open");
      modal.setAttribute("aria-hidden", "false");
      var done = modal.querySelector("[data-nl-close].btn");
      if (done) done.focus();
      document.addEventListener("keydown", onKey, true);
    }

    function closeModal() {
      modal.classList.remove("open");
      modal.setAttribute("aria-hidden", "true");
      document.removeEventListener("keydown", onKey, true);
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    function onKey(e) {
      if (e.key === "Escape") { closeModal(); return; }
      if (e.key === "Tab") {  // keep focus inside the card
        var focusables = modal.querySelectorAll(
          "button, [href], input, select, textarea, [tabindex]:not([tabindex=\"-1\"])"
        );
        if (!focusables.length) return;
        var first = focusables[0], last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var email = form.querySelector('input[name="email"]');
      if (!email || !email.value || !email.checkValidity()) { email.reportValidity(); return; }

      // POST to the Cloudflare Pages Function (proxies to MailerLite with the
      // server-side token). No navigation; show the thank-you modal on success.
      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/newsletter", true);
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.onload = function () {
        // 2xx or even a soft failure -> show the card (don't trap the reader)
        openModal();
      };
      xhr.onerror = function () {
        openModal();  // network hiccup — still show the thank-you card
      };
      xhr.send(JSON.stringify({ email: email.value }));
    });

    modal.querySelectorAll("[data-nl-close]").forEach(function (btn) {
      btn.addEventListener("click", closeModal);
    });
    modal.addEventListener("click", function (e) {
      if (e.target === modal) closeModal();
    });
  })();

  // pages pass build date via <html data-built>; expose for meta
  document.documentElement.setAttribute("data-js", "ok");
})();
