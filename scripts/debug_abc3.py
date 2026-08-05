#!/usr/bin/env python3
"""Check ABC POST redirect behavior + table provenance."""
import re, datetime, requests

S = requests.Session()
S.headers.update({"User-Agent": "BakersfieldDailyBriefBot/1.0 (local news site; editor@bakersfieldbrief.com)"})
r = S.get("https://www.abc.ca.gov/licensing/licensing-reports/new-applications/")
nonce = re.search(r'name=["\']abclqs_daily_report["\'][^>]*value=["\']([^"\']+)["\']', r.text).group(1)

# 1. does the GET page itself contain the 18-row table? (i.e. is the table static page content)
print("GET table present:", "<table" in r.text, "| BAKERSFIELD:", r.text.count("BAKERSFIELD"))
tbl = re.search(r"<table.*?</table>", r.text, re.S)
if tbl:
    head = re.search(r"<thead.*?</thead>", tbl.group(0), re.S)
    print("GET thead:", re.sub(r"\s+", " ", head.group(0))[:300] if head else "none")

# 2. POST with redirects disabled
d = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%m/%d/%Y")
r2 = S.post("https://www.abc.ca.gov/wp-admin/admin-post.php",
            data={"action": "abclqs_daily_report", "url": "/licensing/licensing-reports/new-applications/",
                  "rpttype": "2", "abclqs_daily_report": nonce,
                  "_wp_http_referer": "/licensing/licensing-reports/new-applications/",
                  "abclqs-date": d},
            allow_redirects=False)
print("\nPOST status:", r2.status_code, "| Location:", r2.headers.get("Location"))
print("POST body head:", r2.text[:200].replace("\n", " "))

# 3. follow manually to the redirect target and compare
if r2.status_code in (301, 302, 303, 307, 308) and r2.headers.get("Location"):
    loc = r2.headers["Location"]
    r3 = S.get(loc)
    print("\nRedirect target:", loc)
    print("target len:", len(r3.text), "| BAKERSFIELD:", r3.text.count("BAKERSFIELD"), "| tables:", r3.text.count("<table"))
    # find the table with date columns
    for t in re.findall(r"<table.*?</table>", r3.text, re.S):
        if "Date" in t or "CITY" in t.upper():
            head = re.search(r"<thead.*?</thead>", t, re.S)
            print("thead:", re.sub(r"\s+", " ", head.group(0))[:250] if head else "?")
            break
