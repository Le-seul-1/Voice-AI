#!/usr/bin/env python3
"""Simule le flux d'affluence des quatre agences pour la démonstration.

Utile quand la caméra n'est pas branchée : le poste conseiller et l'assistant
vocal reçoivent des données qui évoluent en direct, au même format que le CSV
produit par le module de comptage YOLO.

Exemples :
    python scripts/simulate_affluence.py --once
    python scripts/simulate_affluence.py --duration 600 --interval 2
"""

from __future__ import annotations

import argparse
import csv
import random
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "app" / "data" / "affluence.csv"

AGENCIES = [
    # nom, ville, visibles de départ, entrées, sorties, probabilité d'alerte
    ("République", "Paris", 11, 48, 37, 0.55),
    ("Bellecour", "Lyon", 4, 21, 17, 0.05),
    ("Prado", "Marseille", 7, 33, 26, 0.15),
    ("Centre", "Lille", 2, 12, 10, 0.02),
]


def write_row(handle: csv.writer, agency: str, visibles: int, entrees: int, sorties: int, alerte: bool) -> None:
    handle.writerow(
        [
            datetime.now().isoformat(timespec="seconds"),
            agency,
            max(0, visibles),
            max(0, entrees),
            max(0, sorties),
            "true" if alerte else "false",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Simule affluence.csv pour la démo Banque Claire.")
    parser.add_argument("--path", default=str(DEFAULT_PATH), help="Chemin du CSV partagé.")
    parser.add_argument("--interval", type=float, default=2.0, help="Secondes entre deux mesures.")
    parser.add_argument("--duration", type=float, default=0, help="Durée totale (0 = infini).")
    parser.add_argument("--once", action="store_true", help="Écrit une seule mesure puis quitte.")
    parser.add_argument("--reset", action="store_true", help="Réécrit le fichier depuis zéro.")
    args = parser.parse_args()

    path = Path(args.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if args.reset or not path.exists():
        path.write_text("heure,agence,visibles,entrees,sorties,alerte\n", encoding="utf-8")

    state = {
        name: {"visibles": visibles, "entrees": entrees, "sorties": sorties, "alert": prob}
        for name, _city, visibles, entrees, sorties, prob in AGENCIES
    }
    start = time.time()
    print(f"Simulation → {path} (Ctrl+C pour arrêter)")

    try:
        while True:
            with path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                for name, _city, _v, _e, _s, prob in AGENCIES:
                    item = state[name]
                    arrivals = random.choices([0, 1, 2], weights=[0.55, 0.35, 0.10])[0]
                    departures = random.choices([0, 1, 2], weights=[0.60, 0.32, 0.08])[0]
                    item["entrees"] += arrivals
                    item["sorties"] += departures
                    item["visibles"] = max(0, item["visibles"] + arrivals - departures)
                    alerte = item["visibles"] >= 10 and random.random() < prob
                    write_row(writer, name, item["visibles"], item["entrees"], item["sorties"], alerte)

            if args.once:
                break
            if args.duration and time.time() - start >= args.duration:
                break
            time.sleep(max(0.2, args.interval))
    except KeyboardInterrupt:
        print("\nSimulation arrêtée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
