#!/usr/bin/env python3
"""Probe ABC daily report POST across recent dates."""
import re, datetime, requests

S = requests.Session()
S.headers.update({"User-Agent": "BakersfieldDailyBriefBot/1.0 (local news site; editor@bakersfieldbrief.com)"})
r = S.get("https://www.abc.ca.gov/licensing/licensing-reports/new-applications/")
m = re.search(r'name=["\']abclqs_daily_report["\'][^>]*value=["\']([^"\']+)["\']', r.text)
nonce = m.group(1)
print("nonce:", nonce)

for days_ago in [0, 1, 2, 3, 4, 5, 6]:
    d = (datetime.date.today() - datetime.timedelta(days=days_ago)).strftime("%m/%d/%Y")
    r2 = S.post("https://www.abc.ca.gov/wp-admin/admin-post.php",
                data={"action": "abclqs_daily_report", "url": "/licensing/licensing-reports/new-applications/",
                      "rpttype": "2", "abclqs_daily_report": nonce,
                      "_wp_http_referer": "/licensing/licensing-reports/new-applications/",
                      "abclqs-date": d})
    # look for the results table region: find <table ...> ... </table> and count rows/cities
    tables = re.findall(r"<table.*?</table>", r2.text, re.S)
    city_hits = r2.text.count("BAKERSFIELD")
    n_rows = 0
    sample = ""
    if tables:
        biggest = max(tables, key=len)
        n_rows = len(re.findall(r"<tr", biggest))
        # find a city cell pattern
        cells = re.findall(r">([A-Z][A-Z ]{3,})<", biggest)
        sample = ", ".join(dict.fromkeys(cells))[:80]
    print(f"date {d}: resp {len(r2.text)}B, tables={len(tables)}, rows_in_biggest={n_rows}, BAKERSFIELD x{city_hits}, cities: {sample}")
