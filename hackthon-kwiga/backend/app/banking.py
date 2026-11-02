"""Données bancaires fictives et opérations de démonstration.

Les données de référence sont dans des fichiers CSV faciles à éditer. Les
statuts de carte sont modifiés en mémoire pour la durée de la démonstration.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR
from .rag import normalize

logger = logging.getLogger(__name__)


@dataclass
class Customer:
    id: str
    name: str
    card_last4: str
    card_status: str
    card_type: str
    agency: str
    phone: str

    @property
    def first_name(self) -> str:
        return self.name.split(" ", 1)[0]

    @property
    def card_is_blocked(self) -> bool:
        return self.card_status == "blocked"


@dataclass(frozen=True)
class Agency:
    name: str
    city: str
    address: str
    hours: str
    phone: str
    access: str


def _load_rows(filename: str) -> list[dict]:
    """Lit un CSV (source principale) avec repli JSON pour compatibilité."""
    csv_path = Path(DATA_DIR) / filename
    json_path = csv_path.with_suffix(".json")
    if csv_path.exists():
        try:
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            if rows:
                return rows
            logger.warning("CSV vide, repli sur le JSON : %s", csv_path)
        except (OSError, UnicodeDecodeError, csv.Error):
            logger.warning("CSV illisible, repli sur le JSON : %s", csv_path, exc_info=True)
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            logger.warning("JSON de données ignoré (liste attendue) : %s", json_path)
        except (OSError, json.JSONDecodeError):
            logger.warning("JSON de données illisible : %s", json_path, exc_info=True)
    return []


def _text(row: dict, key: str) -> str:
    value = row.get(key)
    return str(value).strip() if value is not None else ""


def _normalize_card_status(value: str) -> str:
    normalized = normalize(value)
    if normalized in {"blocked", "bloque", "bloquee", "inactive", "inactif"}:
        return "blocked"
    if normalized in {"active", "actif", "actived"}:
        return "active"
    logger.warning("Statut de carte inconnu « %s », valeur active par défaut.", value)
    return "active"


@lru_cache(maxsize=1)
def _customers() -> dict[str, Customer]:
    customers = {}
    for row in _load_rows("customers.csv"):
        customer_id = _text(row, "id")
        card_last4 = _text(row, "card_last4")
        if not customer_id or not card_last4:
            logger.warning("Ligne client incomplète ignorée : %s", row)
            continue
        customer = Customer(
            id=customer_id,
            name=_text(row, "name"),
            card_last4=card_last4[-4:],
            card_status=_normalize_card_status(_text(row, "card_status")),
            card_type=_text(row, "card_type"),
            agency=_text(row, "agency"),
            phone=_text(row, "phone"),
        )
        customers[customer.id.upper()] = customer
    return customers


@lru_cache(maxsize=1)
def agencies() -> tuple[Agency, ...]:
    result: list[Agency] = []
    for row in _load_rows("agencies.csv"):
        name = _text(row, "name")
        city = _text(row, "city")
        if not name or not city:
            logger.warning("Ligne agence incomplète ignorée : %s", row)
            continue
        result.append(
            Agency(
                name=name,
                city=city,
                address=_text(row, "address"),
                hours=_text(row, "hours"),
                phone=_text(row, "phone"),
                access=_text(row, "access"),
            )
        )
    return tuple(result)


def _normalize_customer_id(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value).upper()
    match = re.fullmatch(r"CL-?(\d+)", cleaned)
    return f"CL-{match.group(1)}" if match else cleaned


def find_customer(customer_id: str | None = None, last4: str | None = None) -> Customer | None:
    if customer_id:
        customer = _customers().get(_normalize_customer_id(customer_id))
        if customer:
            return customer
    if last4:
        digits = "".join(char for char in last4 if char.isdigit())[-4:]
        if len(digits) == 4:
            for customer in _customers().values():
                if customer.card_last4 == digits:
                    return customer
    return None


def set_card_status(customer: Customer, status: str) -> Customer:
    """Change le statut de la carte pour la durée de la démonstration."""
    normalized = _normalize_card_status(status)
    customer.card_status = normalized
    return customer


def _contains_name(query: str, candidate: str) -> bool:
    normalized_candidate = normalize(candidate).strip()
    if not normalized_candidate:
        return False
    return bool(re.search(rf"(?<!\w){re.escape(normalized_candidate)}(?!\w)", query))


def find_agency(query: str) -> Agency | None:
    normalized = normalize(query)
    for agency in agencies():
        candidates = (agency.city, agency.name.replace("Agence ", ""))
        if any(_contains_name(normalized, candidate) for candidate in candidates):
            return agency
    return None


def customer_agency(customer: Customer) -> Agency | None:
    return find_agency(customer.agency)


def format_agency(agency: Agency) -> str:
    return (
        f"{agency.name}, {agency.address}. Horaires : {agency.hours}. "
        f"Téléphone : {agency.phone}."
    )
