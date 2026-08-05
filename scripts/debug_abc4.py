#!/usr/bin/env python3
"""Follow ABC redirect properly and inspect the report table."""
import re, datetime, requests

S = requests.Session()
S.headers.update({"User-Agent": "BakersfieldDailyBriefBot/1.0 (local news site; editor@bakersfieldbrief.com)"})
r = S.get("https://www.abc.ca.gov/licensing/licensing-reports/new-applications/")
nonce = re.search(r'name=["\']abclqs_daily_report["\'][^>]*value=["\']([^"\']+)["\']', r.text).group(1)

def tables_of(html):
    out = []
    for t in re.findall(r"<table.*?</table>", html, re.S):
        head = re.search(r"<thead.*?</thead>", t, re.S)
        thead = re.sub(r"<[^>]+>", " | ", head.group(0)) if head else "?"
        thead = re.sub(r"\s+", " ", thead).strip(" |")
        rows = len(re.findall(r"<tr", t))
        out.append((thead, rows))
    return out

print("=== GET (no params) ===")
for thead, rows in tables_of(r.text):
    print(f"  [{rows} rows] {thead[:110]}")

d = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%m/%d/%Y")
r2 = S.post("https://www.abc.ca.gov/wp-admin/admin-post.php",
            data={"action": "abclqs_daily_report", "url": "/licensing/licensing-reports/new-applications/",
                  "rpttype": "2", "abclqs_daily_report": nonce,
                  "_wp_http_referer": "/licensing/licensing-reports/new-applications/",
                  "abclqs-date": d},
            allow_redirects=False)
loc = "https://www.abc.ca.gov" + r2.headers["Location"]
r3 = S.get(loc)
print(f"\n=== GET {loc} ===")
for thead, rows in tables_of(r3.text):
    print(f"  [{rows} rows] {thead[:110]}")
print("BAKERSFIELD x", r3.text.count("BAKERSFIELD"))
print("len:", len(r3.text), "(plain GET:", len(r.text), ")")

# try a couple of rpttype values / dates quickly
for rpt in ["1", "2", "3"]:
    for days in [1, 3, 5]:
        dd = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%m/%d/%Y")
        rr = S.get(f"https://www.abc.ca.gov/licensing/licensing-reports/new-applications/?RPTTYPE={rpt}&RPTDATE={dd}")
        b = rr.text.count("BAKERSFIELD")
        print(f"RPTTYPE={rpt} RPTDATE={dd}: len={len(rr.text)} BAKERSFIELD x{b}")
