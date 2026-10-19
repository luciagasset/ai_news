"""Persistencia del histórico: history/YYYY-MM-DD.json (las noticias que surgieron ese día) y history/links.json.

Cada mañana se añade el día anterior; la edición es la ventana de los 7 últimos días del histórico.
El esquema ya incluye `embedding` y `related` para la detección de relaciones de la Fase 2;
en la Fase 1 `related` queda vacío y links.json se crea vacío.
"""
from __future__ import annotations

import json
from datetime import date as Date, timedelta

from .common import HISTORY
from .models import SourceRef, Story

SCHEMA_VERSION = 2  # 2: un fichero por día de noticias (la 1 era un fichero por edición semanal)


def save_day(date: str, stories: list[Story], failed_sources: list[str], stats: dict) -> None:
    HISTORY.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "date": date,
        "stats": stats,
        "failed_sources": failed_sources,
        "stories": [s.to_dict() for s in stories],
    }
    (HISTORY / f"{date}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    links = HISTORY / "links.json"
    if not links.exists():
        # Fase 2: [{from_id, to_id, relation, similarity, confirmed_by_llm, reviewed}]
        links.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "links": []}, indent=1), encoding="utf-8")


def load_day(date: str) -> tuple[list[Story], list[str], dict]:
    path = HISTORY / f"{date}.json"
    if not path.exists():
        return [], [], {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    stories = []
    for s in doc["stories"]:
        s = dict(s)
        s["sources"] = [SourceRef(**r) for r in s["sources"]]
        stories.append(Story(**s))
    return stories, doc.get("failed_sources", []), doc.get("stats", {})


def window_days(end: str, days: int = 7) -> list[str]:
    """Los `days` días que terminan en `end` (incluido), del más antiguo al más reciente."""
    last = Date.fromisoformat(end)
    return [(last - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def load_window(end: str, days: int = 7) -> list[Story]:
    """Las noticias de los `days` días que terminan en `end`: el contenido de una edición."""
    return [s for d in window_days(end, days) for s in load_day(d)[0]]


def list_days() -> list[str]:
    return sorted((p.stem for p in HISTORY.glob("????-??-??.json")), reverse=True)
