# Claude result for handover-esp32-sdr-www-split.md

- ran: 2026-10-13 08:11 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com

Nothing was edited or pushed. Two sources could not be opened: the tweet (HTTP 402) and the Adafruit blog post (HTTP 403). The radio claims below come from rtl-sdr.com, the ESPARGOS project page and the C5VRX repo.

# Part A: ESP32 as a scanner

1. **Verdict:** not usable as a scanner for our work.

2. **Frequency arithmetic:** none of these parts can tune 150-174, 450-512 or 769-869 MHz.
   - The ESPARGOS page lists only 2.2-2.7 GHz, plus 4.8-6.0 GHz on the ESP32-C5, and nothing below 2 GHz.
   - The bottom of the window, 2,200 MHz, is about 1,330 MHz above the top of our highest band (869 MHz).
   - This is the WiFi/Bluetooth front end, so firmware cannot move it. Reaching our bands would need an external downconverter, which is already more hardware than an RTL-SDR.

3. **Continuous monitoring:** no part streams demodulated audio.
   - Most boards send raw IQ in low-duty-cycle bursts over serial. ESPARGOS says packets between capture windows "may be missed".
   - The ESP32-S31 is the exception: it streams raw IQ continuously over native USB or Gigabit Ethernet through the SoapyESPSDR driver, which ESPARGOS marks "Experimental".
   - The rate is in dispute: rtl-sdr.com says up to 16 MS/s, while the ESPARGOS page reads as up to 20 MS/s over USB and 40 MS/s over Ethernet. I did not resolve that.
   - The ESP32-S3 plus FPGA project also streams continuously. I only saw it as a Reddit link from rtl-sdr.com and did not open it.

4. **Demodulation:** no narrowband FM, no P25 phase 1 or 2, and no trunked control channel in any of these projects.
   - ESPARGOS ships a spectrum and waterfall display and raw IQ only.
   - C5VRX demodulates wideband FM analog video at 40 MS/s, with no audio.
   - To get there you would need a downconverter, the S31 streaming path, and then the usual stack (SDRTrunk, OP25 or trunk-recorder) on a PC. All the real work is in parts that already run on a $30 dongle.

5. **Against the baseline we could just buy:**

| | ESP32 trick | RTL-SDR (~$30) | Airspy |
|---|---|---|---|
| Our three bands | None | All three | All three |
| Continuous streaming | S31 only, experimental | Yes | Yes |
| Sample rate | Up to 80 MS/s captured to RAM; far less leaves the chip | About 2.4 MS/s, enough for a control channel plus nearby voice | 10 MS/s on the R2, covering more of a trunked system at once |
| Software | A waterfall and an experimental driver | SDRTrunk, OP25, trunk-recorder, all mature | Same |
| Work to get there | Build an RF front end and port a driver | Plug in and configure | Plug in and configure |

   The RTL-SDR and Airspy columns are from general knowledge, not checked today.

6. **Cost of the hidden feature:**
   - **Documented:** no. ESPARGOS reverse engineered the `adctrig` function in Espressif's `librftest` library and uses debug registers.
   - **Stable:** fragile. C5VRX pins ESP-IDF 6.0.2 because its filter and DC correction need "the exact libphy of IDF 6.0.2"; with another PHY they are disabled and the build warns. So a firmware or SDK update can kill it.
   - **Breaks normal WiFi/BT:** neither source says. It takes over the same radio, so assume yes while capturing; that is my inference.
   - **Silicon revisions:** no revision requirement is stated. It is model specific: 5 GHz only on the C5, streaming only on the S31.

7. **Transmit or receive:** everything published is receive only; ESPARGOS says transmit is possible but is withholding it "due to the potential for misuse".

8. **Narrowest real use:** C5VRX, a 5.8 GHz analog FPV video receiver on a Seeed XIAO ESP32-C5 with a resistor DAC, covering 48 channels and outputting composite video.
   - It is a 223-star research project with some features marked field-test pending.
   - It would not give audio, digital FPV (DJI, and HDZero is unqualified), recording, or anything on public safety bands.
   - It has no use for the overnight report or policeradio.org.

