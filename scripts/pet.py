#!/usr/bin/env python3
"""
Elige el sprite de tu mascota (png/jpg/gif, aportados por ti en
assets/sprites/) segun cuantos commits llevas HOY, y genera ademas
una tarjeta de estadisticas (calendario del mes, rachas, contadores)
y un historial intradia de los cambios de estado.

Estados (de menos a mas actividad hoy):
    sleeping -> waking_up -> awake -> curious -> happy -> hyper

Requiere: GITHUB_TOKEN (lo provee GitHub Actions) y GH_USERNAME.
Dependencias: requests, Pillow  (pip install requests pillow)
"""

import os
import sys
import json
import shutil
import datetime
import requests
from PIL import Image

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
USERNAME = os.environ["GH_USERNAME"]

GRAPHQL_URL = "https://api.github.com/graphql"
SPRITE_BASE_DIR = "assets/sprites"
SKINS_CONFIG_PATH = "skins.json"
OUTPUT_PATH = "dist/pet.gif"
HISTORY_PATH = "dist/history.json"
HISTORY_DAYS_KEPT = 30  # cuantos dias de historial intradia conservamos
CANDIDATE_EXTS = [".gif", ".png", ".jpg", ".jpeg"]
DEFAULT_SKIN = "default"

# --- Umbrales de commits DE HOY para cada estado ---
# Ajusta estos numeros a tu gusto. STATE_ORDER define el orden de menos
# a mas actividad; STATE_MIN el commit minimo (de hoy) para cada uno.
STATE_ORDER = ["sleeping", "waking_up", "awake", "curious", "happy", "hyper"]
STATE_MIN = {
    "sleeping": 0,
    "waking_up": 1,
    "awake": 2,
    "curious": 5,
    "happy": 10,
    "hyper": 20,
}

# Color de cada estado, usado en el calendario de la tarjeta de stats.
STATE_COLOR = {
    "sleeping": "#30363d",
    "waking_up": "#0e4429",
    "awake": "#006d32",
    "curious": "#26a641",
    "happy": "#39d353",
    "hyper": "#f2cc60",
}

DOW_LABELS_ES = ["L", "M", "X", "J", "V", "S", "D"]
# Estados con fondo oscuro necesitan el numero del dia en texto claro;
# el resto (fondos claros) lo llevan en texto oscuro, para contraste.
STATE_DARK_BG = {"sleeping", "waking_up", "awake"}
MONTH_NAMES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# Titulo que aparece arriba de las tarjetas. Puedes sobreescribirlo
# poniendo PET_TITLE como variable de entorno en el workflow.
TITLE = os.environ.get("PET_TITLE", "Mi actividad de hoy")

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_calendar():
    """Devuelve la lista completa de dias (hasta ~1 ano) que da GitHub,
    ordenada por fecha ascendente: [{"date": "YYYY-MM-DD", "contributionCount": N}, ...]
    """
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": QUERY, "variables": {"login": USERNAME}},
        headers={"Authorization": f"bearer {GITHUB_TOKEN}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        print(data["errors"], file=sys.stderr)
        sys.exit(1)

    calendar = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = []
    for week in calendar["weeks"]:
        days.extend(week["contributionDays"])
    days.sort(key=lambda d: d["date"])
    return days


def mood_from_count(count):
    state = STATE_ORDER[0]
    for s in STATE_ORDER:
        if count >= STATE_MIN[s]:
            state = s
    return state


# ─────────────────────────── Skins (temporadas) ───────────────────────────

def load_skin_config():
    """Lee skins.json de la raiz del repo. Si no existe o esta mal formado,
    se usa solo el skin 'default' sin temporadas."""
    fallback = {"default": DEFAULT_SKIN, "seasons": [], "override": None}
    if not os.path.isfile(SKINS_CONFIG_PATH):
        return fallback
    try:
        with open(SKINS_CONFIG_PATH) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"AVISO: skins.json invalido ({e}), uso solo 'default'.", file=sys.stderr)
        return fallback
    fallback.update(cfg)
    return fallback


def _md(date_str):
    """'MM-DD' -> (mes, dia) como enteros, para comparar sin el ano."""
    m, d = date_str.split("-")
    return int(m), int(d)


