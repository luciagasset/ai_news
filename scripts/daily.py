"""Actualización diaria automática: la lanza el Programador de tareas de Windows a las 07:07 (hora de Madrid).

Por cada día pendiente (normalmente solo ayer; si el ordenador estuvo apagado, también los días que faltan):

    ingest  →  Claude Code escribe candidatos.json  →  select  →  Claude Code escribe resumenes.json  →  render

y al final publica output/ e history/ en GitHub (el flujo de GitHub Pages despliega la web).

Claude Code se ejecuta en modo no interactivo (`claude -p`) con la sesión de Lucía, sin API de pago, y solo
puede leer y escribir ficheros: sin terminal ni web, para que los resúmenes salgan solo de las fuentes.
Si un fichero de Claude no pasa la validación, se le pide una vez más con el error. Si algo falla, no se
publica nada y queda anotado en logs/diario.log; al día siguiente se reintenta desde el día que faltó.

    .venv/Scripts/python scripts/daily.py [--no-push]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / "logs" / "diario.log"
LOCK = ROOT / "data" / "diario.lock"
CLAUDE = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # con pythonw no se abre ninguna consola

CLAUDE_TOOLS = ["--permission-mode", "acceptEdits",
                "--allowedTools", "Read,Write,Edit,Glob,Grep",
                "--disallowedTools", "Bash,PowerShell,WebFetch,WebSearch,Agent"]

PROMPTS = {
    "candidatos": (
        "Actualización diaria automática de AI News, día {day}. Sigue docs/instrucciones-claude-code.md, paso 1: "
        "lee entero data/raw/{day}/para_claude.md y escribe data/raw/{day}/candidatos.json. "
        "No hagas nada más ni preguntes: nadie va a contestar."
    ),
    "resumenes": (
        "Actualización diaria automática de AI News, día {day}. Sigue docs/instrucciones-claude-code.md, paso 2: "
        "lee entero data/raw/{day}/para_resumir.md y escribe data/raw/{day}/resumenes.json, con la traducción "
        "al inglés en `en`. Solo a partir de las fuentes. No hagas nada más ni preguntes: nadie va a contestar."
    ),
}


def say(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    if sys.stdout:  # con pythonw no hay consola
        print(line, flush=True)


def run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=NO_WINDOW,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (p.stdout + p.stderr).strip()
    if p.returncode:
        say(f"  ✗ {' '.join(cmd[:3])} (código {p.returncode})\n{out[-3000:]}")
    return p


def py(step: str, *args: str) -> subprocess.CompletedProcess:
    return run([str(PYTHON), "run_weekly.py", step, *args])


def claude_writes(kind: str, day: str, check: str) -> bool:
    """Claude escribe candidatos.json o resumenes.json; `check` es el paso del script que lo valida."""
    error = ""
    for attempt in (1, 2):
        prompt = PROMPTS[kind].format(day=day)
        if error:
            prompt += f"\n\nEl fichero anterior no pasó la validación; corrígelo. Error:\n{error[-2000:]}"
        say(f"  Claude Code escribe {kind}.json (intento {attempt})")
        try:
            run([CLAUDE, "-p", prompt, *CLAUDE_TOOLS], timeout=2400)
        except subprocess.TimeoutExpired:
            say("  ✗ Claude Code no terminó a tiempo")
            continue
        p = py(check, "--date", day)
        if p.returncode == 0:
            return True
        error = (p.stdout + p.stderr).strip()
    return False


def do_day(day: str) -> bool:
    say(f"Día {day}")
    if py("ingest", "--date", day).returncode:
        return False
    return claude_writes("candidatos", day, "select") and claude_writes("resumenes", day, "render")


def publish(days: list[str]) -> bool:
    run(["git", "add", "output", "history"])
    if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        say("Sin cambios que publicar")
        return True
    label = days[0] if len(days) == 1 else f"{days[0]} a {days[-1]}"
    msg = f"Actualización diaria: noticias del {label}"
    if run(["git", "commit", "-m", msg]).returncode or run(["git", "push"], timeout=300).returncode:
        return False
    say(f"Publicado: {msg}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Actualización diaria de AI News.")
    ap.add_argument("--no-push", action="store_true", help="genera los días pendientes, pero no publica")
    args = ap.parse_args()

    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 3 * 3600:
        say("Ya hay una actualización en marcha: no se lanza otra")
        return 0
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()))
    try:
        if run(["git", "pull", "--ff-only"], timeout=300).returncode:
            say("Aviso: no se pudo traer lo último de GitHub; se sigue en local")
        pending = py("pending").stdout.split()
        if not pending:
            say("Nada pendiente: la edición ya está al día")
            return 0
        say(f"Días pendientes: {', '.join(pending)}")
        done = []
        for day in pending:
            if not do_day(day):
                say(f"✗ El día {day} falló: se reintentará en la próxima ejecución")
                break
            done.append(day)
        if done and not args.no_push and not publish(done):
            say("✗ No se pudo publicar en GitHub")
            return 1
        return 0 if len(done) == len(pending) else 1
    except Exception as e:  # que quede en el registro aunque no haya consola
        say(f"✗ Error inesperado: {type(e).__name__}: {e}")
        return 1
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
