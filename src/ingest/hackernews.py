"""Historias de Hacker News sobre IA de la ventana de la edición (API pública de Algolia)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..common import http_client, log
from ..models import RawItem
from .article import article_text
from .rss import html_to_text

API = "https://hn.algolia.com/api/v1/search"


def _keyword_pattern(keywords: list[str]) -> re.Pattern:
    """Palabras completas (o su plural en -s); un * final admite cualquier terminación."""
    parts = []
    for k in keywords:
        k = k.strip().lower()
        if k.endswith("*"):
            parts.append(re.escape(k[:-1]))
        else:
            parts.append(re.escape(k) + r"s?(?!\w)")  # admite plural: LLMs, agents
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + ")", re.IGNORECASE)


def _is_ai(title: str, pattern: re.Pattern) -> bool:
    return bool(pattern.search(title))


ITEM_API = "https://hn.algolia.com/api/v1/items/{}"
MIN_DENSITY = 10      # menciones de IA por cada 1.000 palabras
MIN_HITS = 8
MIN_ARTICLE_WORDS = 200


def _thread_text(client, story_id: str, max_comments: int = 40) -> str:
    """Comentarios de primer nivel del hilo: sirven cuando la web enlazada no deja leer su texto."""
    r = client.get(ITEM_API.format(story_id))
    r.raise_for_status()
    children = r.json().get("children", [])[:max_comments]
    return " ".join(html_to_text(c.get("text") or "") for c in children)


def _about_ai(text: str, pattern: re.Pattern) -> bool:
    words = len(text.split())
    hits = len(pattern.findall(text))
    return hits >= MIN_HITS and 1000 * hits / max(words, 1) >= MIN_DENSITY


def _check_by_text(client, h: dict, pattern: re.Pattern) -> str | None:
    """Texto que demuestra que la historia es de IA (artículo o, si no se puede leer, el hilo), o None."""
    try:
        text = article_text(client, h["url"])
    except Exception:
        text = ""
    if len(text.split()) < MIN_ARTICLE_WORDS:
        try:
            thread = _thread_text(client, h["objectID"])
        except Exception:
            return None
        if _about_ai(thread, pattern):
            return f"(Comentarios del hilo de Hacker News) {thread}"
        return None
    return text if _about_ai(text, pattern) else None


def fetch(cfg: dict, since: datetime, until: datetime) -> list[RawItem]:
    hcfg = cfg["hackernews"]
    hits: list[dict] = []
    with http_client() as client:
        # Una semana tiene cientos de historias: se pagina hasta agotar la ventana.
        for page in range(10):
            r = client.get(API, params={
                "tags": "story",
                "numericFilters": f"created_at_i>{int(since.timestamp())},created_at_i<{int(until.timestamp())},"
                                  f"points>={hcfg.get('min_points', 50)}",
                "hitsPerPage": 200, "page": page,
            })
            r.raise_for_status()
            data = r.json()
            hits.extend(data.get("hits", []))
            if page + 1 >= data.get("nbPages", 0):
                break

        pattern = _keyword_pattern(hcfg["keywords"])
        check_min = hcfg.get("check_text_min_points", 150)
        selected, by_text, texts = [], 0, {}
        for h in hits:
            title = h.get("title") or ""
            if _is_ai(title, pattern):
                selected.append(h)
            elif (h.get("points") or 0) >= check_min and h.get("url"):
                text = _check_by_text(client, h, pattern)
                if text:
                    selected.append(h)
                    texts[h["objectID"]] = text
                    by_text += 1

    selected.sort(key=lambda h: h.get("points") or 0, reverse=True)
    selected = selected[: hcfg.get("max_items", 80)]
    items = []
    for h in selected:
        hn_url = f"https://news.ycombinator.com/item?id={h['objectID']}"
        items.append(RawItem(
            id=f"hn:{h['objectID']}",
            kind="hackernews",
            source_name="Hacker News",
            title=h.get("title") or "",
            url=h.get("url") or hn_url,
            published=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
            text=html_to_text(h.get("story_text") or "") or texts.get(h["objectID"], ""),
            points=int(h.get("points") or 0),
            comments=int(h.get("num_comments") or 0),
            discussion_url=hn_url,
        ))
    log.info("Hacker News: %d historias de IA (%d detectadas por el texto del artículo) de %d", len(items), by_text, len(hits))
    return items