def date_in_range(today, from_str, to_str):
    """True si today cae dentro del rango [from_str, to_str] (formato
    'MM-DD', sin ano, se repite cada ano). Soporta rangos que cruzan
    fin de ano, p.ej. de '12-20' a '01-05'."""
    f, t = _md(from_str), _md(to_str)
    now = (today.month, today.day)
    if f <= t:
        return f <= now <= t
    return now >= f or now <= t  # el rango cruza el 31 de diciembre


def resolve_skin(cfg, today):
    """Decide que skin usar hoy: override manual > temporada por fecha > default."""
    override = cfg.get("override")
    if override:
        return override, "override manual"

    for season in cfg.get("seasons", []):
        try:
            if date_in_range(today, season["from"], season["to"]):
                return season["skin"], f"temporada ({season['from']} a {season['to']})"
        except (KeyError, ValueError):
            print(f"AVISO: entrada de temporada mal formada en skins.json: {season}", file=sys.stderr)

    return cfg.get("default", DEFAULT_SKIN), "skin por defecto"


def find_sprite(state, skin):
    """Busca el sprite del estado dentro de la carpeta del skin activo.
    Si no existe ahi, cae al skin 'default' (para que un skin de
    temporada no tenga que incluir los 6 estados si no quieres)."""
    for candidate_skin in [skin, DEFAULT_SKIN]:
        for ext in CANDIDATE_EXTS:
            path = os.path.join(SPRITE_BASE_DIR, candidate_skin, state + ext)
            if os.path.isfile(path):
                return path, candidate_skin
    return None, None


def export_sprite(state, skin):
    src, used_skin = find_sprite(state, skin)
    os.makedirs("dist", exist_ok=True)

    if src is None:
        print(
            f"AVISO: no encontre sprite para el estado '{state}' ni en el skin "
            f"'{skin}' ni en '{DEFAULT_SKIN}' dentro de {SPRITE_BASE_DIR}/. "
            "Sube esa imagen y vuelve a ejecutar el workflow.",
            file=sys.stderr,
        )
        return False, None

    if used_skin != skin:
        print(
            f"AVISO: el skin '{skin}' no tiene sprite para '{state}', "
            f"uso el de '{DEFAULT_SKIN}' como respaldo.",
            file=sys.stderr,
        )

    if src.lower().endswith(".gif"):
        shutil.copyfile(src, OUTPUT_PATH)
    else:
        img = Image.open(src)
        img = img.convert("RGBA") if "A" in img.mode else img.convert("RGB")
        img.save(OUTPUT_PATH, format="GIF")

    return True, used_skin


def build_status_svg(state, count, dark):
    idx = STATE_ORDER.index(state)
    cur_min = STATE_MIN[state]

    if idx < len(STATE_ORDER) - 1:
        next_state = STATE_ORDER[idx + 1]
        next_min = STATE_MIN[next_state]
        remaining = max(next_min - count, 0)
        span = next_min - cur_min
        progress = min(max((count - cur_min) / span, 0), 1) if span > 0 else 1.0
        subtitle = f"Faltan {remaining} commit(s) para pasar a '{next_state}'"
    else:
        progress = 1.0
        subtitle = "¡Estado máximo alcanzado hoy!"

    bg = "#0d1117" if dark else "#ffffff"
    text_color = "#c9d1d9" if dark else "#24292f"
    muted_color = "#8b949e" if dark else "#57606a"
    bar_bg = "#30363d" if dark else "#e1e4e8"
    bar_fill = "#3fb950"

    width, height = 280, 110
    bar_x, bar_y, bar_w, bar_h = 16, 70, width - 32, 14
    filled_w = bar_w * progress

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" rx="8" fill="{bg}"/>
  <text x="{width/2}" y="22" font-size="14" font-weight="bold" fill="{text_color}"
        font-family="Segoe UI, Helvetica, Arial, sans-serif" text-anchor="middle">{TITLE}</text>
  <text x="{width/2}" y="42" font-size="13" fill="{text_color}"
        font-family="Segoe UI, Helvetica, Arial, sans-serif" text-anchor="middle">
    Estado: {state} · {count} commit(s) hoy
  </text>
  <rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="7" fill="{bar_bg}"/>
  <rect x="{bar_x}" y="{bar_y}" width="{filled_w:.1f}" height="{bar_h}" rx="7" fill="{bar_fill}"/>
  <text x="{width/2}" y="{bar_y + bar_h + 16}" font-size="11" fill="{muted_color}"
        font-family="Segoe UI, Helvetica, Arial, sans-serif" text-anchor="middle">{subtitle}</text>
