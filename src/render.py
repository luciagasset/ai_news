"""Render de la edición (los 7 últimos días), del índice de ediciones y de la página de cada noticia
(HTML autocontenidos, sin dependencias externas).

La portada (index.html) se actualiza cada mañana. Cada 7 días, contando desde la primera edición archivada,
la edición queda guardada en output/<fecha>.html: así el índice no repite días entre una semana y la siguiente.
"""
from __future__ import annotations

from datetime import date as Date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .common import OUTPUT, TEMPLATES, log
from .export import CAROUSEL_DIR, OG_DIR, export_assets, export_icons, export_images, export_pwa
from .history import list_days, load_day, load_window
from .models import (CATEGORY_LABELS, CATEGORY_LABELS_EN, TYPE_LABELS, TYPE_LABELS_EN, TYPE_ORDER,
                     TYPE_SINGULAR, TYPE_SINGULAR_EN, SourceRef, Story)

DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]

TYPE_DESCRIPTIONS = {
    "avance": "Lanzamientos, versiones y benchmarks",
    "debate": "Discusiones técnicas y de opinión",
    "polemica": "Controversias y críticas",
    "noticia": "Empresas, inversión y regulación",
}

TYPE_DESCRIPTIONS_EN = {
    "avance": "Launches, versions and benchmarks",
    "debate": "Technical and opinion debates",
    "polemica": "Controversies and criticism",
    "noticia": "Companies, investment and regulation",
}
DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]


def week_label_en(end_iso: str, days: int = 7) -> str:
    """«October 9–15, 2026» (o «September 28 – October 4, 2026»)."""
    end = Date.fromisoformat(end_iso)
    start = end - timedelta(days=days - 1)
    if start.month == end.month:
        return f"{MONTHS_EN[end.month - 1]} {start.day}–{end.day}, {end.year}"
    if start.year == end.year:
        return f"{MONTHS_EN[start.month - 1]} {start.day} – {MONTHS_EN[end.month - 1]} {end.day}, {end.year}"
    return f"{MONTHS_EN[start.month - 1]} {start.day}, {start.year} – {MONTHS_EN[end.month - 1]} {end.day}, {end.year}"


def en(s: Story, field: str):
    """Campo de la noticia en inglés, o el español si aún no hay traducción."""
    value = (s.en or {}).get(field)
    return value if value else getattr(s, field)


def week_label(end_iso: str, days: int = 7) -> str:
    """«Del 9 al 16 de octubre de 2026» (o «Del 28 de septiembre al 4 de octubre de 2026»)."""
    end = Date.fromisoformat(end_iso)
    start = end - timedelta(days=days - 1)
    if start.month == end.month:
        return f"Del {start.day} al {end.day} de {MONTHS[end.month - 1]} de {end.year}"
    if start.year == end.year:
        return f"Del {start.day} de {MONTHS[start.month - 1]} al {end.day} de {MONTHS[end.month - 1]} de {end.year}"
    return (f"Del {start.day} de {MONTHS[start.month - 1]} de {start.year} "
            f"al {end.day} de {MONTHS[end.month - 1]} de {end.year}")

def week_days(end_iso: str, stories: list[Story], days: int = 7) -> list[dict]:
    """Los días de la semana con sus noticias, agrupadas por tipo (vista diaria y «El pulso de la semana»)."""
    end = Date.fromisoformat(end_iso)
    out = []
    for i in range(days - 1, -1, -1):
        d = end - timedelta(days=i)
        iso = d.isoformat()
        items = sorted((s for s in stories if s.first_seen == iso), key=lambda s: s.score, reverse=True)
        out.append({
            "iso": iso,
            "weekday": DAYS[d.weekday()][:3],
            "initial": "LMXJVSD"[d.weekday()],
            "day": d.day,
            "label": long_date(iso).rsplit(" de ", 1)[0],  # «Martes, 13 de octubre»
            "label_en": f"{DAYS_EN[d.weekday()]}, {MONTHS_EN[d.month - 1]} {d.day}",
            "weekday_en": DAYS_EN[d.weekday()][:3],
            "initial_en": "MTWTFSS"[d.weekday()],
            "stories": items,
            "sections": [(t, TYPE_LABELS[t], [s for s in items if s.type == t]) for t in TYPE_ORDER],
        })
    return out

