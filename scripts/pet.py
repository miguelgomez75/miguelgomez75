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
# Ajusta estos numeros a tu gusto. Se evaluan de mayor a menor.
THRESHOLDS = {
    "hyper": 20,      # 20 o mas
    "happy": 10,      # 10-19
    "curious": 5,     # 5-9
    "awake": 2,       # 2-4
    "waking_up": 1,   # exactamente 1
}

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
    if count >= THRESHOLDS["hyper"]:
        return "hyper"
    if count >= THRESHOLDS["happy"]:
        return "happy"
    if count >= THRESHOLDS["curious"]:
        return "curious"
    if count >= THRESHOLDS["awake"]:
        return "awake"
    if count >= THRESHOLDS["waking_up"]:
        return "waking_up"
    return "sleeping"


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


def main():
    date, count = fetch_today_count()
    mood = mood_from_count(count)
    ok = export_sprite(mood)
    status = "ok" if ok else "sprite faltante"
    print(f"fecha={date} commits_hoy={count} estado={mood} ({status})")


if __name__ == "__main__":
    main()
