"""Probe the City of Bakersfield AgendaCenter for its data endpoint."""
import re
import urllib.request

req = urllib.request.Request("https://www.bakersfieldcity.us/AgendaCenter",
                             headers={"User-Agent": "Mozilla/5.0"})
h = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
print("len:", len(h))

for pat in ["GetMeetings", "Search", "GetItems", "/api/", "loadMeetings",
            "dataUrl", "fetch(", "WebService"]:
    hits = re.findall(r'["\']([^"\']*%s[^"\']*)["\']' % re.escape(pat), h)[:4]
    if hits:
        print(pat, "->", hits)

print("scripts:", re.findall(r'src="([^"]+\.js[^"]*)"', h)[:6])
