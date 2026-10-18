"""Clasificación sin API de pago: el script prepara las fuentes y Claude Code clasifica.

1. `write_brief` vuelca todas las fuentes del día (con transcripciones marcadas por minuto) en
   data/raw/<fecha>/para_claude.md.
2. Claude Code lo lee y escribe data/raw/<fecha>/candidatos.json: las noticias del día, ya agrupadas
   y clasificadas, siguiendo docs/instrucciones-claude-code.md.
3. `load_candidates` valida ese fichero y lo convierte en grupos que el script puntúa.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .cluster import Cluster
from .common import RAW, log
from .models import Mention, RawItem
from .transcripts import timestamped_text

BRIEF_FILE = "para_claude.md"
CANDIDATES_FILE = "candidatos.json"
BRIEF_TEXT_CHARS = 900  # en el paso 1 basta el arranque del artículo; el paso 2 recibe el texto completo

StoryTypeLit = Literal["avance", "debate", "polemica", "noticia"]
CategoryLit = Literal["modelos", "empresas", "investigacion", "regulacion", "herramientas"]


class CandidateSource(BaseModel):
    item: str = Field(description='id del elemento, p. ej. "yt:abc123" o "hn:456"')
    timestamp: str = Field(default="", description='"mm:ss" o "h:mm:ss" donde empieza el tema en el vídeo')


class Candidate(BaseModel):
    key: str
    headline: str
    type: StoryTypeLit
    category: CategoryLit
    entities: list[str]
    sources: list[CandidateSource]


class Candidates(BaseModel):
    candidates: list[Candidate]


def _describe(item: RawItem) -> str:
    kind = {"youtube": "Vídeo de YouTube", "rss": "Artículo de prensa", "lab": "Blog oficial",
            "hackernews": "Historia de Hacker News"}[item.kind]
    lines = [f"## `{item.id}` · {kind} · {item.source_name}",
             f"**Título:** {item.title}  ",
             f"**URL:** {item.url}  ",
             f"**Fecha:** {item.published:%Y-%m-%d %H:%M} UTC" + (" · FUENTE OFICIAL" if item.official else "")]
    if item.kind == "hackernews":
        lines.append(f"**Señal:** {item.points} puntos · {item.comments} comentarios · "
                     f"dominio {urlparse(item.url).netloc}")
    if item.kind == "youtube":
        lines.append(f"**Comentarios:** {item.comments}\n\n**Descripción:**\n{item.text}")
        if item.segments:
            lines.append(f"\n**Transcripción:**\n{timestamped_text(item)}")
        else:
            lines.append("\n(Sin transcripción: resumen parcial, usar solo título y descripción.)")
    elif item.text:
        text = item.text
        if len(text) > BRIEF_TEXT_CHARS:
            text = text[:BRIEF_TEXT_CHARS] + f" […] (recortado: {len(item.text)} caracteres en total)"
        lines.append(f"\n**Texto:**\n{text}")
    return "\n".join(lines)


def write_brief(day: str, items: list[RawItem], frontier_labs: list[str]) -> Path:
    folder = RAW / day
    folder.mkdir(parents=True, exist_ok=True)
    order = {"lab": 0, "rss": 1, "hackernews": 2, "youtube": 3}
    header = (
        f"# Fuentes del {day}\n\n"
        f"{len(items)} elementos. Laboratorios frontera: {', '.join(frontier_labs)}.\n"
        f"Sigue `docs/instrucciones-claude-code.md` (paso 1) y escribe `{CANDIDATES_FILE}` en esta carpeta.\n"
    )
    body = "\n\n---\n\n".join(_describe(i) for i in sorted(items, key=lambda i: (order[i.kind], i.source_name)))
    path = folder / BRIEF_FILE
    path.write_text(header + "\n---\n\n" + body + "\n", encoding="utf-8")
    return path


def parse_ts(ts: str) -> float | None:
    try:
        parts = [int(p) for p in ts.strip().split(":")]
    except ValueError:
        return None
    if not parts or len(parts) > 3:
        return None
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return float(seconds)


def load_candidates(day: str, items: list[RawItem]) -> list[tuple[str, Cluster]]:
    """Valida candidatos.json y devuelve (key, grupo). Las referencias a ids inexistentes se descartan con aviso."""
    path = RAW / day / CANDIDATES_FILE
    if not path.exists():
        raise FileNotFoundError(f"Falta {path}: Claude Code debe escribirlo a partir de {BRIEF_FILE}")
    data = Candidates.model_validate(json.loads(path.read_text(encoding="utf-8")))
    by_id = {i.id: i for i in items}
    out = []
    for c in data.candidates:
        mentions = []
        for s in c.sources:
            item = by_id.get(s.item)
            if item is None:
                log.warning("Candidato %s: el elemento %s no existe en la ingesta", c.key, s.item)
                continue
            mentions.append(Mention(
                item=item, headline=c.headline, summary="", entities=c.entities,
                type_guess=c.type, category_guess=c.category,
                timestamp=parse_ts(s.timestamp) if item.kind == "youtube" and s.timestamp else None,
            ))
        if mentions:
            out.append((c.key, Cluster(mentions)))
    log.info("Candidatos: %d noticias válidas de %d", len(out), len(data.candidates))
    return out
