"""Feeds RSS/Atom: medios (fuente secundaria) y blogs oficiales de laboratorios."""
from __future__ import annotations

from datetime import datetime, timezone

import feedparser
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..common import http_client, log, short_hash
from ..models import RawItem


def html_to_text(html: str) -> str:
    if not html:
        return ""
    tree = HTMLParser(html)
    return " ".join(tree.text(separator=" ").split())


def _entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def fetch_feed(name: str, url: str, since: datetime, until: datetime, *,
               kind: str = "rss", official: bool = False) -> list[RawItem]:
    with http_client() as client:
        r = client.get(url)
        r.raise_for_status()
    feed = feedparser.parse(r.content)
    items = []
    for e in feed.entries:
        published = _entry_date(e)
        if not published or not (since <= published <= until):
            continue
        body = ""
        if e.get("content"):
            body = e.content[0].get("value", "")
        body = html_to_text(body or e.get("summary", ""))
        link = e.get("link", url)
        items.append(RawItem(
            id=f"{kind}:{short_hash(link)}",
            kind=kind,  # type: ignore[arg-type]
            source_name=name,
            title=html_to_text(e.get("title", "")),
            url=link,
            published=published,
            text=body,
            official=official,
        ))
    return items


def sources(cfg: dict):
    """Una tarea por feed, para que el fallo de uno no afecte a los demás."""
    for src in cfg.get("rss", []):
        if src.get("enabled", True):
            yield src["name"], (lambda since, until, s=src: fetch_feed(s["name"], s["url"], since, until))
