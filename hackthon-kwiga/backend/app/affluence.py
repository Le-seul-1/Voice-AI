"""Lecture locale de l'affluence des agences produite par le module vidéo.

Le module de comptage (YOLO) écrit un CSV. Le call center le lit sans réseau :
c'est le point de jonction entre la vision et l'assistant vocal.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from .banking import agencies
from .config import AFFLUENCE_CSV
from .rag import normalize

logger = logging.getLogger(__name__)

TRUE_VALUES = {"1", "true", "vrai", "oui", "yes", "alerte"}


def _as_bool(value: str) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def _as_int(value: str) -> int:
    try:
        return max(0, int(float((value or "0").strip())))
    except (TypeError, ValueError, OverflowError):
        return 0


def _read_rows() -> list[dict]:
    path = Path(AFFLUENCE_CSV)
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        logger.warning("Fichier d'affluence illisible : %s", path, exc_info=True)
        return []


def _latest_by_agency() -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in _read_rows():
        agency = (row.get("agence") or "").strip()
        if not agency:
            continue
        key = normalize(agency)
        previous = latest.get(key)
        timestamp = (row.get("heure") or "").strip()
        if previous and previous["heure"] >= timestamp:
            continue
        latest[key] = {
            "agency": agency,
            "heure": timestamp,
            "visibles": _as_int(row.get("visibles", "0")),
            "entrees": _as_int(row.get("entrees", "0")),
            "sorties": _as_int(row.get("sorties", "0")),
            "alerte": _as_bool(row.get("alerte", "")),
        }
    return latest


def _level(snapshot: dict) -> str:
    if snapshot["alerte"] or snapshot["visibles"] >= 10:
        return "forte"
    if snapshot["visibles"] >= 5:
        return "moderee"
    return "calme"


def _is_stale(timestamp: str, minutes: int = 10) -> bool:
    if not timestamp:
        return True
    try:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    now = datetime.now(moment.tzinfo) if moment.tzinfo else datetime.now()
    return (now - moment).total_seconds() > minutes * 60


def snapshots() -> list[dict]:
    """Retourne l'affluence la plus récente, fusionnée avec les agences connues."""
    latest = _latest_by_agency()
    result = []
    for agency in agencies():
        key = normalize(agency.name.replace("Agence ", ""))
        snapshot = latest.get(key) or latest.get(normalize(agency.city))
        if snapshot:
            result.append(
                {
                    **snapshot,
                    "name": agency.name,
                    "city": agency.city,
                    "level": _level(snapshot),
                    "stale": _is_stale(snapshot["heure"]),
                }
            )
        else:
            result.append(
                {
                    "agency": agency.name,
                    "name": agency.name,
                    "city": agency.city,
                    "heure": "",
                    "visibles": 0,
                    "entrees": 0,
                    "sorties": 0,
                    "alerte": False,
                    "level": "inconnu",
                    "stale": True,
                }
            )
    return result


def for_agency(agency_name: str) -> dict | None:
    key = normalize(agency_name.replace("Agence ", "")).strip()
    if not key:
        return None
    for snapshot in snapshots():
        if key in normalize(snapshot["name"]) or key == normalize(snapshot.get("city", "")):
            return snapshot
    return None


def describe(snapshot: dict | None) -> str:
    """Phrase courte utilisable par l'assistant vocal."""
    if not snapshot or snapshot["level"] == "inconnu":
        return ""
    prefix = "D'après la dernière mesure disponible, " if snapshot.get("stale") else ""
    subject = "l'agence" if prefix else "L'agence"
    if snapshot["alerte"]:
        return (
            f"{prefix}{subject} est actuellement très fréquentée : {snapshot['visibles']} personnes "
            "sont présentes et la zone d'attente est en alerte."
        )
    if snapshot["level"] == "forte":
        return (
            f"{prefix}{subject} est actuellement fréquentée : "
            f"{snapshot['visibles']} personnes sont présentes."
        )
    if snapshot["level"] == "moderee":
        pronoun = "il" if prefix else "Il"
        return f"{prefix}{pronoun} y a actuellement {snapshot['visibles']} personnes dans l'agence."
    return (
        f"{prefix}{subject} est calme en ce moment, avec "
        f"{snapshot['visibles']} personne(s) présente(s)."
    )