def search_text(s: Story) -> str:
    return " ".join([s.headline, s.summary_short, en(s, "headline"), en(s, "summary_short"),
                     " ".join(s.entities), CATEGORY_LABELS[s.category], CATEGORY_LABELS_EN[s.category]]).lower()

def categories_of(stories: list[Story]) -> list[tuple[str, str]]:
    return [(k, v) for k, v in CATEGORY_LABELS.items() if any(s.category == k for s in stories)]

def long_date(iso: str) -> str:
    d = Date.fromisoformat(iso)
    return f"{DAYS[d.weekday()].capitalize()}, {d.day} de {MONTHS[d.month - 1]} de {d.year}"

def short_date(iso: str) -> str:
    d = Date.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1][:3]}"

def source_link(ref: SourceRef) -> str:
    """Enlace al vídeo en el minuto exacto cuando se conoce."""
    if ref.kind != "youtube" or not ref.timestamp:
        return ref.url
    u = urlparse(ref.url)
    q = dict(parse_qsl(u.query))
    q["t"] = f"{int(ref.timestamp)}s"
    return urlunparse(u._replace(query=urlencode(q)))

def mmss(seconds: float | None) -> str:
    s = int(seconds or 0)
    h, rem = divmod(s, 3600)
    m, se = divmod(rem, 60)
    return f"{h}:{m:02d}:{se:02d}" if h else f"{m}:{se:02d}"

def source_names(refs: list[SourceRef]) -> list[str]:
    """Nombres cortos y únicos para la tarjeta: el canal sin el título del vídeo, 'Hacker News' sin cifras."""
    out: list[str] = []
    for r in refs:
        name = r.name.split(" — ")[0].split(" · ")[0]
        if name not in out:
            out.append(name)
    return out

HEAT_STEPS = (20, 80, 200, 500, 1000)

def heat_level(comments: int) -> int:
    """0-5 barras del medidor de intensidad del debate."""
    return sum(comments >= step for step in HEAT_STEPS)

def heat(comments: int) -> str:
    if comments >= 300:
        return "Muy debatido"
    if comments >= 80:
        return "Debatido"
    return ""

def first_sentence(text: str) -> str:
    """La frase de contexto del texto que se comparte: la primera del resumen breve."""
    head, sep, _ = text.partition(". ")
    return head + "." if sep else text


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    env.filters.update(source_link=source_link, source_names=source_names, mmss=mmss, heat=heat,
                       heat_level=heat_level, short_date=short_date, categories_of=categories_of,
                       search_text=search_text, first_sentence=first_sentence)
    env.globals["en"] = en  # en(s, "headline"): versión en inglés con el español como respaldo
    return env

def archives() -> list[str]:
    """Ediciones archivadas: output/AAAA-MM-DD.html, de la más antigua a la más reciente."""
    return sorted(p.stem for p in OUTPUT.glob("????-??-??.html"))


def is_archive(date: str) -> bool:
    """Se archiva una edición cada 7 días, contando desde la primera archivada."""
    arch = archives()
    if not arch or date in arch:
        return True
    return (Date.fromisoformat(date) - Date.fromisoformat(arch[0])).days % 7 == 0


def archive_of(day: str) -> str | None:
    """La edición archivada que contiene ese día, si ya existe."""
    return next((a for a in archives() if 0 <= (Date.fromisoformat(a) - Date.fromisoformat(day)).days < 7), None)


def _site_url(site: dict | None) -> str:
    url = (site or {}).get("url") or ""
    return url.rstrip("/") + "/" if url else ""


