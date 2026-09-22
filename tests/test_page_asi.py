"""Guard: a string literal that ends a line inside a <script> block, with another literal on the next
line and no operator between them, is valid JavaScript after automatic semicolon insertion. It silently
turns the rest of the expression into an unused statement.

That exact shape shipped once: every owner record on the ALPR explorer rendered its heading and then
stopped, because the note string lost its trailing + and the camera list, the company record and the
minimap were parsed as a statement of their own. node --check passes such a file, so this test exists.
"""
import re
import pathlib

SITE = pathlib.Path(__file__).resolve().parents[1] / "site"
ENDS_LITERAL = re.compile(r"(?<![+\-*/=(,:\[])\s*'(?:\s*)$")
STARTS_LITERAL = re.compile(r"^\s*'")


def script_blocks(html):
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)


def hazards(js):
    out = []
    lines = js.split("\n")
    for i in range(len(lines) - 1):
        if ENDS_LITERAL.search(lines[i]) and STARTS_LITERAL.match(lines[i + 1]):
            out.append((i + 1, lines[i].strip()[-70:], lines[i + 1].strip()[:70]))
    return out


def test_no_string_literal_asi_hazard():
    pages = sorted(SITE.rglob("*.html"))
    if not pages:
        return  # nothing built in this checkout
    bad = []
    for p in pages:
        try:
            html = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for block in script_blocks(html):
            for line, a, b in hazards(block):
                bad.append(f"{p.name}:{line} ... {a!r} / {b!r}")
    assert not bad, "string literal split by a newline inside a script block:\n" + "\n".join(bad[:10])