</svg>'''
    return svg


def export_status(state, count):
    os.makedirs("dist", exist_ok=True)
    with open("dist/pet-status-light.svg", "w") as f:
        f.write(build_status_svg(state, count, dark=False))
    with open("dist/pet-status-dark.svg", "w") as f:
        f.write(build_status_svg(state, count, dark=True))


# ─────────────────────────── Estadisticas ───────────────────────────

def compute_current_streak(days_by_date, today):
    """Dias consecutivos (terminando hoy) con al menos 1 commit."""
    streak = 0
    d = today
    while True:
        count = days_by_date.get(d.isoformat())
        if count is None or count <= 0:
            break
        streak += 1
        d -= datetime.timedelta(days=1)
    return streak


def compute_max_streak(days):
    """Racha mas larga de dias consecutivos con >=1 commit en TODO
    el calendario que nos da GitHub (hasta ~1 ano)."""
    best = 0
    current = 0
    for d in days:
        if d["contributionCount"] > 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def compute_month_stats(days, today):
    """Devuelve dict con: month_days (solo el mes actual, hasta hoy),
    state_counts (dias por estado), best_day (fecha, commits),
    avg_active (media de commits en dias con >=1 commit)."""
    month_days = [
        d for d in days
        if d["date"].startswith(today.strftime("%Y-%m"))
        and d["date"] <= today.isoformat()
    ]

    state_counts = {s: 0 for s in STATE_ORDER}
    best_day = None
    active_counts = []

    for d in month_days:
        mood = mood_from_count(d["contributionCount"])
        state_counts[mood] += 1
        if d["contributionCount"] > 0:
            active_counts.append(d["contributionCount"])
        if best_day is None or d["contributionCount"] > best_day["contributionCount"]:
            best_day = d

    avg_active = sum(active_counts) / len(active_counts) if active_counts else 0.0

    return {
        "month_days": month_days,
        "state_counts": state_counts,
        "best_day": best_day,
        "avg_active": avg_active,
    }


def build_stats_svg(days, today, dark):
    days_by_date = {d["date"]: d["contributionCount"] for d in days}
    current_streak = compute_current_streak(days_by_date, today)
    max_streak = compute_max_streak(days)
    stats = compute_month_stats(days, today)
    month_days_by_date = {d["date"]: d for d in stats["month_days"]}

    bg = "#0d1117" if dark else "#ffffff"
    text_color = "#c9d1d9" if dark else "#24292f"
    muted_color = "#8b949e" if dark else "#57606a"
    cell_border = "#010409" if dark else "#ffffff"

    width = 340
    cell, gap, cols = 22, 4, 7
    grid_width = cols * cell + (cols - 1) * gap
    left = (width - grid_width) / 2

    first_of_month = today.replace(day=1)
    offset = first_of_month.weekday()  # lunes = 0
    total_cells = offset + today.day
    rows = -(-total_cells // cols)  # ceil

    elems = []
    y = 22
    elems.append(
        f'<text x="{width/2}" y="{y}" font-size="14" font-weight="bold" fill="{text_color}" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif" text-anchor="middle">{TITLE} — estadísticas</text>'
    )
    y += 20
    elems.append(
        f'<text x="{width/2}" y="{y}" font-size="12" fill="{muted_color}" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif" text-anchor="middle">'
        f'{MONTH_NAMES_ES[today.month - 1]} {today.year}</text>'
    )
    y += 16

    for c, lbl in enumerate(DOW_LABELS_ES):
        x = left + c * (cell + gap) + cell / 2
        elems.append(
            f'<text x="{x:.1f}" y="{y + 8}" font-size="9" fill="{muted_color}" '
            f'font-family="Segoe UI, Helvetica, Arial, sans-serif" text-anchor="middle">{lbl}</text>'
        )
    y += 14
    grid_top = y

    day_num = 1
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            if idx < offset or day_num > today.day:
                continue
            date_str = today.replace(day=day_num).isoformat()
            entry = month_days_by_date.get(date_str)
            mood = mood_from_count(entry["contributionCount"]) if entry else "sleeping"
            color = STATE_COLOR[mood]
            cx = left + c * (cell + gap)
            cy = grid_top + r * (cell + gap)
            elems.append(
                f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cell}" height="{cell}" rx="4" '
                f'fill="{color}" stroke="{cell_border}" stroke-width="1"/>'
            )
            elems.append(
                f'<text x="{cx + cell/2:.1f}" y="{cy + cell/2 + 3:.1f}" font-size="8.5" '
                f'fill="{"#e6edf3" if mood in STATE_DARK_BG else "#0d1117"}" '
                f'font-family="Segoe UI, Helvetica, Arial, sans-serif" '
                f'text-anchor="middle">{day_num}</text>'
            )
            day_num += 1

    y = grid_top + rows * (cell + gap) + 10

    def line(text, size=12, bold=False, color=text_color):
        nonlocal y
        weight = "font-weight=\"bold\" " if bold else ""
        elems.append(
            f'<text x="16" y="{y}" font-size="{size}" {weight}fill="{color}" '
            f'font-family="Segoe UI, Helvetica, Arial, sans-serif">{text}</text>'
        )
        y += size + 8

    def line_wrapped(parts, sep=" · ", size=11, color=text_color, max_chars=52):
        """Igual que line(), pero reparte 'parts' en varias líneas si la
        unión supera max_chars, para que nunca se salga del ancho de la tarjeta."""
        current = ""
        for part in parts:
            candidate = (current + sep + part) if current else part
            if len(candidate) > max_chars and current:
                line(current, size=size, color=color)
                current = part
            else:
                current = candidate
        if current:
            line(current, size=size, color=color)

    line(f"Racha actual: {current_streak} día(s) · Racha máxima: {max_streak} día(s)", size=12.5)

    if stats["best_day"]:
        bd = stats["best_day"]
        bd_date = datetime.date.fromisoformat(bd["date"])
        line(f"Mejor día del mes: {bd_date.day} ({bd['contributionCount']} commits)", size=12.5)

    line(f"Media en días activos: {stats['avg_active']:.1f} commits", size=12.5)

    y += 2
    line("Días por estado este mes:", size=11, bold=True, color=muted_color)
    parts = [
        f"{s}: {stats['state_counts'][s]}"
        for s in STATE_ORDER
        if stats["state_counts"][s] > 0
    ]
    if parts:
        line_wrapped(parts, size=11, color=muted_color)
    else:
        line("(sin datos)", size=11, color=muted_color)

    height = y + 6
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height:.0f}" '
        f'viewBox="0 0 {width} {height:.0f}">'
        f'<rect width="{width}" height="{height:.0f}" rx="8" fill="{bg}"/>'
        + "".join(elems)
        + "</svg>"
    )
    return svg


def export_stats(days, today):
    os.makedirs("dist", exist_ok=True)
    with open("dist/pet-stats-light.svg", "w") as f:
        f.write(build_stats_svg(days, today, dark=False))
    with open("dist/pet-stats-dark.svg", "w") as f:
        f.write(build_stats_svg(days, today, dark=True))


# ─────────────────────────── Tarjeta de temporada ───────────────────────────

# Color representativo de cada skin para la línea de tiempo
SKIN_COLOR = {
    "sylveon":  "#f4a7d0",
    "todos":    "#b0c4de",
    "vaporeon": "#5bc8f5",
    "leafeon":  "#78c85b",
    "espeon":   "#c084e8",
    "flareon":  "#f97316",
    "umbreon":  "#4a4a6a",
    "eevee":    "#c8a87a",
    "glaceon":  "#a8d8ea",
    "jolteon":  "#f2cc60",
}
SKIN_LABEL = {
    "sylveon":  "Sylveon",
    "todos":    "Todos",
    "vaporeon": "Vaporeon",
    "leafeon":  "Leafeon",
    "espeon":   "Espeon",
    "flareon":  "Flareon",
    "umbreon":  "Umbreon",
    "eevee":    "Eevee",
    "glaceon":  "Glaceon",
    "jolteon":  "Jolteon",
}


def iter_year(year, cfg):
    """Devuelve una lista de 365/366 entradas (date, skin) para el año dado,
    usando la misma lógica de resolve_skin pero sin el campo 'override'."""
    start = datetime.date(year, 1, 1)
    end   = datetime.date(year, 12, 31)
    result = []
    d = start
    while d <= end:
        skin = cfg.get("default", "sylveon")
        for season in cfg.get("seasons", []):
            try:
                if date_in_range(d, season["from"], season["to"]):
                    skin = season["skin"]
                    break
            except (KeyError, ValueError):
                pass
        result.append((d, skin))
        d += datetime.timedelta(days=1)
    return result


def find_next_change(today, year_map):
    """A partir de hoy, busca el próximo día en que cambia el skin.
    Busca hasta 2 años hacia adelante por si today está muy cerca del fin de año."""
    current_skin = next((s for d, s in year_map if d == today), None)
    for d, skin in year_map:
        if d > today and skin != current_skin:
            return d, skin
    return None, None


def build_season_svg(cfg, today, dark):
    bg         = "#0d1117" if dark else "#ffffff"
    text_color = "#c9d1d9" if dark else "#24292f"
    muted      = "#8b949e" if dark else "#57606a"
    track_bg   = "#30363d" if dark else "#e1e4e8"

    width = 420
    # Construimos el mapa del año actual + siguiente (para next_change)
    year_map_this = iter_year(today.year, cfg)
    year_map_next = iter_year(today.year + 1, cfg)
    combined = year_map_this + year_map_next

    current_skin, current_reason = resolve_skin(cfg, today)
    next_date, next_skin = find_next_change(today, combined)

    days_left = (next_date - today).days if next_date else None

    # ── Línea de tiempo anual ──
    # Agrupamos el año en segmentos continuos del mismo skin
    segments = []
    for d, skin in year_map_this:
        if segments and segments[-1][2] == skin:
            segments[-1][1] = d
        else:
            segments.append([d, d, skin])

    total_days = 366 if (today.year % 4 == 0 and (today.year % 100 != 0 or today.year % 400 == 0)) else 365
    bar_x, bar_y, bar_w, bar_h = 16, 0, width - 32, 12

    elems = []
    y = 22
    elems.append(
        f'<text x="{width/2}" y="{y}" font-size="14" font-weight="bold" fill="{text_color}" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif" text-anchor="middle">{TITLE} — temporadas</text>'
    )
    y += 20

    # Skin activo
    active_color = SKIN_COLOR.get(current_skin, "#888")
    active_label = SKIN_LABEL.get(current_skin, current_skin)
    reason_text  = "override manual" if cfg.get("override") else ("temporada" if current_skin != cfg.get("default") else "skin por defecto")
    elems.append(
        f'<text x="{width/2}" y="{y}" font-size="12.5" fill="{text_color}" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif" text-anchor="middle">'
        f'Ahora: <tspan font-weight="bold" fill="{active_color}">{active_label}</tspan>'
        f' <tspan font-size="11" fill="{muted}">({reason_text})</tspan></text>'
    )
    y += 18

    # Próximo cambio
    if next_date and next_skin:
        next_color = SKIN_COLOR.get(next_skin, "#888")
        next_label = SKIN_LABEL.get(next_skin, next_skin)
        elems.append(
            f'<text x="{width/2}" y="{y}" font-size="11.5" fill="{muted}" '
            f'font-family="Segoe UI, Helvetica, Arial, sans-serif" text-anchor="middle">'
            f'Próximo: <tspan fill="{next_color}" font-weight="bold">{next_label}</tspan>'
            f' el {next_date.day}/{next_date.month} '
            f'<tspan>({days_left} día{"s" if days_left != 1 else ""})</tspan></text>'
        )
    y += 18

    # Barra de año
    bar_y = y
    elems.append(
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="6" fill="{track_bg}"/>'
    )
    jan1 = datetime.date(today.year, 1, 1)
    for seg_start, seg_end, skin in segments:
        day_start = (seg_start - jan1).days
        day_end   = (seg_end   - jan1).days + 1
        sx = bar_x + bar_w * day_start / total_days
        sw = bar_w * (day_end - day_start) / total_days
        color = SKIN_COLOR.get(skin, "#888")
        r = "6" if day_start == 0 else ("0" if day_end < total_days else "6")
        elems.append(
            f'<rect x="{sx:.1f}" y="{bar_y}" width="{sw:.1f}" height="{bar_h}" '
            f'rx="{r}" fill="{color}"/>'
        )

    # Marcador de hoy
    today_x = bar_x + bar_w * (today - jan1).days / total_days + bar_w / total_days / 2
    elems.append(
        f'<line x1="{today_x:.1f}" y1="{bar_y - 3}" x2="{today_x:.1f}" y2="{bar_y + bar_h + 3}" '
        f'stroke="{text_color}" stroke-width="2" stroke-linecap="round"/>'
    )
    y = bar_y + bar_h + 14

    # Leyenda compacta: dos columnas
    legend_skins = [s for s in SKIN_LABEL if s in {sk for _, sk in year_map_this}]
    dot_r, col_w = 5, (width - 32) // 2
    for i, skin in enumerate(legend_skins):
        col = i % 2
        row = i // 2
        lx = bar_x + col * col_w
        ly = y + row * 16
        color = SKIN_COLOR.get(skin, "#888")
        label = SKIN_LABEL.get(skin, skin)
        elems.append(f'<circle cx="{lx + dot_r}" cy="{ly - 3}" r="{dot_r}" fill="{color}"/>')
        elems.append(
            f'<text x="{lx + dot_r * 2 + 4}" y="{ly}" font-size="11" fill="{muted}" '
            f'font-family="Segoe UI, Helvetica, Arial, sans-serif">{label}</text>'
        )

    legend_rows = -(-len(legend_skins) // 2)
    height = y + legend_rows * 16 + 8

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height:.0f}" '
        f'viewBox="0 0 {width} {height:.0f}">'
        f'<rect width="{width}" height="{height:.0f}" rx="8" fill="{bg}"/>'
        + "".join(elems)
        + "</svg>"
    )


def export_season(cfg, today):
    os.makedirs("dist", exist_ok=True)
    with open("dist/pet-season-light.svg", "w") as f:
        f.write(build_season_svg(cfg, today, dark=False))
    with open("dist/pet-season-dark.svg", "w") as f:
        f.write(build_season_svg(cfg, today, dark=True))



def load_history():
    if not os.path.isfile(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def update_history(mood, count, today):
    """Anade una entrada al historial SOLO si el estado cambio respecto
    a la ultima entrada registrada (o es el primer run del dia), para
    no llenar el archivo de entradas identicas cada 5 minutos. Recorta
    entradas de mas de HISTORY_DAYS_KEPT dias de antiguedad."""
    history = load_history()
    now = datetime.datetime.now(datetime.timezone.utc)

    last = history[-1] if history else None
    should_append = (
        last is None
        or last.get("date") != today.isoformat()
        or last.get("mood") != mood
    )

    if should_append:
        history.append({
            "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date": today.isoformat(),
            "mood": mood,
            "count": count,
        })

    cutoff = (today - datetime.timedelta(days=HISTORY_DAYS_KEPT)).isoformat()
    history = [h for h in history if h.get("date", "9999-99-99") >= cutoff]

    os.makedirs("dist", exist_ok=True)
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    return should_append


def main():
    days = fetch_calendar()
    today_entry = days[-1]
    today = datetime.date.fromisoformat(today_entry["date"])
    count = today_entry["contributionCount"]
    mood = mood_from_count(count)

    skin_cfg = load_skin_config()
    skin, skin_reason = resolve_skin(skin_cfg, today)

    ok, used_skin = export_sprite(mood, skin)
    export_status(mood, count)
    export_stats(days, today)
    export_season(skin_cfg, today)
    logged = update_history(mood, count, today)

    status = "ok" if ok else "sprite faltante"
    hist = "nueva entrada en history.json" if logged else "sin cambios en history.json"
    skin_info = f"skin={skin} ({skin_reason})" + (f", sprite servido desde '{used_skin}'" if used_skin and used_skin != skin else "")
    print(f"fecha={today.isoformat()} commits_hoy={count} estado={mood} ({status}) [{hist}] {skin_info}")


if __name__ == "__main__":
    main()
