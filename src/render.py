"""Render de la edición semanal y del índice de ediciones (HTML autocontenidos, sin dependencias externas)."""
from __future__ import annotations

from datetime import date as Date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .common import OUTPUT, TEMPLATES
from .export import export_assets, export_icons
from .history import list_days, load_day
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

def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    env.filters.update(source_link=source_link, source_names=source_names, mmss=mmss, heat=heat,
                       heat_level=heat_level, short_date=short_date, categories_of=categories_of,
                       search_text=search_text)
    env.globals["en"] = en  # en(s, "headline"): versión en inglés con el español como respaldo
    return env

def render_day(date: str, stories: list[Story], failed_sources: list[str], stats: dict,
               site: dict | None = None) -> str:
    """Edición semanal (la semana como pantalla principal y la vista día a día) en un solo HTML,
    más su imagen de vista previa y el carrusel PDF para LinkedIn."""
    site = site or {}
    site_url = (site.get("url") or "").rstrip("/") + "/" if site.get("url") else ""
    ranked = sorted(stories, key=lambda s: s.score, reverse=True)
    types = [(t, TYPE_LABELS[t], TYPE_DESCRIPTIONS[t], [s for s in ranked if s.type == t]) for t in TYPE_ORDER]
    days = week_days(date, stories)
    with_news = [d for d in days if d["stories"]]

    editions = list_days()
    older = [d for d in editions if d < date]
    newer = sorted(d for d in editions if d > date)

    ctx = dict(
        date=date,
        week_label=week_label(date),
        week_label_en=week_label_en(date),
        days=days,
        default_day=(with_news[-1] if with_news else days[-1])["iso"],
        types=types,
        ranked=ranked,
        n_stories=len(stories),
        total_minutes=sum(s.reading_minutes for s in stories),
        failed_sources=failed_sources,
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
        page_url=f"{site_url}{date}.html" if site_url else "",
    )
    env = _env()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / f"{date}.html"
    html = env.get_template("week.html").render(**ctx)
    path.write_text(html, encoding="utf-8")
    if not newer:  # la portada del sitio es siempre la edición más reciente
        (OUTPUT / "index.html").write_text(html, encoding="utf-8")
    export_assets(date, env.get_template("og.html").render(**ctx), env.get_template("carousel.html").render(**ctx))
    export_icons(env.from_string('{% from "partials/logo.html" import logo_mark %}{{ logo_mark(512, "logo") }}').render())
    render_index(site_url)
    return str(path)

def render_index(site_url: str = "") -> str:
    """output/ediciones.html: todas las ediciones semanales, con sus días y búsqueda en todo el histórico."""

    editions = []
    for date in list_days():  # de la más reciente a la más antigua
        stories, _, _ = load_day(date)
        days = week_days(date, stories)
        editions.append({"date": date, "label": week_label(date), "label_en": week_label_en(date),
                         "stories": sorted(stories, key=lambda s: s.score, reverse=True),
                         "days": days})
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