def render_edition(date: str, n_days: int = 7, failed_sources: list[str] = (), site: dict | None = None) -> str:
    """La edición de los `n_days` días que terminan en `date` (la semana como pantalla principal y la vista
    día a día) en un solo HTML, más su imagen de vista previa, el carrusel PDF para LinkedIn y las páginas e
    imágenes para compartir cada noticia."""
    site = site or {}
    site_url = _site_url(site)
    stories = load_window(date, n_days)
    stats = {"items": sum(load_day(d)[2].get("items", 0) for d in {s.first_seen for s in stories})}
    ranked = sorted(stories, key=lambda s: s.score, reverse=True)
    types = [(t, TYPE_LABELS[t], TYPE_DESCRIPTIONS[t], [s for s in ranked if s.type == t]) for t in TYPE_ORDER]
    days = week_days(date, stories, n_days)
    with_news = [d for d in days if d["stories"]]

    archive = is_archive(date)
    latest = not any(d > date for d in list_days())
    arch = archives()
    older = [d for d in arch if d < date]
    newer = [d for d in arch if d > date]

    ctx = dict(
        date=date,
        week_label=week_label(date, n_days),
        week_label_en=week_label_en(date, n_days),
        days=days,
        default_day=(with_news[-1] if with_news else days[-1])["iso"],
        types=types,
        ranked=ranked,
        n_stories=len(stories),
        total_minutes=sum(s.reading_minutes for s in stories),
        failed_sources=list(failed_sources),
        stats=stats,
        type_singular=TYPE_SINGULAR,
        type_singular_en=TYPE_SINGULAR_EN,
        type_labels=TYPE_LABELS,
        type_labels_en=TYPE_LABELS_EN,
        type_desc_en=TYPE_DESCRIPTIONS_EN,
        category_labels=CATEGORY_LABELS,
        category_labels_en=CATEGORY_LABELS_EN,
        prev_day=older[-1] if older else None,
        next_day=newer[0] if newer else None,
        generated=datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        site_url=site_url,
        author=site.get("author", ""),
        og_image=f"{site_url}og/{date}.png" if site_url else "",
        page_url=(f"{site_url}{date}.html" if archive else site_url) if site_url else "",
    )
    env = _env()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    html = env.get_template("week.html").render(**ctx)
    path = OUTPUT / "index.html"
    if archive:
        path = OUTPUT / f"{date}.html"
        path.write_text(html, encoding="utf-8")
    if latest:  # la portada del sitio es siempre la edición más reciente
        (OUTPUT / "index.html").write_text(html, encoding="utf-8")
    export_assets(date, env.get_template("og.html").render(**ctx), env.get_template("carousel.html").render(**ctx))
    _prune_assets(keep=set(archives()) | {date})
    export_icons(env.from_string('{% from "partials/logo.html" import logo_mark %}{{ logo_mark(512, "logo") }}').render())
    render_stories(site_url, {s.id for s in stories} if latest else set())
    render_index(site_url)
    export_pwa(datetime.now().strftime("%Y%m%d%H%M%S"))
    return str(path)


def _prune_assets(keep: set[str]) -> None:
    """La portada cambia cada día: se borran la vista previa y el carrusel de los días que no quedan archivados."""
    for folder, ext in ((OG_DIR, "png"), (CAROUSEL_DIR, "pdf")):
        for p in folder.glob(f"????-??-??.{ext}"):
            if p.stem not in keep:
                p.unlink()


STORIES_DIR = OUTPUT / "noticias"
INSTAGRAM_DIR = OUTPUT / "instagram"
STORY_OG_DIR = OG_DIR / "noticias"


