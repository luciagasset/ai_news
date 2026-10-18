"""Persistencia del histórico: history/YYYY-MM-DD.json y history/links.json.

El esquema ya incluye `embedding` y `related` para la detección de relaciones de la Fase 2;
en la Fase 1 `related` queda vacío y links.json se crea vacío.
"""
from __future__ import annotations

import json

from .common import HISTORY
from .models import SourceRef, Story

SCHEMA_VERSION = 1


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
    doc = json.loads((HISTORY / f"{date}.json").read_text(encoding="utf-8"))
    stories = []
    for s in doc["stories"]:
        s = dict(s)
        s["sources"] = [SourceRef(**r) for r in s["sources"]]
        stories.append(Story(**s))
    return stories, doc.get("failed_sources", []), doc.get("stats", {})


def list_days() -> list[str]:
    return sorted((p.stem for p in HISTORY.glob("????-??-??.json")), reverse=True)
