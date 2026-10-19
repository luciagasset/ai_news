# AI News

**Edición en vivo:** https://luciagasset.github.io/ai_news/

Resumen, en español, de lo que se mueve en inteligencia artificial: **avances en modelos frontera,
debates, polémicas y noticias**. **Se actualiza cada mañana** con las noticias del día anterior. Las ediciones son semanas
de lunes a domingo (unas 15 noticias), sin solaparse: la portada es la semana en curso, con «Lo último» arriba, y
cada semana completa queda en `ediciones.html`. Las noticias van en tarjetas que se amplían al pulsarlas.

La edición se abre en la semana:

- **La semana** (principal): un botón por tipo (Modelos frontera, En debate, Polémicas, Noticias),
  «El pulso de la semana» (un punto por noticia en el día en que surgió, más grande cuanto más se debatió),
  lo más destacado, el listado completo con búsqueda y filtros, y el índice de ediciones con búsqueda en
  todo el histórico.
- **Día a día**: un selector y unas flechas recorren los 7 días; cada día ordena sus noticias por tipo.

La página está en español e inglés, con un selector ES/EN arriba a la derecha (recuerda la elección y, la
primera vez, usa el idioma del navegador).

Cada edición genera además dos piezas para compartir en LinkedIn: una **imagen de vista previa**
(`output/og/<fecha>.png`, con etiquetas Open Graph) y un **carrusel PDF** de 1080×1350
(`output/carrusel/<fecha>.pdf`).

**Compartir una noticia**: el botón de la hoja de cada noticia abre un menú con WhatsApp, Instagram, Telegram,
LinkedIn, X, correo, copiar enlace y (en el móvil) el resto de apps del sistema. Cada noticia tiene su propia
página, `output/noticias/<id>.html`, con su titular e imagen (`output/og/noticias/<id>.png`), para que el enlace
muestre esa noticia y no la edición entera. Instagram no admite enlaces desde la web: en el móvil se comparte la
imagen cuadrada de la noticia (`output/instagram/<id>.png`) con la hoja del sistema; en el ordenador se descarga
y se copia el texto del pie.

El criterio no es lo primero que sale en un buscador, sino lo que genera conversación real: cuántas
fuentes distintas lo cuentan y cuánto se discute en Hacker News y en los comentarios de YouTube.

## Cómo funciona

```
 YouTube (transcripciones) ─┐
 RSS de medios ─────────────┤                          ┌─ Claude Code ─────────────────┐
 Blogs oficiales de labs ───┼─► 1. ingest ─► para_claude.md ─► candidatos.json        │
 Hacker News ───────────────┘                          │  (agrupa y clasifica)          │
                                                       │                                │
              2. select (puntuación) ─► para_resumir.md ─► resumenes.json             │
                                                       │  (resume en dos niveles)       │
                                                       └────────────────────────────────┘
              3. render ─► history/AAAA-MM-DD.json + output/index.html (la semana en curso)
```

La Fase 1 **no usa ninguna API de pago**. El script hace todo lo mecánico (descargar, transcribir,
puntuar, guardar y maquetar) y deja los textos listos en ficheros; la parte editorial (agrupar,
clasificar y resumir) la hace Claude Code leyendo esos ficheros, con las reglas de
[`docs/instrucciones-claude-code.md`](docs/instrucciones-claude-code.md).

1. **Ingesta**: vídeos del día de los canales configurados (YouTube Data API v3) con su
   transcripción, feeds RSS, páginas de novedades de OpenAI, Anthropic y Google DeepMind, e historias de
   IA de Hacker News. Todo queda en `data/raw/<fecha>/`.
2. **Agrupación y clasificación** (Claude Code): un vídeo de noticias repasa varias noticias, así que se
   separan por tema y se unen las fuentes que cuentan el mismo hecho. Cada noticia recibe tipo
   (avance, debate, polémica, noticia), categoría, entidades y el minuto del vídeo.
3. **Puntuación** (`select`): número de fuentes distintas, intensidad del debate (puntos y comentarios),
   frescura, tipo (los avances y las polémicas pesan más) y temas prioritarios. Se garantiza al menos un
   elemento por tipo si hay material con peso real; un día sin polémicas no se rellena. Un modelo de
   embeddings local avisa de posibles duplicados.
4. **Resumen** (Claude Code): titular, resumen breve y ampliado con una plantilla por tipo y reglas de
   neutralidad (cada opinión atribuida; lo no verificado, marcado "sin confirmar"). Una polémica solo se
   da por confirmada con dos fuentes independientes o una oficial.
