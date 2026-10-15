Two questions from the owner. Answer both in one reply, in this order.

# Part A: can this ESP32 SDR trick be a scanner for us?

The owner saw this and wants a verdict: can we use it as a scanner?

Sources (verify each at the source, do not trust the blog post alone):
- Tweet, 2026-10-12 14:46 UTC, @adafruit: "Various projects find hidden SDR capabilities in ESP32 microcontrollers"
  https://x.com/adafruit/status/2109657005602615694
- Adafruit blog: https://blog.adafruit.com/2026/10/12/various-projects-find-hidden-sdr-capabilities-in-esp32-microcontrollers/
- rtl-sdr.com: https://www.rtl-sdr.com/various-projects-independently-find-hidden-sdr-capabilities-in-esp32-microcontrollers/
- GitHub, C5VRX: https://github.com/Twotoz/C5VRX

What the blog post claims (unverified, check it):
- The ESPARGOS team found an undocumented feature that lets firmware bypass the fixed WiFi and Bluetooth radio functions and capture raw IQ baseband samples.
- Tuning: 2.2 to 2.7 GHz, plus 4.8 to 6.0 GHz on the ESP32-C5.
- Sample rates to 80 MS/s, analog bandwidth roughly 13 to 54 MHz depending on the part.
- The catch is output bandwidth: most chips export snapshots to a PC only, so they are a spectrum analyzer and not a continuous demodulator. The ESP32-S31 is the exception, streaming up to 16 MS/s over Gigabit Ethernet.
- An ESP-WebSDR page flashes the firmware to most ESP32 dev boards from a browser and shows live spectrum and waterfall.
- Two other projects found the same behaviour: one pairs an ESP32-S3 with an FPGA as a USB3 front end for continuous IQ streaming; the other, C5VRX, uses an ESP32-C5 as a 5.8 GHz FPV video receiver that demodulates onboard and outputs composite video through a resistor DAC.

What "scanner" means here, and it is the whole question:
- Our scanner work is public safety radio in Kern County: VHF 150 to 174 MHz, UHF 450 to 512 MHz, and 700/800 MHz 769 to 869 MHz trunked systems.
- The owner runs zip-programmed Baofeng UV-5R and UV-5R Mini handhelds, and we run scanner-audio pipelines: feeds, speech to text, the overnight report, and policeradio.org (repo: C:\Users\tscac\Projects\policeradio-content).

Deliver:
1. **Verdict in one line**: usable as a scanner for our work, or not.
2. **The frequency arithmetic**: can any of these parts tune 150-174, 450-512 or 769-869 MHz at all? The claimed 2.2-2.7 GHz and 4.8-6.0 GHz windows are the WiFi/BT front end, so say plainly what that means for our three bands, and do not repeat the claimed numbers as if they covered our bands.
3. **Continuous monitoring**: can any part stream demodulated audio continuously, or is it snapshot only? Name the part and the mechanism if yes.
4. **Demodulation**: does any of these projects demodulate narrowband FM, P25 phase 1 or 2, or a trunked control channel? If not, say what would be needed.
5. **Compare against the baseline we could just buy**: an RTL-SDR at about $30, or an Airspy. Cover frequency coverage, continuous streaming, sample rate, software maturity, and the amount of work to get there.
6. **The cost of the hidden feature**: is it documented, is it stable, does it break normal WiFi/BT use, does it need specific silicon revisions, and does a firmware update kill it?
7. **Transmit or receive only**, in one line.
8. **The narrowest real use if one exists** (5.8 GHz FPV video monitoring is the obvious candidate), and what that use would not do.

# Part B: the www duplicate host. Explain the split, and the fix.

Verified today, 2026-10-13, with curl:
- `https://www.bakersfieldbrief.com/` returns **200 with no redirect**.
- `https://www.bakersfieldbrief.com/briefs/2026-10-10/` returns **200 with no redirect**.
- `https://bakersfieldbrief.com/` returns 200.
- The www response carries `<link rel="canonical" href="https://bakersfieldbrief.com/">` and the same title as the apex.

Search Console, domain property `sc-domain:bakersfieldbrief.com`, read through the owner's Chrome on CDP port 9223:
- 90 days: 281 clicks, 8,996 impressions, 79 pages with impressions.
- The Pages table lists www and the apex as **separate rows**, for example `https://www.bakersfieldbrief.com/briefs/2026-09-26/` with 1 click against the apex twin at 0 clicks.
- The real `sitemap.xml` reads Success with 181 discovered pages. Two bogus sitemap entries sit beside it (`/briefs/` and `/overnight/`, type Unknown, 1 error each) and this UI build exposes no way to remove them.

Deliver:
1. **Explain the split in plain words the owner can repeat to someone else.** Be exact about the three things and which one Google actually follows: the 301 redirect, the canonical tag, and the duplicate host serving 200.
2. **What it costs today**, from the numbers above, and what it does not cost. Do not inflate it.
3. **The correct fix and the order to do it in.** Check this repo (CNAME, the Pages project, `functions/`, `_redirects`) and the Cloudflare setup and say which layer owns the fix.
4. **Whether the canonical tag we already ship is enough on its own**, and how long Google takes to consolidate if we change nothing.
5. **Cloudflare Redirect Rule vs a Pages Function (`functions/_middleware.js`)**: which is right here, and the risk of each on a production site.
6. Say plainly if the answer is "do nothing, the canonical handles it". That is a valid answer.

# Ground rules
- Read and verify. Do not edit any file in this repo or anywhere else, and do not push.
- Verify each number at the source: curl for the HTTP behaviour, the rtl-sdr.com page and the GitHub repos for the radio claims. If a claim cannot be verified, say so.
- Keep the whole reply tight.
