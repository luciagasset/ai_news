"""Piezas para compartir cada edición: imagen de vista previa (Open Graph) y carrusel PDF para LinkedIn.

Las dos se maquetan con plantillas HTML y se convierten con Chrome en modo headless, que ya está
instalado en el ordenador (y en los runners de GitHub Actions). Si no se encuentra Chrome, la edición
se genera igualmente, sin estas piezas.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .common import DATA, OUTPUT, log

OG_DIR = OUTPUT / "og"
ICON_DIR = OUTPUT / "icons"
CAROUSEL_DIR = OUTPUT / "carrusel"
TMP = DATA / "tmp"

CHROME_CANDIDATES = [
    os.environ.get("CHROME_PATH", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
    shutil.which("chromium-browser") or "",
]


def find_chrome() -> str | None:
    return next((c for c in CHROME_CANDIDATES if c and Path(c).exists()), None)


def _run(chrome: str, args: list[str], html: Path) -> None:
    cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
           "--run-all-compositor-stages-before-draw", "--virtual-time-budget=3000", *args, html.as_uri()]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)


def export_assets(date: str, og_html: str, carousel_html: str) -> dict[str, str]:
    """Escribe output/og/<fecha>.png y output/carrusel/<fecha>.pdf. Devuelve las rutas generadas."""
    chrome = find_chrome()
    if not chrome:
        log.warning("No encuentro Chrome: se omiten la imagen de vista previa y el carrusel")
        return {}
    TMP.mkdir(parents=True, exist_ok=True)
    OG_DIR.mkdir(parents=True, exist_ok=True)
    CAROUSEL_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}

    og_src = TMP / f"og-{date}.html"
    og_src.write_text(og_html, encoding="utf-8")
    og_png = OG_DIR / f"{date}.png"
    try:
        _run(chrome, ["--window-size=1200,630", f"--screenshot={og_png}"], og_src)
        out["og"] = str(og_png)
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("No se pudo generar la imagen de vista previa: %s", e)

    car_src = TMP / f"carrusel-{date}.html"
    car_src.write_text(carousel_html, encoding="utf-8")
    car_pdf = CAROUSEL_DIR / f"{date}.pdf"
    try:
        _run(chrome, [f"--print-to-pdf={car_pdf}", "--no-pdf-header-footer", "--print-to-pdf-no-header"], car_src)
        out["carousel"] = str(car_pdf)
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("No se pudo generar el carrusel: %s", e)

    if out:
        log.info("Para compartir: %s", ", ".join(out.values()))
    return out


def export_icons(svg: str) -> None:
    """Logo como archivo: logo.svg (pestaña del navegador) e icon-180/512.png (iPhone, redes)."""
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    (ICON_DIR / "logo.svg").write_text(svg, encoding="utf-8")
    chrome = find_chrome()
    if not chrome:
        return
    TMP.mkdir(parents=True, exist_ok=True)
    for size in (180, 512):
        page = TMP / f"icon-{size}.html"
        page.write_text(
            "<!doctype html><html><body style='margin:0;background:transparent'>"
            + svg.replace('width="512" height="512"', f'width="{size}" height="{size}"') + "</body></html>",
            encoding="utf-8")
        try:
            _run(chrome, [f"--window-size={size},{size}", "--default-background-color=00000000",
                          f"--screenshot={ICON_DIR / f'icon-{size}.png'}"], page)
        except (subprocess.SubprocessError, OSError) as e:
            log.warning("No se pudo generar el icono de %d px: %s", size, e)
