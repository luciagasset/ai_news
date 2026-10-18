"""Descarga del texto principal de un artículo (para feeds sin cuerpo y enlaces de Hacker News)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..common import http_client, log
from ..models import RawItem

MAX_TEXT_CHARS = 20000
MIN_USEFUL_CHARS = 400
SKIP_DOMAINS = ("twitter.com", "x.com", "youtube.com", "youtu.be", "news.ycombinator.com")


def article_text(client, url: str) -> str:
    r = client.get(url)
    r.raise_for_status()
    if "html" not in r.headers.get("content-type", "html"):
        return ""
    tree = HTMLParser(r.text)
    for sel in ("script", "style", "nav", "header", "footer", "aside", "form", "noscript"):
        for n in tree.css(sel):
            n.decompose()
    main = tree.css_first("article") or tree.css_first("main") or tree.body
    text = " ".join(main.text(separator=" ").split()) if main else ""
    return text[:MAX_TEXT_CHARS]


def enrich(items: list[RawItem], workers: int = 8) -> None:
    """Completa item.text con el artículo enlazado cuando el feed o HN no traen cuerpo suficiente."""
    todo = [it for it in items
            if len(it.text) < MIN_USEFUL_CHARS and not any(d in it.url for d in SKIP_DOMAINS)]

    def one(it: RawItem) -> bool:
        try:
            with http_client() as client:
                body = article_text(client, it.url)
        except Exception as e:
            log.info("Sin texto para %s (%s): %s", it.id, it.url, type(e).__name__)
            return False
        if len(body) > len(it.text):
            it.text = f"{it.text}\n\n{body}" if it.text else body
            return True
        return False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        ok = sum(pool.map(one, todo))
    log.info("Artículos descargados: %d/%d", ok, len(todo))
