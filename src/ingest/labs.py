"""Páginas oficiales de novedades de los laboratorios frontera.

Si el laboratorio publica RSS se usa; si no, se extraen de la página los enlaces a artículos
y su fecha. Para cada artículo nuevo se descarga el texto principal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin

from dateutil import parser as dateparser
from selectolax.lexbor import LexborHTMLParser as HTMLParser, LexborNode as Node

from ..common import http_client, log, short_hash
from ..models import RawItem
from .article import article_text
from .rss import fetch_feed

def _find_date(node: Node) -> datetime | None:
    """Busca un <time> dentro del enlace o en sus ancestros cercanos."""
    cur: Node | None = node
    for _ in range(4):
        if cur is None:
            break
        t = cur.css_first("time")
        if t is not None:
            raw = t.attributes.get("datetime") or t.text(strip=True)
            try:
                d = dateparser.parse(raw)
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except (ValueError, OverflowError):
                return None
        cur = cur.parent
    return None


def _title(a: Node) -> str:
    h = a.css_first("h1, h2, h3, h4, [class*=title]")
    text = (h.text(strip=True) if h else a.text(separator=" ", strip=True))
    return " ".join(text.split())


def fetch_html(name: str, url: str, link_prefix: str, since: datetime, until: datetime) -> list[RawItem]:
    items = []
    seen = set()
    with http_client() as client:
        r = client.get(url)
        r.raise_for_status()
        tree = HTMLParser(r.text)
        for a in tree.css("a[href]"):
            href = a.attributes.get("href") or ""
            full = urljoin(url, href)
            path = href if href.startswith("/") else full.replace(urljoin(url, "/"), "/")
            if not path.startswith(link_prefix) or path.rstrip("/") == link_prefix.rstrip("/") or full in seen:
                continue
            published = _find_date(a)
            if not published or not (since.date() <= published.date() <= until.date()):
                continue
            seen.add(full)
            # Las páginas solo dan el día: el texto completo se trae del propio artículo.
            items.append(RawItem(
                id=f"lab:{short_hash(full)}",
                kind="lab",
                source_name=name,
                title=_title(a),
                url=full,
                published=published,
                text=article_text(client, full),
                official=True,
            ))
    return items


def sources(cfg: dict):
    for lab in cfg.get("labs", []):
        if not lab.get("enabled", True):
            continue
        if lab["kind"] == "rss":
            fn = (lambda since, until, l=lab:
                  fetch_feed(l["name"], l["url"], since, until, kind="lab", official=True))
        else:
            fn = (lambda since, until, l=lab:
                  fetch_html(l["name"], l["url"], l["link_prefix"], since, until))
        yield lab["name"], fn
