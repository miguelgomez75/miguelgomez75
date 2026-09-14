#!/usr/bin/env python3
"""
Elige el sprite de tu mascota (png/jpg/gif, aportados por ti en
assets/sprites/) segun cuantos commits llevas HOY. Se reinicia solo
cada dia porque el contador de "hoy" que da GitHub vuelve a 0 a
medianoche.

Estados (de menos a mas actividad hoy):
    sleeping -> waking_up -> awake -> curious -> happy -> hyper

Requiere: GITHUB_TOKEN (lo provee GitHub Actions) y GH_USERNAME.
Dependencias: requests, Pillow  (pip install requests pillow)
"""

import os
import sys
import shutil
import requests
from PIL import Image

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
USERNAME = os.environ["GH_USERNAME"]

GRAPHQL_URL = "https://api.github.com/graphql"
SPRITE_DIR = "assets/sprites"
OUTPUT_PATH = "dist/pet.gif"
CANDIDATE_EXTS = [".gif", ".png", ".jpg", ".jpeg"]

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

# Titulo que aparece arriba de la tarjeta de estado. Puedes sobreescribirlo
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


def fetch_today_count():
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

    # El ultimo dia de la lista es "hoy" segun GitHub (evita liarnos con
    # timezones: dejamos que sea GitHub quien decida donde empieza el dia).
    today = days[-1]
    return today["date"], today["contributionCount"]


def mood_from_count(count):
    state = STATE_ORDER[0]
    for s in STATE_ORDER:
        if count >= STATE_MIN[s]:
            state = s
    return state


def find_sprite(state):
    for ext in CANDIDATE_EXTS:
        path = os.path.join(SPRITE_DIR, state + ext)
        if os.path.isfile(path):
            return path
    return None


def export_sprite(state):
    src = find_sprite(state)
    os.makedirs("dist", exist_ok=True)

    if src is None:
        print(
            f"AVISO: no encontre sprite para el estado '{state}' en "
            f"{SPRITE_DIR}/ (busque {', '.join(state + e for e in CANDIDATE_EXTS)}). "
            "Sube esa imagen y vuelve a ejecutar el workflow.",
            file=sys.stderr,
        )
        return False

    if src.lower().endswith(".gif"):
        # Copiamos tal cual para conservar animacion si la tiene.
        shutil.copyfile(src, OUTPUT_PATH)
    else:
        # Convertimos png/jpg a gif para que el README siempre apunte
        # a la MISMA ruta, sin importar el formato original del sprite.
        img = Image.open(src)
        img = img.convert("RGBA") if "A" in img.mode else img.convert("RGB")
        img.save(OUTPUT_PATH, format="GIF")

    return True


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


def main():
    date, count = fetch_today_count()
    mood = mood_from_count(count)
    ok = export_sprite(mood)
    export_status(mood, count)
    status = "ok" if ok else "sprite faltante"
    print(f"fecha={date} commits_hoy={count} estado={mood} ({status})")


if __name__ == "__main__":
    main()
