#!/usr/bin/env python3
"""Dump ABC table rows to design the parser."""
import re, requests
from html.parser import HTMLParser

S = requests.Session()
S.headers.update({"User-Agent": "BakersfieldDailyBriefBot/1.0 (local news site; editor@bakersfieldbrief.com)"})
r = S.get("https://www.abc.ca.gov/licensing/licensing-reports/new-applications/")

tbl = re.search(r"<table.*?</table>", r.text, re.S).group(0)

class RowParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cells, self.cur, self.href, self.in_a = [], [], [], None, False
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr": self.cells.append([])
        elif tag == "td": self.cur = []
        elif tag == "a": self.in_a = True; self.href = a.get("href")
    def handle_endtag(self, tag):
        if tag == "td" and self.cur is not None and self.cells:
            self.cells[-1].append(("".join(self.cur)).strip())
            self.cur = None
        elif tag == "a": self.in_a = False
    def handle_data(self, d):
        if self.cur is not None: self.cur.append(d)

# only parse rows with tds
body = re.search(r"<tbody.*?</tbody>", tbl, re.S)
frag = body.group(0) if body else tbl
p = RowParser()
p.feed(frag)
print("rows parsed:", len(p.cells))
for row in p.cells[:6]:
    print([c[:45] for c in row])
# any rows with links?
for row in p.cells:
    for c in row:
        if "http" in c.lower():
            print("LINK IN ROW:", c[:80]); break
