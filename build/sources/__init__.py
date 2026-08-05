"""Data-source registry. Each source is an isolated module with a run(ctx)
that returns {"ok": bool, ...} and NEVER raises. build_all.py wraps each in
its own try/except so one broken source can't stop the site.
"""
from . import (escribe, kern_board, abc, news_rss, weather, chp, isabella, food,
               alpr, gnews, airnow, calfire, venues, blocked)

# name -> module. Order matters only for the build report.
SOURCES = {
    "escribe": escribe,        # City meetings + agendas (eSCRIBE JSON API)
    "kern_board": kern_board,  # Kern County Board of Supervisors agenda PDF
    "abc": abc,                # CA ABC liquor license applications
    "news_rss": news_rss,      # KGET + 23ABC local RSS (metro digest)
    "gnews": gnews,            # Google News RSS per place (hyperlocal)
    "weather": weather,        # NWS alerts + Bakersfield forecast/KBFL observation
    "airnow": airnow,          # EPA AirNow AQI (zip 93301; needs AIRNOW_API_KEY)
    "calfire": calfire,        # CAL FIRE active incidents (wildfires)
    "chp": chp,                # CHP incidents (LAHB → BFCC)
    "isabella": isabella,      # Isabella Lake storage (CDEC)
    "food": food,              # Kern EH closed food facilities
    "alpr": alpr,              # ALPR cameras (Overpass/OSM)
    "venues": venues,          # Weekend Guide venue whitelist (--guide only)
    # Blocked sources (datacenter IPs / not yet built) — leave stubs:
    "blocked": blocked,
}
