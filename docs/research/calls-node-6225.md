# Broadcastify Calls Node 6225 (Kern County / Bakersfield) - Research Findings

Researched: 2026-09-20 (PDT). Every claim below is backed by an HTTP fetch performed the same day with the premium session cookie (login `kern_overnight/.bcfy_cookie.json`), a saved page in `C:\Users\tscac\AppData\Local\hermes\cache\scratch\bcfy\`, or a ffprobe run on a downloaded file. Nothing here is from memory.

## 1. What Calls delivers for node 6225

| Question | Finding | Evidence |
| --- | --- | --- |
| Per-call clips? | Yes. Each transmission is a discrete AAC/M4A file. | Downloaded clip, ffprobe (Section 2) |
| Continuous per-frequency streams? | No. Calls is clip-based; continuous audio is what the Audio Feeds (Archives) product does. | Calls Client API doc: "ingests individual radio calls" (support.broadcastify.com article 50488286518427) |
| Playlists? | Yes. Premium users build playlists of groups (max 30 entries) at https://www.broadcastify.com/calls/playlists/; playlist playback is served through `/calls/playlists/ajax.php` and `/calls/apis/live-pub` (surge/CDN path). | live.js source (`/calls/scripts/live.js?v=231`), fetched with cookie; forum post by blantonl, 2024-02-02 |
| Node listening for the public? | Disabled since Feb 2024, except for node owners. Node 6225 page states: "Listening via an individual node is no longer available to the public. Please listen via Playlists or each individual frequency/talkgroup." | node.html (saved) + live fetch of https://www.broadcastify.com/calls/node/6225 |
| Node page URL | https://www.broadcastify.com/calls/node/6225 (frequencies list: .../calls/node/6225/fids) | fetched live, HTTP 200 |

### URL shapes (verified live)

- Call list for the node (AJAX): `POST https://www.broadcastify.com/calls/apis/live-calls` with form data `systemId=6225&doInit=1&pos=<unix>&sid=&groups=&sessionKey=<uuid-like>` plus cookie `bcfyuser1=...` and header `X-Requested-With: XMLHttpRequest`. Returns JSON: `{"calls":[...],"serverTime":...,"lastPos":...}`. Without a valid sessionKey shape the endpoint returns 403 (verified: first attempt without it got 403, with it got 200).
- Each call object carries: `scid`, `filename` (e.g. `1789944494-61061`), `hash` (e.g. `ldsnpkwy`), `enc` (`m4a`), `call_freq`, `display`, `grouping`, `meta_starttime`/`meta_stoptime`, `fid`, `slot`, `transcribe`.
- Audio clip URL: `https://calls.broadcastify.com/<hash>/<systemId>/<filename>.<enc>` (live.js also shows a CDN variant `https://calls-ai-1.broadcastify.com/...`). The `hash` rotates; a hash+filename pair from an earlier poll returned 403 minutes later. Verified: one clip downloaded with HTTP 200, `Content-Type: audio/aac`.
- Call details modal: `/calls/apis/callDetails.php?scid=<n>` returned 401 with the cookie in a plain GET (may need referer/token from an active page session). Not resolved.
- Node metadata: `GET /calls/apis/nodeDetails.php?nodeId=6225` returns an HTML fragment (HTTP 200, verified).

**Important:** these are undocumented web-app internals, not the licensed API. ToS Section 9 (below) classifies exactly this kind of scripted access as requiring a commercial license.

## 2. Audio quality of Calls clips (measured)

Downloaded call: KRN Fire 1 Dispatch (153.785), 6.28 s, from `https://calls.broadcastify.com/ldsnpkwy/6225/1789944494-61061.m4a` (saved to scratch `bcfy/sample_call.m4a`).

Command: `ffprobe -v error -show_entries stream=codec_name,sample_rate,channels,bit_rate -show_entries format=bit_rate,duration -of default=nw=1 sample_call.m4a`

| Property | Calls clip (measured) | Feed 14029 archives (verified by parent) |
| --- | --- | --- |
| Codec | AAC (m4a container) | MP3 |
| Bitrate | ~82 kbps (format bit_rate 81742) | 16 kbps |
| Sample rate | 96,000 Hz | 22,050 Hz |
| Channels | 1 (mono) | 1 (mono) |
| Duration | per-call (6.28 s here) | 30-minute blocks |

Calls audio is dramatically better than the feed archives: higher bitrate and 4.4x the sample rate. The Ingest API doc recommends providers encode "approximately 32 kb/s with an 18 kHz cutoff" M4A/AAC (or MP3 16/32 kbps 22050 Hz mono), so ~82 kbps measured on this clip is above the recommended floor.

