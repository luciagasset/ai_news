"""Transcripciones de los vídeos (subtítulos manuales o automáticos), con caché en disco.

La YouTube Data API no da subtítulos de canales ajenos, así que se usa youtube-transcript-api.
Si no hay transcripción, el vídeo se resume con título + descripción y se marca como parcial.
"""
from __future__ import annotations

import json

from youtube_transcript_api import YouTubeTranscriptApi

from .common import CACHE, log
from .models import RawItem

CACHE_DIR = CACHE / "transcripts"
PREFERRED_LANGS = ["es", "es-ES", "en", "en-US", "en-GB"]


def _fetch(api: YouTubeTranscriptApi, video_id: str) -> list[tuple[float, str]]:
    try:
        fetched = api.fetch(video_id, languages=PREFERRED_LANGS)
    except Exception:
        # Ningún idioma preferido: vale cualquier transcripción disponible.
        transcript = next(iter(api.list(video_id)))
        fetched = transcript.fetch()
    return [(round(s.start, 1), s.text.replace("\n", " ")) for s in fetched]


def add_transcripts(items: list[RawItem]) -> None:
    """Rellena item.segments y item.text (in situ) para los vídeos de YouTube."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    api = YouTubeTranscriptApi()
    ok = 0
    for item in items:
        if item.kind != "youtube":
            continue
        video_id = item.id.removeprefix("yt:")
        path = CACHE_DIR / f"{video_id}.json"
        if path.exists():
            segments = [tuple(s) for s in json.loads(path.read_text(encoding="utf-8"))]
        else:
            try:
                segments = _fetch(api, video_id)
                path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
            except Exception as e:  # bloqueos de IP, subtítulos desactivados, etc.
                log.warning("Sin transcripción para %s (%s): %s", video_id, item.source_name, type(e).__name__)
                segments = []
        if segments:
            item.segments = segments
            ok += 1
        else:
            item.partial = True
    total = sum(1 for i in items if i.kind == "youtube")
    log.info("Transcripciones: %d/%d vídeos", ok, total)


def timestamped_text(item: RawItem, every: float = 30.0) -> str:
    """Transcripción con marcas [mm:ss] cada ~30 s, para que el LLM pueda citar el minuto."""
    if not item.segments:
        return item.text
    out, next_mark = [], 0.0
    for start, text in item.segments:
        if start >= next_mark:
            m, s = divmod(int(start), 60)
            out.append(f"\n[{m:02d}:{s:02d}] ")
            next_mark = start + every
        out.append(text + " ")
    return "".join(out).strip()
