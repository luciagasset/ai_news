"""Utilidades compartidas: rutas, configuración, cliente HTTP y logging."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.yaml"
DATA = ROOT / "data"
RAW = DATA / "raw"
CACHE = DATA / "cache"
HISTORY = ROOT / "history"
OUTPUT = ROOT / "output"
LOGS = ROOT / "logs"
TEMPLATES = ROOT / "templates"

USER_AGENT = "Mozilla/5.0 (compatible; AI News/1.0; +https://github.com/)"

log = logging.getLogger("ai_news")


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def http_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
    )


def short_hash(text: str, n: int = 12) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]