def _card_sizes(s: Story) -> list[tuple[Path, int, int, dict]]:
    """Las dos imágenes de una noticia, con la letra ajustada a la longitud del titular."""
    n = len(s.headline)
    return [
        # Instagram: cuadrada, con el titular grande y el resumen breve
        (INSTAGRAM_DIR, 1080, 1080, dict(pad=64, base=26, title=76 if n <= 70 else 66 if n <= 95 else 58,
                                         lines=5, lead_lines=4)),
        # Vista previa al pegar el enlace (WhatsApp, LinkedIn, Telegram): apaisada, solo el titular
        (STORY_OG_DIR, 1200, 630, dict(pad=44, base=22, title=58 if n <= 70 else 50 if n <= 95 else 44,
                                       lines=3, lead_lines=0)),
    ]


def render_stories(site_url: str = "", current: set[str] = frozenset()) -> int:
    """output/noticias/<id>.html para todas las noticias del histórico, con sus metaetiquetas Open Graph, y sus
    imágenes (og/noticias/<id>.png e instagram/<id>.png) si aún no existen. Devuelve las imágenes nuevas.

    `current`: las noticias de la portada; su página enlaza a la portada y las demás, a su edición archivada."""
    env = _env()
    page, card = env.get_template("story.html"), env.get_template("card.html")
    host = (urlparse(site_url).netloc + urlparse(site_url).path).rstrip("/")
    STORIES_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    for day in list_days():
        for s in load_day(day)[0]:
            arch = archive_of(s.first_seen)
            link = f"../#n={s.id}" if s.id in current or not arch else f"../{arch}.html#n={s.id}"
            d = Date.fromisoformat(s.first_seen)
            html = page.render(
                s=s, type_singular=TYPE_SINGULAR, type_singular_en=TYPE_SINGULAR_EN,
                category_labels=CATEGORY_LABELS, category_labels_en=CATEGORY_LABELS_EN,
                long_date=long_date(s.first_seen),
                long_date_en=f"{DAYS_EN[d.weekday()]}, {MONTHS_EN[d.month - 1]} {d.day}, {d.year}",
                edition_link=link,
                og_image=f"{site_url}og/noticias/{s.id}.png" if site_url else "",
                page_url=f"{site_url}noticias/{s.id}.html" if site_url else "",
            )
            (STORIES_DIR / f"{s.id}.html").write_text(html, encoding="utf-8")
            for folder, w, h, sizes in _card_sizes(s):
                dest = folder / f"{s.id}.png"
                if not dest.exists():
                    jobs.append((card.render(s=s, w=w, h=h, site_host=host, type_singular=TYPE_SINGULAR, **sizes),
                                 w, h, dest))
    made = export_images(jobs)
    if made:
        log.info("Imágenes para compartir: %d nuevas", made)
    return made

def render_index(site_url: str = "") -> str:
    """output/ediciones.html: todas las ediciones semanales, con sus días y búsqueda en todo el histórico."""

    editions = []
    saved = list_days()
    arch = archives()
    dates = arch[::-1]  # de la más reciente a la más antigua
    if saved and (not arch or saved[0] > arch[-1]):
        dates.insert(0, saved[0])  # la portada, mientras no quede archivada
    for date in dates:
        stories = load_window(date)
        editions.append({"date": date, "href": f"{date}.html" if date in arch else "./",
                         "label": week_label(date), "label_en": week_label_en(date),
                         "stories": sorted(stories, key=lambda s: s.score, reverse=True),
                         "days": week_days(date, stories)})
    html = _env().get_template("index.html").render(
        editions=editions, type_singular=TYPE_SINGULAR, category_labels=CATEGORY_LABELS,
        type_singular_en=TYPE_SINGULAR_EN, category_labels_en=CATEGORY_LABELS_EN,
        site_url=site_url, og_image=f"{site_url}og/{editions[0]['date']}.png" if site_url and editions else "",
        generated=datetime.now().strftime("%d/%m/%Y a las %H:%M"),
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "ediciones.html"
    path.write_text(html, encoding="utf-8")
    return str(path)