# Part B: the www duplicate host

**The answer is not "do nothing". Add one www-to-apex 301 in Cloudflare; nothing changes in the repo.**

## 1. The split, in plain words

The site answers at two addresses, `bakersfieldbrief.com` and `www.bakersfieldbrief.com`, and both hand over the full page. Three things are in play:

- **The 301 redirect:** this is the only one Google treats as close to an order, and we do not have one between the hosts. The only 301s are http to https on the same host (`http://www...` goes to `https://www...`).
- **The canonical tag:** every www page says "the real copy is on the apex". I confirmed that on the www homepage and on `/briefs/2026-10-10/`. Google treats this as a hint it may overrule.
- **The duplicate host serving 200:** this is what makes the www URLs indexable at all.

Google mostly follows the canonical. The www rows in Search Console are the places where it did not, because that report files clicks under the URL Google itself chose.

## 2. What it costs today

- **Costs:** split rows in the Pages report, a handful of URLs where Google shows www instead of the apex, and some doubled crawling on a 181-URL site. Your one example is a single click on a www row out of 281.
- **Does not cost:** lost clicks (the www visitor got the same page), a penalty, or undercounted totals. The domain property counts both hosts, so 281 and 8,996 are whole.
- I did not read Search Console myself; those figures are yours.

## 3. The fix and the order

The Cloudflare zone owns the fix, not the repo:

- **`CNAME`** contains only `bakersfieldbrief.com`. It is a GitHub Pages convention and Cloudflare Pages ignores it.
- **`_redirects`** is written by `build/build_all.py:227` and holds path rules only. It cannot match on hostname.
- **`functions/`** has no `_middleware.js`, only the API and the 410 handlers.
- **Cloudflare:** I had no dashboard access. From outside, both hosts are on Cloudflare nameservers, proxied, on the same IPs, and www serves the Pages site and its Functions (`/api/fires` returns 200). So www is attached to the `bakersfieldbrief` Pages project.

Order:

1. In the Cloudflare dashboard, add a Redirect Rule on the zone: hostname equals `www.bakersfieldbrief.com`, 301 to `https://bakersfieldbrief.com` plus the path, preserve the query string.
2. Leave the www DNS record and the Pages custom domain in place. The rule only fires while www is proxied and has a certificate.
3. Verify with curl: www `/` and a deep URL return one 301 hop to the apex, the apex still returns 200, and `/api/fires` on the apex still returns 200.
4. No Search Console action is needed. The two bogus sitemap entries are unrelated and harmless: `/briefs/` and `/overnight/` are HTML pages returning 200, so they fail to parse as sitemaps.

## 4. Is the canonical enough on its own?

It is nearly enough, which is why the cost is small. It is not fully enough, because Google has already overruled it for some URLs. If we change nothing there is no deadline, and it may never fully consolidate. With the 301, URLs typically switch as they are recrawled, over days to a few weeks. The www rows stay in a 90-day report until they age out.

## 5. Redirect Rule vs `functions/_middleware.js`

**The Redirect Rule is right here.**

- **Redirect Rule:** it runs at the edge before Pages, involves no code or deploy, and is undone with one toggle. The risks are a wrong match expression causing a loop, and a POST to www being turned into a GET. Nothing in our source, templates, workflows or latest email references the www host (grep found zero), so the POST risk is low.
- **Middleware:** it runs on every request to the site, including static pages. That puts Functions billing and limits on all traffic, and a bug in it takes down every page instead of just one redirect. It also ships through the shared deploy pipeline. Its one advantage is that it could also redirect `bakersfieldbrief.pages.dev`, which serves 200 today as well. That host carries the apex canonical too, and is not worth the risk.

## 6. Is "do nothing" the answer?

No, but it is close. Doing nothing is safe and costs very little; the rule is a five-minute change that removes the ambiguity for good.

--- exit: 0 ---
