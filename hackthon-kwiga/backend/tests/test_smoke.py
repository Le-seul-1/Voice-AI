#!/usr/bin/env python3
"""Tests de fumée sans dépendance lourde (ni pytest, ni réseau, ni LLM).

Objectif : pouvoir exécuter ces scénarios sur le Jetson pour vérifier que
l'orchestrateur ne plante pas, sans appeler Ollama / Whisper / Qwen3-TTS.

Lancement (depuis backend/) :
    python -m tests.test_smoke
ou directement :
    python tests/test_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

# Isole la base SQLite et le CSV d'affluence dans un dossier temporaire, pour
# ne jamais toucher aux données réelles de démo pendant les tests.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="callcenter-smoke-"))
os.environ.setdefault("DB_PATH", str(_TMP_DIR / "callcenter.db"))
os.environ.setdefault("AFFLUENCE_CSV", str(_TMP_DIR / "affluence.csv"))

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import affluence, store  # noqa: E402
from app.intents import classify_intent, extract_customer_id, extract_last4  # noqa: E402
from app.orchestrator import _extract_ticket_id, handle_chat  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def test_intents() -> None:
    cases = {
        "Je voudrais ouvrir un compte": "compte",
        "Ma carte bancaire est bloquée": "carte",
        "J'ai perdu ma carte": "carte",
        "Je voudrais simuler un crédit immobilier": "credit",
        "Quels sont les horaires de l'agence République": "agence",
        "Je veux faire une réclamation": "reclamation",
        "Quel est le taux du livret": "produit",
        "Bonjour": "salutation",
        "Peux-tu réciter un poème": "autre",
    }
    for text, expected in cases.items():
        intent = classify_intent(text)
        check(f"intent({text!r}) == {expected!r}", intent.name == expected, f"obtenu {intent.name!r}")

    # Carte d'identité ne doit pas déclencher le parcours carte bancaire.
    intent = classify_intent("J'ai besoin d'une carte d'identité pour ouvrir un compte")
    check("carte d'identité -> compte (pas carte bancaire)", intent.name == "compte", intent.name)

    check("extract_customer_id(CL-1002)", extract_customer_id("mon identifiant est CL-1002") == "CL-1002")
    check("extract_last4 ignore le code secret", extract_last4("mon code secret est 1234") is None)
    check(
        "extract_last4 trouve les 4 derniers chiffres de carte",
        extract_last4("ma carte se termine par 1234") == "1234",
    )
    check(
        "_extract_ticket_id reconnaît REC-2026-001",
        _extract_ticket_id("mon ticket est REC-2026-001") == "REC-2026-001",
    )


def test_card_flow() -> None:
    """Rejoue le scénario CL-1002 / 1234 (carte bloquée) de bout en bout."""
    session_id = f"smoke-{uuid.uuid4().hex[:8]}"

    r1 = asyncio.run(handle_chat(session_id, "Ma carte est bloquée"))
    check("étape 1 : demande d'identifiant", bool(r1.answer), r1.answer)
    check("étape 1 : intent carte", r1.intent == "carte", r1.intent)

    # Message hors-sujet pendant l'attente de l'identifiant : c'est le cas qui
    # provoquait un crash (fonction sans retour -> result=None -> _finalize
    # plantait sur result.answer.strip()).
    r2 = asyncio.run(handle_chat(session_id, "Quel temps fait-il aujourd'hui ?"))
    check("étape 2 : pas de crash sur message hors-sujet", r2 is not None)
    check("étape 2 : réponse non vide", bool(r2 and r2.answer.strip()), getattr(r2, "answer", None))

    r3 = asyncio.run(handle_chat(session_id, "CL-1002"))
    check("étape 3 : client trouvé", r3.customer is not None and r3.customer.get("id") == "CL-1002")
    check("étape 3 : carte bloquée détectée", "bloquée" in r3.answer.lower())

    r4 = asyncio.run(handle_chat(session_id, "Oui, débloquez-la"))
    check("étape 4 : carte débloquée", r4.action == "card_unblocked", r4.action)

    conversation = store.get_conversation(session_id)
    check("historique persisté en base", conversation is not None and len(conversation["transcript"]) >= 8)


def test_card_flow_refus() -> None:
    session_id = f"smoke-{uuid.uuid4().hex[:8]}"
    asyncio.run(handle_chat(session_id, "carte bloquée"))
    asyncio.run(handle_chat(session_id, "CL-1002"))
    refus = asyncio.run(handle_chat(session_id, "non merci"))
    check("refus de déblocage pris en compte", refus.action == "card_unblock_cancelled", refus.action)


def test_affluence_sans_fichier() -> None:
    # Le CSV temporaire n'existe pas encore : snapshots() ne doit pas planter.
    result = affluence.snapshots()
    check("affluence.snapshots() sans CSV ne plante pas", isinstance(result, list))
    check("agences connues malgré CSV absent", len(result) > 0, str(result))
    check("niveau 'inconnu' par défaut", all(item["level"] == "inconnu" for item in result))


def test_escalade() -> None:
    session_id = f"smoke-{uuid.uuid4().hex[:8]}"
    result = asyncio.run(handle_chat(session_id, "Je veux parler à un conseiller"))
    check("escalade crée un ticket", result.ticket is not None)
    check("escalade signalée", result.escalate is True)


def main() -> int:
    store.init_db()
    test_intents()
    test_card_flow()
    test_card_flow_refus()
    test_affluence_sans_fichier()
    test_escalade()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} test(s) en échec : {', '.join(FAILURES)}")
        return 1
    print("Tous les tests de fumée sont passés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
