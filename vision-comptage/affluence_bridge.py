"""Pont entre le comptage vidéo et le call center Banque Claire.

Le script YOLO appelle `write_snapshot()` à chaque mise à jour. Le fichier produit
est lu par le backend (`app/affluence.py`) pour orienter les clients vers l'agence
la moins fréquentée et alimenter le poste conseiller.

Variables d'environnement :
    AFFLUENCE_CSV  chemin du CSV partagé (défaut : ./affluence.csv)
    AGENCE         nom court de l'agence (défaut : République)
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

DEFAULT_PATH = os.getenv("AFFLUENCE_CSV", "affluence.csv")
DEFAULT_AGENCY = os.getenv("AGENCE", "République")
HEADER = ["heure", "agence", "visibles", "entrees", "sorties", "alerte"]


def write_snapshot(
    visibles: int,
    entrees: int,
    sorties: int,
    alerte: bool,
    agence: str | None = None,
    path: str | Path | None = None,
) -> Path:
    """Ajoute une ligne d'affluence horodatée et retourne le chemin du CSV."""
    destination = Path(path or DEFAULT_PATH)
    destination.parent.mkdir(parents=True, exist_ok=True)
    nouveau = not destination.exists() or destination.stat().st_size == 0

    with destination.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if nouveau:
            writer.writerow(HEADER)
        writer.writerow(
            [
                datetime.now().isoformat(timespec="seconds"),
                agence or DEFAULT_AGENCY,
                int(visibles),
                int(entrees),
                int(sorties),
                "true" if alerte else "false",
            ]
        )
    return destination


if __name__ == "__main__":
    # Test rapide : écrit une ligne puis affiche le fichier.
    chemin = write_snapshot(3, 10, 7, False)
    print(f"Écrit dans {chemin.resolve()}")
    print(chemin.read_text(encoding="utf-8"))