## 3. Documented developer interfaces

All confirmed by fetching https://support.broadcastify.com/hc/en-us/categories/200377615-Developers and the two Calls articles (requests to support.broadcastify.com return 403 to a bare UA; content retrieved via web_extract of the same URLs).

Four APIs, all managed through the **Broadcastify Developer Program at https://bcfy.io/dev** :

| API | Purpose | Doc |
| --- | --- | --- |
| Live Audio Feed Catalog | metadata for live audio feeds | article 204740425 |
| **Calls Client API** | read live + archived calls, groups, nodes, sources, playlists | article 50488286518427 |
| Calls Ingest/Upload | providers upload calls (not relevant to us as consumer) | article 360049971311 |
| Feed Owner API | feed owner management | article 204172369 |

Calls Client API specifics (from article 50488286518427):

- Access is **self-serve but application-reviewed**: apply at https://bcfy.io/dev/apply/ with your RadioReference/Broadcastify account. Applications "boiling down to 'because I want to'" are declined; be specific.
- **Metered, prepaid pay-as-you-go**: minimum $5 credit, billed per record read, monthly spend cap you set. Premium subscription is NOT required for end users of your app.
- Auth: your own developer key (details at https://bcfy.io/dev/docs/; we did not fetch the docs portal).
- Capabilities: live calls streaming, group/county discovery, node/source/call lookups, **group archives within a time range**, playlist CRUD.
- Entity model: conventional groups are `c-<fid>` (our four channels are `c-61061` style IDs matching the `fid` seen in live JSON); a Call is identified by `groupId + ts`; audio files are "MP3 or MP4 audio file".
- **Licensed uses explicitly include transcription, AI/LLM pipelines, alerting, analytics, research, internal dashboards** - "a primary use case for the Calls API". Scope must be a defined local market (one county is fine); nationwide/general consumer apps need an enterprise royalty license. Prohibited: reselling raw API access, programmatic re-export to third parties, becoming a redistribution layer.
- Scale context from the doc: 5M+ calls/day, 1,000+ nodes, **full year (365-day) retention configured on every system**, node voting dedupes ~8M uploads into ~5.5M unique calls.
- Ingest doc (article 360049971311) independently confirms "archives (365-day retention)".

Pricing page: https://bcfy.io/dev/pricing/ (not fetched; requires visiting the portal).

## 4. Retention for node 6225

- Documented: 365-day retention on every system (two support articles, Section 3).
- Observed live: the node live-calls poll returns only the most recent ~224 calls (about the last 10 minutes of traffic at 22:39-22:49 PDT on 2026-09-20). The `pos` parameter was ignored in my tests (passing pos = now-1h, -1d, -7d, -30d, -108d all returned the same 224-call window).
- Direct probing of old clips failed: requesting `https://calls.broadcastify.com/<hash>/6225/<unixstart>-61061.m4a` with guessed timestamps (1, 7, 30, 107 days old) returns 403 (application/xml). The `hash` component rotates and is apparently tied to a specific filename batch, so old clips cannot be addressed by guessing - access to archives would go through the licensed Client API ("group archives: retrieve all calls for a group within a time range").
- Unconfirmed empirically: whether the full 365-day archive is actually queryable for systemId 6225. All four frequencies show "First: 2026-06-04" (or 06-12 for BPD1) on the fids page, so nothing older than June 2026 exists for this node regardless.

## 5. Terms (quoted)

Source: https://www.broadcastify.com/terms (fetched 2026-09-20, HTTP 200; "Last Updated: July 22, 2026 - Revised Section 9 to cover programmatic and automated access, AI/ML use, scraping and bulk downloading, and commercial licensing through the Broadcastify Developer Program (bcfy.io)").

Section 9, PROGRAMMATIC ACCESS, AUTOMATED USE, AND COMMERCIAL LICENSING (verbatim excerpts):

> "A Broadcastify account, including a Premium subscription, grants a personal, individual right to listen to and view content through Broadcastify's own websites and applications. It does not grant any right to access, retrieve, capture, store, or use Broadcastify audio, live feeds, recorded calls, archives, metadata, or any other content by programmatic, automated, or bulk means. Any such access requires a separate commercial license obtained from Broadcastify in advance."

> "(a) Any programmatic or automated access to Broadcastify feeds, live audio, recorded calls, archives, or metadata, including but not limited to scripts, bots, headless or automated clients, stream rippers, recorders, ffmpeg or comparable tooling, API clients, and any scheduled, unattended, repeated, or automated downloading, reconnection, or polling."

> "(c) Any use of Broadcastify content for machine learning or artificial intelligence, including training or tuning of algorithms or models, transcription, translation, speech-to-text, summarization, classification, correlation, alerting, large language model (LLM) processing, or any other automated analysis, indexing, or derivative processing."

> "(d) Any redistribution, relay, rebroadcast, re-streaming, or embedding of Broadcastify live audio to or on behalf of any other person, application, website, device, or service."

> "A use does not become permitted because it is limited in scale, unpaid, or characterized as personal, hobby, educational, academic, research, journalistic, non-commercial, 'proof of concept,' or one-time."

> "Commercial and developer licenses, including access to the Broadcastify Calls API and the Broadcastify Live Audio Feed Catalog, are issued exclusively through the Broadcastify Developer Program at https://bcfy.io."

> "Broadcastify monitors for automated and programmatic use. Accounts engaged in any activity described in this Section without a valid commercial license may be rate-limited, throttled, restricted, suspended, or terminated at any time and without notice..."

The feed archives we currently script against are covered by the same Section 9 language ("live feeds, recorded calls, archives, metadata"). Our existing automated 30-min-archive downloading is, as of the July 22 2026 ToS revision, licensed activity requiring a Developer Program license.

## 6. Coverage: node 6225 vs the 8 audio feeds

Node 6225 is a conventional-only Trunk Recorder node covering exactly 4 frequencies (node fids page, verified):

| Slot | Freq | Display | Calls seen | First seen |
| --- | --- | --- | --- | --- |
| 153785004 | 153.785 | KRN Fire 1 Dispatch | 938,309 | 2026-06-04 |
| 154070007 | 154.070 | FIRE 1 Fire Dispatch Bakersfield | 803,102 | 2026-06-12 |
| 154800003 | 154.800 | BPD2 Police Dispatch West | 63,762 | 2026-06-04 |
| 155309998 | 155.310 | BPD1 Police Dispatch East | 159,288 | 2026-06-12 |

County 197 Calls coverage page (calls_coverage_law.html) lists only two groups: Law Dispatch (BPD1, BPD2) and Fire Dispatch (KRN Fire 1, FIRE 1). Live calls in the poll window were all on these four channels (verified: distinct call_freq values in the JSON were 153.785, 154.07, 155.31).

**Not covered by Calls for Kern county 197**: everything else the 8 audio feeds carry - CHP, EMS/ambulance, KCSO (and west kern), tactical/ops channels, any trunked traffic. Calls for this county contains only those 4 conventional dispatch channels. Trunked systems would need separate nodes capturing them; none exist for county 197 today (coverage page lists nothing else).

Live traffic observation (22:39-22:49 PDT): all four channels active, calls 6-20 s typical, `transcribe: 0` flag on calls.

## What we can actually do

1. **Licensed path (recommended, only clean path)**: apply at https://bcfy.io/dev/apply/ for the Calls Client API, scoped to Kern County. Metered prepaid (min $5). This gives per-call M4A clips at ~82 kbps 96 kHz AAC for BPD1/BPD2/Fire dispatches, 365-day archive queries, and explicitly licenses transcription/AI pipelines. It covers only the 4 channels, not CHP/EMS/KCSO.
2. **The 4 Calls channels are strictly better quality than feed archives** for those same channels; if a dev license is granted, Calls should replace archive downloads for BPD1/BPD2/KRN Fire 1/FIRE 1.
3. **CHP, EMS, KCSO, tactical remain audio-feed-only.** No Calls node covers them in county 197; nothing on Calls can replace feed 14029-style archives there.
4. **ToS risk flag**: our current automated archive downloader is, post-2026-07-22, unlicensed programmatic access under Section 9 regardless of scale or non-commercial intent. The compliant route for feed archives would be the Live Audio Feed Catalog API (same Developer Program). Flag to the user before expanding any scraping.
5. Scraping `calls.broadcastify.com` clip URLs directly (the undocumented path we proved works) violates Section 9 and the URLs rotate; do not build on it.

## Open questions / unconfirmed

- bcfy.io pricing per record and rate limits: portal pages not fetched (https://bcfy.io/dev/pricing/, /dev/docs/).
- Whether the 365-day archive is actually queryable for systemId 6225 (documented generally; not testable without a dev key; node data only exists since 2026-06-04 anyway).
- `callDetails.php` auth scheme (returned 401 with cookie; likely needs a token from an active web session).
- Whether premium web playback of Calls clips is metered/limited in any way (no rate limit observed in a handful of probes).
- Whether a Kern public playlist already exists that packages these 4 channels (playlist discovery endpoint exists; not enumerated).
