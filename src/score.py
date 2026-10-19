"""Puntuación de relevancia (sección 2.1 del plan) y selección de las noticias del día."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

from .cluster import Cluster
from .common import log

TYPE_WEIGHT = {"avance": 1.3, "polemica": 1.25, "debate": 1.15, "noticia": 1.0}
MIN_SHARE_FOR_RESERVED = 0.35  # un tipo solo se garantiza si su mejor noticia llega al 35 % de la mejor del día


def source_key(it) -> str:
    """Fuente independiente: el medio enlazado para Hacker News, el canal o medio para el resto."""
    if it.kind == "hackernews":
        host = urlparse(it.url).netloc.removeprefix("www.")
        return {"twitter.com": "x.com"}.get(host, host)
    return it.source_name


def source_names(c: Cluster) -> set[str]:
    return {source_key(it) for it in c.items}


def allocate_signals(clusters: list[Cluster]) -> None:
    """Reparte puntos y comentarios de cada fuente entre las noticias que la citan.

    Los comentarios de un vídeo van al tema principal (el que antes aparece en el vídeo), no a
    todo lo que menciona de pasada; el resto de fuentes compartidas se reparte a partes iguales.
    """
    citing: dict[str, list[tuple[Cluster, float]]] = defaultdict(list)
    for c in clusters:
        c.points = c.comments = 0.0
        for m in {m.item.id: m for m in c.mentions}.values():
            citing[m.item.id].append((c, m.timestamp if m.timestamp is not None else 0.0))
    by_id = {it.id: it for c in clusters for it in c.items}
    for item_id, owners in citing.items():
        it = by_id[item_id]
        if it.kind == "youtube":
            main = min(owners, key=lambda o: o[1])[0]
            main.comments += it.comments
        else:
            for c, _ in owners:
                c.points += it.points / len(owners)
                c.comments += it.comments / len(owners)


def comments(c: Cluster) -> int:
    return round(c.comments)


def is_confirmed(c: Cluster) -> bool:
    """Dos fuentes independientes o una oficial."""
    return any(it.official for it in c.items) or len(source_names(c)) >= 2


def score(c: Cluster, now: datetime, priority_topics: list[str]) -> float:
    items = c.items
    n_sources = len(source_names(c))
    discussion = c.points + 2 * c.comments
    intensity = math.log1p(discussion)

    age_h = min((now - it.published).total_seconds() / 3600 for it in items)
    # Lo de los últimos días pesa algo más, sin hundir lo del principio de la ventana.
    freshness = 1.0 if age_h <= 48 else 0.9 if age_h <= 96 else 0.8

    s = (1.5 * n_sources + intensity) * TYPE_WEIGHT.get(c.type, 1.0) * freshness

    haystack = (c.headline + " " + " ".join(c.entities)).lower()
    if any(t.lower() in haystack for t in priority_topics):
        s += 1.0
    if c.type == "avance" and any(it.official for it in items):
        s += 1.5
    return round(s, 3)


MADRID = ZoneInfo("Europe/Madrid")


def day_of(c: Cluster) -> str:
    """Día (hora de Madrid) en que surgió la noticia: el de su primera fuente."""
    return min(it.published for it in c.items).astimezone(MADRID).date().isoformat()


def select(clusters: list[Cluster], cfg: dict, now: datetime) -> list[tuple[Cluster, float]]:
    """Las noticias del día (2-3; unas 15 en la semana): por puntuación, con mínimos por tipo y por día,
    topes para que nada acapare y un suelo (`min_share` de la mejor) para no rellenar los días flojos."""
    sel_cfg = cfg.get("selection", {})
    max_items = sel_cfg.get("max_items", 12)
    min_per_type = sel_cfg.get("min_per_type", 1)
    max_per_type = sel_cfg.get("max_per_type", max_items)
    min_per_day = sel_cfg.get("min_per_day", 1)
    max_per_day = sel_cfg.get("max_per_day", max_items)
    min_share = sel_cfg.get("min_share", 0.0)
    topics = cfg.get("priority_topics", [])

    allocate_signals(clusters)
    scored = sorted(((c, score(c, now, topics)) for c in clusters), key=lambda x: x[1], reverse=True)
    if not scored:
        return []
    top = scored[0][1]
    worthy = [x for x in scored if x[1] >= MIN_SHARE_FOR_RESERVED * top]  # nunca se reserva relleno

    chosen: list[tuple[Cluster, float]] = []
    per_type: dict[str, int] = {}
    per_day: dict[str, int] = {}

    def take(x) -> bool:
        c = x[0]
        if any(c is y for y, _ in chosen) or len(chosen) >= max_items:
            return False
        if per_type.get(c.type, 0) >= max_per_type or per_day.get(day_of(c), 0) >= max_per_day:
            return False
        chosen.append(x)
        per_type[c.type] = per_type.get(c.type, 0) + 1
        per_day[day_of(c)] = per_day.get(day_of(c), 0) + 1
        return True

    # 1. Representación mínima por tipo, si hay material con peso real.
    for t in TYPE_WEIGHT:
        for x in [x for x in worthy if x[0].type == t][:min_per_type]:
            take(x)
    # 2. Repartida entre los días: cada día con material de peso tiene al menos una noticia.
    for d in sorted({day_of(c) for c, _ in worthy}):
        have = per_day.get(d, 0)
        for x in [x for x in worthy if day_of(x[0]) == d]:
            if have >= min_per_day:
                break
            have += take(x)
    # 3. El resto, por puntuación, sin bajar del suelo.
    for x in scored:
        if x[1] >= min_share * top:
            take(x)

    chosen.sort(key=lambda x: x[1], reverse=True)
    log.info("Selección: %d de %d noticias (puntuación %.1f–%.1f) · por día: %s",
             len(chosen), len(clusters), chosen[0][1], chosen[-1][1],
             ", ".join(f"{d[8:]}:{n}" for d, n in sorted(per_day.items())))
    return chosen
