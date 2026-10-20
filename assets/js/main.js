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

  /* Meta pixel: same consent as ads, and never when the browser sends
     Global Privacy Control. "" = not set up yet; the loader stays dormant. */
  var META_PIXEL_ID = "";
  function loadMetaPixel() {
    if (!META_PIXEL_ID || window.fbq || navigator.globalPrivacyControl) return;
    /* eslint-disable */
    !function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
    n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
    n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
    t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,
    document,'script','https://connect.facebook.net/en_US/fbevents.js');
    /* eslint-enable */
    window.fbq("init", META_PIXEL_ID);
    window.fbq("track", "PageView");
  }

  function consentGranted() {
    try { return localStorage.getItem(CONSENT_KEY) === "granted"; }
    catch (e) { return false; }
  }
  function consentDismissed() {
    try { return localStorage.getItem(CONSENT_KEY) === "dismissed"; }
    catch (e) { return false; }
  }

  function consentBanner() {
    if (consentGranted() || consentDismissed() || !ADSENSE_CLIENT) return;
    var bar = document.createElement("div");
    bar.id = "consent-bar";
    bar.style.cssText = "position:fixed;bottom:0;left:0;right:0;background:#20262C;color:#fff;" +
      "padding:12px 18px;z-index:999;font-size:14px;display:flex;gap:14px;align-items:center;" +
      "justify-content:space-between;flex-wrap:wrap;";
    bar.innerHTML = "<span>This site shows ads and uses Meta ad measurement only with your consent. " +
      "We never sell your data. " +
      "<a href=\"privacy/\" style=\"color:#F3C76E\">Privacy policy</a></span>";
    var btnWrap = document.createElement("span");
    btnWrap.style.cssText = "display:flex;gap:8px;";
    var ok = document.createElement("button");
    ok.textContent = "OK, show ads";
    ok.style.cssText = "background:#DC9A1F;color:#20262C;border:0;padding:7px 16px;border-radius:4px;" +
      "font-weight:600;cursor:pointer;";
    ok.addEventListener("click", function () {
      try { localStorage.setItem(CONSENT_KEY, "granted"); } catch (e) {}
      bar.remove();
      document.body.style.paddingBottom = "";
      loadAdsense();   // enables Auto Ads (dashboard-configured) post-consent
      loadMetaPixel();
      injectSlots();
    });
    // a dismiss that persists, so visitors who decline aren't re-prompted on
    // every page and the fixed bar stops covering hero/direct-answer content
    var no = document.createElement("button");
    no.textContent = "No thanks";
    no.style.cssText = "background:transparent;color:#F3C76E;border:1px solid #F3C76E;padding:7px 16px;" +
      "border-radius:4px;font-weight:600;cursor:pointer;";
    no.addEventListener("click", function () {
      try { localStorage.setItem(CONSENT_KEY, "dismissed"); } catch (e) {}
      bar.remove();
      document.body.style.paddingBottom = "";
    });
    btnWrap.appendChild(no);
    btnWrap.appendChild(ok);
    bar.appendChild(btnWrap);
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
      if (consentGranted()) { loadAdsense(); loadMetaPixel(); }  // returning consenting visitors
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
    // Every signup form on the page (the footer block and the overnight card) posts here.
    var forms = document.querySelectorAll('form.nl-form[action="/api/newsletter"]');
    if (!form && forms.length) form = forms[0];
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

    function onSubmit(e) {
      e.preventDefault();
      var email = e.currentTarget.querySelector('input[name="email"]');
      if (!email || !email.value || !email.checkValidity()) { email.reportValidity(); return; }

      // POST to the Cloudflare Pages Function (proxies to MailerLite with the
      // server-side token). No navigation; show the thank-you modal on success.
      if (window.fbq) window.fbq("track", "Lead");  // only present with consent
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
    }
    Array.prototype.forEach.call(forms, function (f) { f.addEventListener("submit", onSubmit); });

    modal.querySelectorAll("[data-nl-close]").forEach(function (btn) {
      btn.addEventListener("click", closeModal);
    });
    modal.addEventListener("click", function (e) {
      if (e.target === modal) closeModal();
    });
  })();

  /* ---------- ad-visitor funnel (GoatCounter events) ----------
     Meta appends ?fbclid= to every ad click. A visitor who lands with it is
     an ad visitor; we remember that in first-party storage (a flag and a
     date, no ID) and count, in aggregate, what ad visitors do next. Each
     event fires at most once per tab session ("returned" once per browser):
       ad/landed        arrived from a Facebook/Instagram ad
       ad/stayed-30s    page open and visible for 30 seconds
       ad/scrolled-75   scrolled three quarters of the way down
       ad/2nd-page      opened another page on the site
       ad/subscribed    submitted the newsletter form
       ad/returned      came back on a later day without clicking an ad
     Read them on the GoatCounter dashboard (kulture), or per event at
     https://kulture.goatcounter.com/counter/ad%2F<name>.json */
  (function () {
    var ss, ls;
    try { ss = window.sessionStorage; ls = window.localStorage; } catch (e) { return; }
    if (!ss || !ls) return;

    function get(s, k) { try { return s.getItem(k); } catch (e) { return null; } }
    function set(s, k, v) { try { s.setItem(k, v); } catch (e) {} }

    // Mark an event as sent only once it really went out, so a visitor who
    // leaves before count.js loads is counted on their next page instead.
    function send(name, store, key) {
      var tries = 0;
      (function go() {
        var gc = window.goatcounter;
        if (get(store, key)) return;
        if (gc && gc.count) {
          set(store, key, "1");
          gc.count({ path: "ad/" + name, title: location.pathname, event: true });
        } else if (++tries < 20) {
          setTimeout(go, 500);  // count.js loads async
        }
      })();
    }
    function once(name) { send(name, ss, "bb_ad_" + name); }

    var today = new Date().toISOString().slice(0, 10);
    var fromAd = /[?&]fbclid=/.test(location.search);

    if (fromAd) {
      if (!get(ls, "bb_ad_day")) set(ls, "bb_ad_day", today);
      // a second ad click in the same tab session is not a new landing
      if (!get(ss, "bb_ad")) {
        set(ss, "bb_ad", "1");
        set(ss, "bb_ad_first", location.pathname);
      }
    } else if (get(ls, "bb_ad_day")) {
      if (get(ss, "bb_ad")) {
        if (location.pathname !== get(ss, "bb_ad_first")) once("2nd-page");
      } else if (get(ls, "bb_ad_day") < today) {
        send("returned", ls, "bb_ad_returned");
      }
    }

    if (!get(ss, "bb_ad")) return;
    once("landed");  // no-op once sent; retries here if the first page closed too soon

    // 30 seconds of visible time on this page
    var seen = 0, last = document.hidden ? 0 : Date.now();
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) { if (last) seen += Date.now() - last; last = 0; }
      else last = Date.now();
    });
    var timer = setInterval(function () {
      var t = seen + (last ? Date.now() - last : 0);
      if (t >= 30000) { clearInterval(timer); once("stayed-30s"); }
    }, 2000);

    function onScroll() {
      var h = document.documentElement.scrollHeight - window.innerHeight;
      if (h > 0 && window.scrollY / h >= 0.75) {
        window.removeEventListener("scroll", onScroll);
        once("scrolled-75");
      }
    }
    window.addEventListener("scroll", onScroll, { passive: true });

    Array.prototype.forEach.call(
      document.querySelectorAll('form.nl-form[action="/api/newsletter"]'),
      function (f) {
        f.addEventListener("submit", function () {
          var email = f.querySelector('input[name="email"]');
          if (email && email.value && email.checkValidity()) once("subscribed");
        });
      });
  })();

  // pages pass build date via <html data-built>; expose for meta
  document.documentElement.setAttribute("data-js", "ok");
})();