5. **Histórico y página** (`render`): cada edición se guarda con embeddings, lista para detectar noticias
   relacionadas, y se genera un único HTML autocontenido por semana, con modo claro y oscuro, pensado para
   leerse con una mano en el móvil, además del índice de ediciones. El diseño sigue las Human Interface
   Guidelines de Apple. Se adapta a móvil, tablet (también en horizontal) y ordenador, y se puede instalar
   como app (manifiesto + service worker): se abre a pantalla completa y guarda las ediciones leídas para
   verlas sin conexión. La selección se reparte entre los días y los tipos, con mínimos y topes en
   `config/sources.yaml`.

## Puesta en marcha

Requisitos: Python 3.10+ y una clave de la
[YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) (la cuota gratuita sobra).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # y rellena YOUTUBE_API_KEY
```

### Actualización diaria automática

`scripts/daily.py` hace todo el proceso para los días que falten (normalmente, ayer) y publica en GitHub Pages.
Los dos pasos editoriales los escribe Claude Code en modo no interactivo (`claude -p`) con tu sesión, sin API de
pago y sin acceso a terminal ni a la web. Para programarlo cada día a las 07:07:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\programar-tarea.ps1
```

La tarea despierta el ordenador si está en suspensión; si estaba apagado, se ejecuta al encenderlo y recupera
los días que falten (hasta 7). El registro queda en `logs/diario.log`. Para quitarla, añade `-Quitar`.

### A mano

Abre Claude Code en la carpeta del proyecto y pídele «genera el día» (o una fecha): `CLAUDE.md` le indica los
pasos. Son:

| Paso | Comando | Resultado |
| --- | --- | --- |
| 1 | `python run_weekly.py ingest --date 2026-10-15` | `data/raw/<fecha>/para_claude.md` |
| — | Claude Code escribe `candidatos.json` | |
| 2 | `python run_weekly.py select --date 2026-10-15` | `data/raw/<fecha>/para_resumir.md` |
| — | Claude Code escribe `resumenes.json` | |
| 3 | `python run_weekly.py render --date 2026-10-15` | `history/<fecha>.json`, la portada `output/index.html` (la semana de `<fecha>`), `output/ediciones.html` y las páginas de cada noticia |

`--date` es el día de las noticias; sin `--date` se usa ayer. Con las noticias del domingo, la semana se archiva
como `output/<domingo>.html`. `run_weekly.py pending` lista los días que
faltan. `ingest --reuse-raw` reutiliza la descarga guardada. Las transcripciones se cachean en `data/cache/`.

## Configuración

Todas las fuentes están en [`config/sources.yaml`](config/sources.yaml): canales de YouTube (por handle),
feeds RSS, laboratorios, palabras clave de Hacker News, temas prioritarios y número de noticias.
`enabled: false` desactiva una fuente sin borrarla.

## Estructura

```
config/sources.yaml     fuentes y parámetros
src/ingest/             youtube.py, rss.py, labs.py, hackernews.py
src/transcripts.py      subtítulos de YouTube con caché
src/classify.py         prepara para_claude.md y valida candidatos.json
src/cluster.py          grupos de fuentes y aviso de duplicados (embeddings)
src/score.py            puntuación y selección
src/summarize.py        prepara para_resumir.md y valida resumenes.json
docs/instrucciones-claude-code.md   reglas editoriales de clasificación y resumen
src/history.py          persistencia en history/
src/render.py           edición (templates/week.html), índice (templates/index.html) y página e imágenes
                        de cada noticia (templates/story.html, templates/card.html)
run_weekly.py           punto de entrada (un paso, un día)
scripts/daily.py        actualización diaria automática; scripts/programar-tarea.ps1 la programa
```

## Límites conocidos

- **X no se lee directamente** (su API es de pago): su debate llega a través de vídeos, Hacker News y medios.
- **Señales del día**: la ingesta se hace a la mañana siguiente, así que los puntos y comentarios de Hacker News
  de una noticia de última hora aún son pocos.
- **Ordenador encendido**: la tarea diaria corre en el PC; si está apagado varios días, recupera hasta 7 al encenderlo.
- **Transcripciones**: si un vídeo no tiene subtítulos, se resume con título y descripción y se marca como parcial.
- **Calidad**: los resúmenes los escribe un modelo de IA y pueden equivocarse; cada noticia enlaza a sus fuentes.

## Hoja de ruta

- **Fase 1** (actual): pipeline completo con 3 canales, 2 medios, 3 laboratorios y Hacker News.
- **Fase 2**: todas las fuentes (Reddit, arXiv, más laboratorios) y noticias relacionadas entre
  ediciones (Seguimiento, Relacionada, Contradicción).
- **Fase 3** (en marcha): actualización diaria a las 07:07 en el PC con Claude Code (`claude -p`, con la
  suscripción, sin API de pago) y publicación automática en GitHub Pages.
