"""Punto de entrada de la edición semanal. La Fase 1 no usa APIs de pago: la clasificación y los
resúmenes los escribe Claude Code entre los pasos, siguiendo docs/instrucciones-claude-code.md.

    python run_weekly.py ingest [--date AAAA-MM-DD] [--reuse-raw]
        Descarga las fuentes de los 7 días previos y escribe data/raw/<fecha>/para_claude.md.
        -> Claude Code escribe data/raw/<fecha>/candidatos.json

    python run_weekly.py select [--date ...]
        Puntúa los candidatos (sección 2.1), elige los de la semana y escribe para_resumir.md.
        -> Claude Code escribe data/raw/<fecha>/resumenes.json

    python run_weekly.py render [--date ...]
        Guarda history/<fecha>.json y genera output/<fecha>.html.

<fecha> es el último día de la semana (la fecha de cierre). Sin --date se usa ayer, de modo que la
edición cubre los 7 días naturales previos a hoy.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date as Date, datetime, time, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from src.classify import load_candidates, write_brief
from src.cluster import Cluster, possible_duplicates
from src.common import LOGS, RAW, ROOT, load_config, log
from src.embeddings import embed
from src.history import save_day
from src.ingest import hackernews, labs, rss, youtube
from src.ingest.article import enrich
from src.models import RawItem, SourceRef, Story
from src.render import render_day
from src.score import allocate_signals, comments, is_confirmed, select
from src.summarize import Summary, load_selection, load_summaries, write_requests
from src.transcripts import add_transcripts

MADRID = ZoneInfo("Europe/Madrid")


def setup_logging(day: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(LOGS / f"{day}.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def window(day: str, days: int = 7) -> tuple[datetime, datetime]:
    """Los `days` días naturales que terminan en `day` (incluido), en hora de Madrid.

    Si `day` es hoy, la ventana acaba ahora mismo."""
    end_day = Date.fromisoformat(day)
    since = datetime.combine(end_day - timedelta(days=days - 1), time(0, 0), tzinfo=MADRID)
    until = datetime.combine(end_day + timedelta(days=1), time(0, 0), tzinfo=MADRID)
    return since, min(until, datetime.now(MADRID))


def ingest(cfg: dict, since: datetime, until: datetime) -> tuple[list[RawItem], list[str]]:
    tasks = []
    if cfg.get("youtube", {}).get("channels"):
        tasks.append(("YouTube", lambda s, u: youtube.fetch(cfg, s, u)))
    if cfg.get("hackernews", {}).get("enabled", True):
        tasks.append(("Hacker News", lambda s, u: hackernews.fetch(cfg, s, u)))
    tasks += list(rss.sources(cfg)) + list(labs.sources(cfg))

    items, failed = [], []

    def run(task):
        name, fn = task
        try:
            got = fn(since, until)
            log.info("Fuente %-22s %3d elementos", name, len(got))
            return got
        except Exception as e:
            log.error("Fuente %s caída: %s: %s", name, type(e).__name__, e)
            failed.append(name)
            return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        for got in pool.map(run, tasks):
            items.extend(got)
    return items, sorted(failed)


def save_raw(day: str, items: list[RawItem], failed: list[str]) -> None:
    folder = RAW / day
    folder.mkdir(parents=True, exist_ok=True)
    doc = {"failed_sources": failed, "items": [i.to_dict() for i in items]}
    (folder / "items.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def load_raw(day: str) -> tuple[list[RawItem], list[str]]:
    doc = json.loads((RAW / day / "items.json").read_text(encoding="utf-8"))
    return [RawItem.from_dict(d) for d in doc["items"]], doc["failed_sources"]


def build_sources(c: Cluster) -> list[SourceRef]:
    refs: list[SourceRef] = []
    timestamps = {}
    for m in c.mentions:
        timestamps.setdefault(m.item.id, m.timestamp)
    # Oficiales primero, luego vídeos y artículos, HN al final.
    order = {"lab": 0, "rss": 1, "youtube": 2, "hackernews": 3}
    for it in sorted(c.items, key=lambda i: order[i.kind]):
        if it.kind == "hackernews":
            if it.url != it.discussion_url:
                domain = urlparse(it.url).netloc.removeprefix("www.")
                refs.append(SourceRef(name=f"{domain} — {it.title}", url=it.url, kind="rss"))
            refs.append(SourceRef(name=f"Hacker News · {it.points} puntos, {it.comments} comentarios",
                                  url=it.discussion_url, kind="hackernews"))
        else:
            refs.append(SourceRef(name=f"{it.source_name} — {it.title}",
                                  url=it.url, kind=it.kind, official=it.official,
                                  timestamp=timestamps.get(it.id), partial=it.partial))
    return refs


def build_story(day: str, n: int, c: Cluster, score: float, s: Summary) -> Story:
    confirmed = is_confirmed(c)
    words = len((s.summary_short + " " + s.summary_long).split())
    return Story(
        id=f"{day}-{n:02d}",
        date=day,
        type=s.type,
        category=s.category,
        headline=s.headline,
        summary_short=s.summary_short,
        summary_long=s.summary_long,
        sources=build_sources(c),
        entities=c.entities,
        score=score,
        comments=comments(c),
        official=any(it.official for it in c.items),
        # Regla del plan: una polémica solo se da por confirmada con dos fuentes independientes o una oficial.
        unconfirmed=(s.type == "polemica" and not confirmed),
        partial=all(it.kind == "youtube" and it.partial for it in c.items),
        reading_minutes=max(1, round(words / 200)),
        unconfirmed_claims=s.unverified_claims,
        en=({"headline": s.en.headline, "summary_short": s.en.summary_short, "summary_long": s.en.summary_long,
             "unconfirmed_claims": s.en.unverified_claims} if s.en else {}),
        first_seen=min(it.published for it in c.items).astimezone(MADRID).date().isoformat(),
    )


def cmd_ingest(day: str, cfg: dict, reuse: bool) -> int:
    since, until = window(day, cfg.get("selection", {}).get("window_days", 7))
    log.info("Edición %s · ventana %s → %s", day, since.strftime("%d/%m %H:%M"), until.strftime("%d/%m %H:%M"))
    if reuse and (RAW / day / "items.json").exists():
        items, failed = load_raw(day)
        log.info("Ingesta reutilizada: %d elementos", len(items))
    else:
        items, failed = ingest(cfg, since, until)
        enrich([i for i in items if i.kind != "youtube"])
        add_transcripts(items)
        save_raw(day, items, failed)
    log.info("Ingesta: %d elementos, fuentes caídas: %s", len(items), ", ".join(failed) or "ninguna")
    if not items:
        log.error("No hay elementos para este día.")
        return 1
    path = write_brief(day, items, cfg.get("frontier_labs", []))
    log.info("Siguiente paso (Claude Code): leer %s y escribir candidatos.json", path)
    return 0


def cmd_select(day: str, cfg: dict) -> int:
    items, _ = load_raw(day)
    keyed = load_candidates(day, items)
    for a, b, sim in possible_duplicates(keyed):
        log.warning("Posible duplicado: %s y %s (similitud %.2f). Revisa candidatos.json.", a, b, sim)
    key_of = {id(c): k for k, c in keyed}
    _, until = window(day, cfg.get("selection", {}).get("window_days", 7))
    chosen = [(key_of[id(c)], c, sc, is_confirmed(c)) for c, sc in select([c for _, c in keyed], cfg, until)]
    path = write_requests(day, chosen)
    log.info("Siguiente paso (Claude Code): leer %s y escribir resumenes.json", path)
    return 0


def cmd_render(day: str, cfg: dict) -> int:
    items, failed = load_raw(day)
    clusters = dict(load_candidates(day, items))
    allocate_signals(list(clusters.values()))
    summaries = load_summaries(day)
    stories: list[Story] = []
    for entry in load_selection(day):
        key = entry["key"]
        if key not in summaries:
            log.warning("Sin resumen para %s: se omite", key)
            continue
        stories.append(build_story(day, len(stories) + 1, clusters[key], entry["score"], summaries[key]))
    vectors = embed([f"{st.headline}. {st.summary_short}" for st in stories])
    for st, v in zip(stories, vectors):
        st.embedding = [round(float(x), 5) for x in v]
    stats = {"items": len(items), "candidates": len(clusters), "selected": len(stories),
             "summarizer": "claude-code"}
    save_day(day, stories, failed, stats)
    path = render_day(day, stories, failed, stats, cfg.get("site"))
    log.info("Página generada: %s (%d noticias)", path, len(stories))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera la edición semanal de noticias de IA.")
    ap.add_argument("step", choices=["ingest", "select", "render"])
    ap.add_argument("--date", default=(datetime.now(MADRID).date() - timedelta(days=1)).isoformat(),
                    help="AAAA-MM-DD: último día de la semana (por defecto, ayer)")
    ap.add_argument("--reuse-raw", action="store_true", help="ingest: reutiliza data/raw/<fecha>/items.json")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    setup_logging(args.date)
    cfg = load_config()
    if args.step == "ingest":
        return cmd_ingest(args.date, cfg, args.reuse_raw)
    if args.step == "select":
        return cmd_select(args.date, cfg)
    return cmd_render(args.date, cfg)


if __name__ == "__main__":
    sys.exit(main())
