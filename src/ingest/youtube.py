"""Vídeos recientes de los canales configurados, vía YouTube Data API v3.

Coste de cuota por canal: channels.list (1, solo la primera vez) + playlistItems.list (1)
+ videos.list (1 por cada 50 vídeos). Evitamos search.list, que cuesta 100.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from ..common import DATA, http_client, log
from ..models import RawItem

API = "https://www.googleapis.com/youtube/v3"
CHANNEL_CACHE = DATA / "youtube_channels.json"
MIN_DURATION_S = 120  # descarta Shorts


def _duration_seconds(iso: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _resolve_channels(client, key: str, channels: list[dict]) -> dict[str, str]:
    """handle -> playlist de subidas. Se cachea en disco para no gastar cuota."""
    cache: dict[str, str] = {}
    if CHANNEL_CACHE.exists():
        cache = json.loads(CHANNEL_CACHE.read_text(encoding="utf-8"))
    changed = False
    for ch in channels:
        handle = ch["handle"]
        if handle in cache:
            continue
        r = client.get(f"{API}/channels", params={"part": "contentDetails", "forHandle": handle, "key": key})
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            log.warning("YouTube: no encuentro el canal %s (%s)", ch["name"], handle)
            continue
        cache[handle] = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        changed = True
    if changed:
        CHANNEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CHANNEL_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return cache


def fetch(cfg: dict, since: datetime, until: datetime) -> list[RawItem]:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("Falta YOUTUBE_API_KEY en .env")
    ycfg = cfg["youtube"]
    channels = [c for c in ycfg["channels"] if c.get("enabled", True)]
    per_channel = ycfg.get("max_videos_per_channel", 5)

    items: list[RawItem] = []
    with http_client() as client:
        uploads = _resolve_channels(client, key, channels)
        candidates: dict[str, dict] = {}  # video_id -> canal
        for ch in channels:
            playlist = uploads.get(ch["handle"])
            if not playlist:
                continue
            r = client.get(f"{API}/playlistItems", params={
                "part": "contentDetails", "playlistId": playlist,
                "maxResults": max(per_channel * 2, 10), "key": key,
            })
            r.raise_for_status()
            n = 0
            for it in r.json().get("items", []):
                published = datetime.fromisoformat(it["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00"))
                if since <= published <= until and n < per_channel:
                    candidates[it["contentDetails"]["videoId"]] = ch
                    n += 1

        ids = list(candidates)
        for i in range(0, len(ids), 50):
            r = client.get(f"{API}/videos", params={
                "part": "snippet,statistics,contentDetails", "id": ",".join(ids[i:i + 50]), "key": key,
            })
            r.raise_for_status()
            for v in r.json().get("items", []):
                if _duration_seconds(v["contentDetails"].get("duration", "")) < MIN_DURATION_S:
                    continue
                sn = v["snippet"]
                items.append(RawItem(
                    id=f"yt:{v['id']}",
                    kind="youtube",
                    source_name=candidates[v["id"]]["name"],
                    title=sn["title"],
                    url=f"https://www.youtube.com/watch?v={v['id']}",
                    published=datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")),
                    text=sn.get("description", ""),
                    comments=int(v.get("statistics", {}).get("commentCount", 0) or 0),
                ))
    log.info("YouTube: %d vídeos en la ventana", len(items))
    return items
