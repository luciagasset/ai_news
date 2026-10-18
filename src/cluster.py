"""Grupos de fuentes que cuentan la misma noticia.

La agrupación la hace Claude Code al escribir candidatos.json. Aquí se define el grupo y una
comprobación automática: si dos candidatos se parecen mucho (embeddings), se avisa de un posible
duplicado para revisarlo antes de resumir.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .embeddings import embed
from .models import Mention

DUPLICATE_SIM = 0.80


@dataclass
class Cluster:
    mentions: list[Mention]
    points: float = 0.0     # señal de debate asignada a esta noticia (ver score.allocate_signals)
    comments: float = 0.0

    @property
    def items(self):
        seen, out = set(), []
        for m in self.mentions:
            if m.item.id not in seen:
                seen.add(m.item.id)
                out.append(m.item)
        return out

    @property
    def headline(self) -> str:
        return self.mentions[0].headline

    @property
    def entities(self) -> list[str]:
        c = Counter(e for m in self.mentions for e in m.entities)
        return [e for e, _ in c.most_common(8)]

    @property
    def type(self) -> str:
        return Counter(m.type_guess for m in self.mentions).most_common(1)[0][0]

    @property
    def category(self) -> str:
        return Counter(m.category_guess for m in self.mentions).most_common(1)[0][0]


def possible_duplicates(keyed: list[tuple[str, Cluster]]) -> list[tuple[str, str, float]]:
    """Pares de candidatos con titulares casi iguales: (key_a, key_b, similitud)."""
    if len(keyed) < 2:
        return []
    vectors = embed([f"{c.headline}. {' '.join(c.entities)}" for _, c in keyed])
    sims = vectors @ vectors.T
    pairs = []
    for i in range(len(keyed)):
        for j in range(i + 1, len(keyed)):
            if sims[i, j] >= DUPLICATE_SIM:
                pairs.append((keyed[i][0], keyed[j][0], round(float(sims[i, j]), 2)))
    return pairs
