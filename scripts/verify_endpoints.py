#!/usr/bin/env python3
"""One-shot verification of every Bakersfield Daily Brief data source.

Prints compact OK/FAIL + a sample per source. Run: python scripts/verify_endpoints.py
"""
import json, re, sys, datetime
import requests
import xml.etree.ElementTree as ET

UA = {"User-Agent": "BakersfieldDailyBriefBot/1.0 (local news site; contact: editor@bakersfieldbrief.com)"}
S = requests.Session()
S.headers.update(UA)
S.timeout = 30

results = []

def check(name, ok, note):
    results.append((name, ok, note))
    print(f"[{'OK ' if ok else 'FAIL'}] {name}: {note}")

# 1. eSCRIBE city meetings
try:
    today = datetime.date.today()
    start = today.isoformat()
    end = (today + datetime.timedelta(days=30)).isoformat()
    r = S.post("https://pub-bakersfield.escribemeetings.com/MeetingsCalendarView.aspx/GetCalendarMeetings",
               json={"calendarStartDate": start, "calendarEndDate": end})
    j = r.json()
    data = j.get("d")
    if isinstance(data, str):
        data = json.loads(data)
    n = len(data)
    sample = data[0] if n else {}
    check("escribe", n > 0, f"{n} meetings; first: {sample.get('MeetingTitle') or sample.get('Title') or list(sample.keys())[:6]}")
except Exception as e:
    check("escribe", False, f"{type(e).__name__}: {e}")

# 2. Kern County board agenda PDF
try:
    r = S.get("https://itsapps.kerncounty.com/clerk/minutes/boardagenda.pdf")
    r.raise_for_status()
    import pdfplumber
    with pdfplumber.open(io := __import__("io").BytesIO(r.content)) as pdf:
        n_pages = len(pdf.pages)
        text = pdf.pages[0].extract_text() or ""
    check("kern_board", n_pages > 0 and len(text) > 50, f"{n_pages} pages, {len(text)} chars on p1: {text[:80]!r}")
except Exception as e:
    check("kern_board", False, f"{type(e).__name__}: {e}")

# 3. CA ABC liquor licenses
try:
    r = S.get("https://www.abc.ca.gov/licensing/licensing-reports/new-applications/")
    m = re.search(r'name=["\']abclqs_daily_report["\'][^>]*value=["\']([^"\']+)["\']', r.text)
    if not m:
        m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']abclqs_daily_report["\']', r.text)
    nonce = m.group(1) if m else None
    if not nonce:
        check("abc", False, "no abclqs_daily_report nonce found")
    else:
        date = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%m/%d/%Y")
        r2 = S.post("https://www.abc.ca.gov/wp-admin/admin-post.php",
                    data={"action": "abclqs_daily_report", "url": "/licensing/licensing-reports/new-applications/",
                          "rpttype": "2", "abclqs_daily_report": nonce,
                          "_wp_http_referer": "/licensing/licensing-reports/new-applications/",
                          "abclqs-date": date})
        n_bak = r2.text.count("BAKERSFIELD")
        tbl = "<table" in r2.text.lower()
        check("abc", tbl, f"nonce ok, table={tbl}, 'BAKERSFIELD' x{n_bak}, resp {len(r2.text)} bytes")
except Exception as e:
    check("abc", False, f"{type(e).__name__}: {e}")

# 4. News RSS
for name, url in [("kget", "https://www.kget.com/feed/"), ("turnto23", "https://www.turnto23.com/news/local-news.rss")]:
    try:
        r = S.get(url)
        r.raise_for_status()
        import feedparser
        f = feedparser.parse(r.content)
        n = len(f.entries)
        t = f.entries[0].title if n else ""
        check(name, n > 0, f"{n} entries; first: {t[:60]}")
    except Exception as e:
        check(name, False, f"{type(e).__name__}: {e}")

# 5. NWS weather alerts
try:
    r = S.get("https://api.weather.gov/alerts/active?area=CA")
    alerts = [a for a in r.json().get("features", []) if "Kern" in (a["properties"].get("areaDesc") or "")]
    check("nws", True, f"{len(r.json().get('features', []))} CA alerts, {len(alerts)} Kern; e.g. {alerts[0]['properties']['event'] if alerts else 'none'}")
except Exception as e:
    check("nws", False, f"{type(e).__name__}: {e}")

# 6. CHP incidents
try:
    r = S.get("https://media.chp.ca.gov/sa_xml/sa.xml")
    root = ET.fromstring(r.content)
    incidents = []
    for center in root.findall("Center"):
        if (center.get("ID") or "").upper() == "LAHB":
            for disp in center.findall("Dispatch"):
                if (disp.get("ID") or "").upper() == "BFCC":
                    for log in disp.findall("Log"):
                        incidents.append(log)
    l = incidents[0] if incidents else None
    check("chp", True, f"LAHB/BFCC logs: {len(incidents)}; sample: {l.findtext('LogType') if l is not None else 'none'} @ {l.findtext('Location') if l is not None else ''}")
except Exception as e:
    check("chp", False, f"{type(e).__name__}: {e}")

# 7. Isabella CDEC
try:
    end = datetime.date.today().isoformat()
    start = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
    url = f"https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet?Stations=ISB&SensorNums=15&dur_code=D&Start={start}&End={end}"
    r = S.get(url)
    j = r.json()
    rows = j if isinstance(j, list) else j.get("data", [])
    last = rows[-1] if rows else None
    check("cdec", len(rows) > 0 and last is not None,
          f"ISB rows: {len(rows)}; last: {last.get('obsDate')} value={last.get('value')} {last.get('units')} (sensor {last.get('SENSOR_NUM')})" if last else "no rows")
except Exception as e:
    check("cdec", False, f"{type(e).__name__}: {e}")

# 8. USGS earthquakes
try:
    url = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
           "&latitude=35.37&longitude=-119.02&maxradiuskm=100&orderby=time&limit=10")
    j = S.get(url).json()
    feats = j.get("features", [])
    mag = feats[0]["properties"]["mag"] if feats else None
    place = feats[0]["properties"]["place"] if feats else None
    check("usgs", True, f"{len(feats)} events; newest M{mag} {place}")
except Exception as e:
    check("usgs", False, f"{type(e).__name__}: {e}")

# 9. Kern EH closed food facilities
try:
    r = S.get("https://phweb.kerncounty.com/EH_Framed_Webpages/EH_Enforcement_ClosedFoodFacility.aspx")
    n_rows = r.text.count("<tr")
    check("kern_eh", n_rows > 0, f"{n_rows} table rows, {len(r.text)} bytes")
except Exception as e:
    check("kern_eh", False, f"{type(e).__name__}: {e}")

# 10. Overpass ALPR
try:
    q = '[out:json];node["man_made"="surveillance"]["surveillance:type"="ALPR"](35.20,-119.25,35.55,-118.80);out;'
    r = S.post("https://overpass-api.de/api/interpreter", data={"data": q})
    els = r.json().get("elements", [])
    manu = {}
    for e in els[:500]:
        m = (e.get("tags") or {}).get("manufacturer", "unknown")
        manu[m] = manu.get(m, 0) + 1
    check("overpass", len(els) > 0, f"{len(els)} ALPR nodes; manufacturers: {dict(list(manu.items())[:4])}")
except Exception as e:
    check("overpass", False, f"{type(e).__name__}: {e}")

fails = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(fails)}/{len(results)} sources OK" + (f"; FAILED: {fails}" if fails else ""))
sys.exit(1 if fails else 0)
