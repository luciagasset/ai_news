"""Estructuras de datos compartidas por todo el pipeline.

RawItem   -> lo que devuelve cada fuente (un vídeo, un artículo, una historia de HN).
Mention   -> un tema concreto dentro de un RawItem (un vídeo suele comentar varias noticias).
Story     -> un grupo de menciones sobre la misma noticia; es lo que se publica y se guarda en history/.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Literal

SourceKind = Literal["youtube", "rss", "lab", "hackernews"]
StoryType = Literal["avance", "debate", "polemica", "noticia"]
Category = Literal["modelos", "empresas", "investigacion", "regulacion", "herramientas"]

TYPE_ORDER: list[StoryType] = ["avance", "debate", "polemica", "noticia"]
TYPE_LABELS = {
    "avance": "Modelos frontera",
    "debate": "En debate",
    "polemica": "Polémicas",
    "noticia": "Noticias",
}
TYPE_SINGULAR = {"avance": "Avance", "debate": "Debate", "polemica": "Polémica", "noticia": "Noticia"}
CATEGORY_LABELS = {
    "modelos": "Modelos",
    "empresas": "Empresas",
    "investigacion": "Investigación",
    "regulacion": "Regulación",
    "herramientas": "Herramientas",
}


@dataclass
class RawItem:
    id: str                      # único y estable, p. ej. "yt:VIDEO_ID", "hn:123", "rss:<hash>"
    kind: SourceKind
    source_name: str             # canal, medio o laboratorio
    title: str
    url: str
    published: datetime
    text: str = ""               # descripción, cuerpo del artículo o transcripción
    official: bool = False       # viene de la propia empresa
    comments: int = 0            # comentarios (YouTube, HN)
    points: int = 0              # puntos (HN)
    partial: bool = False        # vídeo sin transcripción
    discussion_url: str = ""     # hilo de HN si aplica
    # Transcripción con marcas de tiempo [(segundo, texto)] para citar el minuto
    segments: list[tuple[float, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RawItem":
        d = dict(d)
        d["published"] = datetime.fromisoformat(d["published"])
        d["segments"] = [tuple(s) for s in d.get("segments", [])]
        return cls(**d)


@dataclass
class Mention:
    item: RawItem
    headline: str                # titular provisional (en español)
    summary: str                 # 2-3 frases de lo que dice esta fuente
    entities: list[str]
    type_guess: StoryType
    category_guess: Category
    timestamp: float | None = None   # segundo del vídeo donde se trata
    embedding: list[float] | None = None


@dataclass
class SourceRef:
    name: str
    url: str
    kind: SourceKind
    official: bool = False
    timestamp: float | None = None   # segundo del vídeo
    partial: bool = False


@dataclass
class Story:
    id: str                      # "YYYY-MM-DD-NN"
    date: str
    type: StoryType
    category: Category
    headline: str
    summary_short: str           # nivel 1
    summary_long: str            # nivel 2 (párrafos separados por \n\n)
    sources: list[SourceRef]
    entities: list[str]
    score: float
    comments: int
    official: bool
    unconfirmed: bool
    partial: bool
    reading_minutes: int
    unconfirmed_claims: list[str] = field(default_factory=list)
    first_seen: str = ""        # fecha (AAAA-MM-DD) de la primera fuente: sitúa la noticia en la semana
    embedding: list[float] = field(default_factory=list)
    # Fase 2: [{story_id, date, headline, relation: seguimiento|relacionada|contradiccion}]
    related: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
