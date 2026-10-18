"""Resumen en dos niveles, en modo ficheros (Fase 1: lo escribe Claude Code, sin API de pago).

- `write_requests` deja en data/raw/<fecha>/para_resumir.md, por cada noticia seleccionada, el
  fragmento relevante de cada fuente: el artículo o, en los vídeos, la ventana de transcripción
  alrededor del minuto en que se trata el tema. Y en seleccion.json, el orden y la puntuación.
- Claude Code escribe resumenes.json siguiendo docs/instrucciones-claude-code.md (paso 2).
- `load_summaries` lo valida.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .cluster import Cluster
from .common import RAW, log
from .models import Mention

REQUESTS_FILE = "para_resumir.md"
SELECTION_FILE = "seleccion.json"
SUMMARIES_FILE = "resumenes.json"

WINDOW_BEFORE_S = 30
WINDOW_AFTER_S = 300


class Summary(BaseModel):
    headline: str
    summary_short: str
    summary_long: str
    type: Literal["avance", "debate", "polemica", "noticia"]
    category: Literal["modelos", "empresas", "investigacion", "regulacion", "herramientas"]
    unverified_claims: list[str] = []


class Summaries(BaseModel):
    summaries: dict[str, Summary]


def mmss(seconds: float | None) -> str:
    s = int(seconds or 0)
    h, rem = divmod(s, 3600)
    mi, se = divmod(rem, 60)
    return f"{h}:{mi:02d}:{se:02d}" if h else f"{mi:02d}:{se:02d}"


def _excerpt(m: Mention) -> str:
    item = m.item
    if item.kind == "youtube" and item.segments:
        if m.timestamp is None:
            text = " ".join(t for _, t in item.segments)
            return f"Transcripción completa (sin minuto indicado):\n{text}"
        start, end = m.timestamp - WINDOW_BEFORE_S, m.timestamp + WINDOW_AFTER_S
        text = " ".join(t for s, t in item.segments if start <= s <= end)
        return f"Fragmento de la transcripción ({mmss(max(start, 0))}–{mmss(end)}):\n{text}"
    if item.kind == "youtube":
        return f"(Vídeo sin transcripción: resumen parcial.) Descripción:\n{item.text}"
    if item.text:
        return f"Texto:\n{item.text}"
    return "(Solo titular: no hay texto de la fuente.)"


def _request(key: str, c: Cluster, score: float, confirmed: bool) -> str:
    parts = [f"## {key} · {c.headline}",
             f"Propuesta: type={c.type}, category={c.category} · puntuación {score} · "
             f"{'confirmada' if confirmed else 'NO confirmada (una sola fuente no oficial)'}", ""]
    unique: dict[str, Mention] = {}
    for m in c.mentions:
        unique.setdefault(m.item.id, m)
    for n, m in enumerate(unique.values(), 1):
        it = m.item
        tag = " [FUENTE OFICIAL]" if it.official else ""
        extra = f" · {it.points} puntos, {it.comments} comentarios" if it.kind == "hackernews" else ""
        parts.append(f"### Fuente {n}: {it.source_name}{tag} (`{it.id}`{extra})\nTítulo: {it.title}\n{_excerpt(m)}\n")
    return "\n".join(parts)


def write_requests(day: str, chosen: list[tuple[str, Cluster, float, bool]]) -> Path:
    folder = RAW / day
    header = (f"# Noticias seleccionadas del {day}\n\n"
              f"Sigue `docs/instrucciones-claude-code.md` (paso 2) y escribe `{SUMMARIES_FILE}` en esta carpeta, "
              f"con una entrada por cada clave ({', '.join(k for k, *_ in chosen)}).\n\n---\n\n")
    body = "\n---\n\n".join(_request(k, c, s, conf) for k, c, s, conf in chosen)
    path = folder / REQUESTS_FILE
    path.write_text(header + body, encoding="utf-8")
    (folder / SELECTION_FILE).write_text(
        json.dumps([{"key": k, "score": s} for k, _, s, _ in chosen], indent=1), encoding="utf-8")
    return path


def load_selection(day: str) -> list[dict]:
    path = RAW / day / SELECTION_FILE
    if not path.exists():
        raise FileNotFoundError(f"Falta {path}: ejecuta antes `run_weekly.py select`")
    return json.loads(path.read_text(encoding="utf-8"))


def load_summaries(day: str) -> dict[str, Summary]:
    path = RAW / day / SUMMARIES_FILE
    if not path.exists():
        raise FileNotFoundError(f"Falta {path}: Claude Code debe escribirlo a partir de {REQUESTS_FILE}")
    data = Summaries.model_validate(json.loads(path.read_text(encoding="utf-8")))
    log.info("Resúmenes: %d", len(data.summaries))
    return data.summaries
