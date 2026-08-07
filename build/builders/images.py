"""Shared credited-image helpers.

Reads data/images.json (committed; built from Wikimedia Commons — see
scripts/fetch_images.py) and emits clean <figure> blocks with a small credit
line. Images are committed to assets/img/ so builds never hit the network.

  figure(slug, rel)   -> full-width figure (page/article lead images)
  thumb(slug, rel)    -> compact thumbnail (card grids)

Both return "" (empty string) if the slug is missing, so a missing image
never breaks a build.
"""
from __future__ import annotations

import json

from .. import common

_manifest: dict | None = None


def _load() -> dict:
    global _manifest
    if _manifest is None:
        try:
            _manifest = json.loads((common.DATA / "images.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _manifest = {}
    return _manifest


def _info(slug: str) -> dict | None:
    info = _load().get(slug)
    if not info:
        return None
    return info


def _caption(info: dict) -> str:
    """Small credit line: photographer + license + source page link."""
    credit = (info.get("credit") or "").strip()
    lic = (info.get("license") or "").strip()
    src = (info.get("source") or "").strip()
    parts = []
    if credit:
        parts.append(f"Photo: {credit}")
    if lic:
        parts.append(lic)
    body = " &middot; ".join(parts)
    if src:
        url = "https://commons.wikimedia.org/wiki/" + src.replace(" ", "_")
        body += f' &middot; <a href="{url}" rel="noopener">Wikimedia Commons</a>'
    return f"<figcaption>{body}</figcaption>" if body else ""


def figure(slug: str, rel: str = "") -> str:
    """A full-width, rounded figure with a small credit line."""
    info = _info(slug)
    if not info:
        return ""
    alt = (info.get("alt") or "").replace('"', "&quot;")
    w, h = info.get("width", ""), info.get("height", "")
    dims = f' width="{w}" height="{h}"' if w and h else ""
    return (
        f'<figure class="fig">'
        f'<img src="{rel}assets/img/{slug}.jpg" alt="{alt}" loading="lazy"{dims}>'
        f'{_caption(info)}'
        f"</figure>"
    )


def thumb(slug: str, rel: str = "") -> str:
    """A compact card thumbnail (16:9-ish, top-aligned) with sr-only credit."""
    info = _info(slug)
    if not info:
        return ""
    alt = (info.get("alt") or "").replace('"', "&quot;")
    w, h = info.get("width", ""), info.get("height", "")
    dims = f' width="{w}" height="{h}"' if w and h else ""
    return (
        f'<img class="thumb" src="{rel}assets/img/{slug}.jpg" alt="{alt}" loading="lazy"{dims}>'
    )
