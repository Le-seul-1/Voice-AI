"""Orchestrateur conversationnel du centre d'appels Banque Claire.

Le routage est déterministe ; Gemma ne rédige que les réponses documentaires,
toujours à partir des extraits de la base de connaissances locale.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import affluence, store
from .banking import Customer, find_agency, find_customer, format_agency, set_card_status
from .intents import classify_intent, extract_customer_id, extract_last4, is_affirmative, is_negative
from .rag import format_context, get_knowledge_base, normalize
from .services.llm import generate_answer

HOTLINE = "01 23 45 67 89"
OPPOSITION_ANSWER = (
    f"Pour une carte perdue, volée ou en cas de fraude, faites opposition immédiatement au {HOTLINE}, "
    "24 heures sur 24 et 7 jours sur 7, ou depuis l'application Claire & Moi. "
    "L'opposition est gratuite et définitive ; une nouvelle carte est expédiée sous 5 à 7 jours ouvrés."
)
NO_INFO_ANSWER = (
    "Je n'ai pas cette information dans la base Banque Claire. "
    "Je peux transmettre votre demande à un conseiller qui vous répondra rapidement."
)
HUMAN_TERMS = ("conseiller", "humain", "quelqu'un", "une personne", "personne reelle")
FOLLOWUP_TERMS = ("suivre", "suivi", "statut", "avancement", "ou en est", "etape")
TICKET_PATTERN = re.compile(r"\brec[\s-]?(\d{4})[\s-]?(\d{1,3})\b", re.IGNORECASE)

QUICK_REPLIES = {
    "compte": ["Documents pour ouvrir un compte", "Frais d'ouverture", "Parler à un conseiller"],
    "carte": ["Ma carte est bloquée", "Faire opposition", "Parler à un conseiller"],
    "credit": ["Simuler un crédit", "Documents pour un crédit", "Parler à un conseiller"],
    "agence": ["Agence à Paris", "Agence à Lyon", "Parler à un conseiller"],
    "reclamation": ["Suivre ma réclamation", "Parler à un conseiller"],
    "produit": ["Livret d'épargne", "Assurance habitation", "Parler à un conseiller"],
    "salutation": ["Ouvrir un compte", "Ma carte est bloquée", "Horaires d'agence"],
    "autre": ["Parler à un conseiller"],
}

GREETING = (
    "Bonjour ! Je suis l'assistant Banque Claire. Je peux vous renseigner sur l'ouverture de compte, "
    "les cartes bancaires, les crédits, les agences et les produits, ou enregistrer une réclamation. "
    "Que puis-je faire pour vous ?"
)


@dataclass
class SessionState:
    mode: str = "normal"  # normal | await_card_id | confirm_unblock
    customer_id: str | None = None
    card_case: str | None = None
    pending_last4: str | None = None


@dataclass
class ChatResult:
    answer: str
    intent: str = "autre"
    intent_label: str = "Demande générale"
    confidence: float = 0.0
    sources: list[dict] = field(default_factory=list)
    ticket: dict | None = None
    action: str | None = None
    customer: dict | None = None
    quick_replies: list[str] = field(default_factory=list)
    escalate: bool = False

    def to_dict(self) -> dict:
        payload = asdict(self)
        # Alias conservé pour les clients historiques qui lisent « response ».
        payload["response"] = self.answer
        return payload


_sessions: dict[str, SessionState] = {}


def _session(session_id: str) -> SessionState:
    return _sessions.setdefault(session_id, SessionState())


def _wants_human(text: str) -> bool:
    normalized = normalize(text)
    return any(term in normalized for term in HUMAN_TERMS)


def _is_other_intent(text: str) -> bool:
    """Vrai si le message quitte clairement le parcours carte en cours."""
    return classify_intent(text).name in {"agence", "compte", "credit", "produit", "reclamation"}


def _extract_ticket_id(text: str) -> str | None:
    match = TICKET_PATTERN.search(normalize(text))
    if not match:
        return None
    return f"REC-{match.group(1)}-{int(match.group(2)):03d}"


def _is_complaint_followup(text: str) -> bool:
    normalized = normalize(text)
    if _extract_ticket_id(text):
        return True
    if not any(term in normalized for term in ("reclamation", "dossier", "ticket")):
        return False
    return any(term in normalized for term in FOLLOWUP_TERMS)


def _customer_dict(customer: Customer) -> dict:
    return {
        "id": customer.id,
        "name": customer.name,
        "card_last4": customer.card_last4,
        "card_status": customer.card_status,
        "card_type": customer.card_type,
        "agency": customer.agency,
    }


def _detect_card_case(text: str) -> str | None:
    normalized = normalize(text)
    if re.search(r"\b(perdu|perdue|vole|volee|vol|opposition|fraude|suspecte?)\b", normalized):
        return "opposition"
    if "bloqu" in normalized:
        return "blocked"
    return None


def _sources(results) -> list[dict]:
    return [
        {"label": result.chunk.label, "title": result.chunk.title, "score": round(result.score, 2)}
        for result in results
    ]


def _ticket_summary(result: ChatResult) -> str:
    return result.answer[:280]


def _create_ticket(
    session_id: str,
    result: ChatResult,
    *,
    ticket_type: str,
    priority: str = "normale",
    summary: str | None = None,
) -> dict:
    existing = store.find_open_ticket(session_id, ticket_type)
    if existing:
        result.ticket = existing
        return existing
    ticket = store.create_ticket(
        session_id,
        ticket_type,
        (summary or _ticket_summary(result))[:280],
        priority=priority,
        suggested_response=result.answer,
    )
    result.ticket = ticket
    return ticket


def _start_card_flow(session: SessionState, session_id: str, message: str, result: ChatResult) -> ChatResult:
    case = _detect_card_case(message) or "blocked"
    session.card_case = case

    if case == "opposition":
        session.mode = "normal"
        result.answer = OPPOSITION_ANSWER
        result.intent = "carte"
        result.intent_label = "Carte bancaire · opposition"
        result.confidence = 0.95
        result.action = "opposition"
        result.quick_replies = ["Parler à un conseiller"]
        _create_ticket(session_id, result, ticket_type="carte", priority="haute")
        return result

    customer_id = extract_customer_id(message)
    last4 = extract_last4(message) if not customer_id else None
    customer = find_customer(customer_id, last4)
    if not customer and not customer_id and not last4 and session.customer_id:
        # Le client a déjà été identifié dans cette conversation.
        customer = find_customer(session.customer_id)

    if customer:
        return _evaluate_blocked_card(session, customer, result)

    session.mode = "await_card_id"
    result.intent = "carte"
    result.intent_label = "Carte bancaire · blocage"
    result.confidence = 0.9
    result.answer = (
        "Je peux vous aider à débloquer votre carte. Pouvez-vous me donner votre identifiant client "
        "(par exemple CL-1002) ou les quatre derniers chiffres de votre carte ?"
    )
    result.quick_replies = ["CL-1002", "Parler à un conseiller"]
    return result


def _evaluate_blocked_card(session: SessionState, customer: Customer, result: ChatResult) -> ChatResult:
    session.customer_id = customer.id
    result.customer = _customer_dict(customer)
    result.intent = "carte"
    result.confidence = 0.95
    result.action = "card_lookup"

    if customer.card_is_blocked:
        session.mode = "confirm_unblock"
        result.intent_label = "Carte bancaire · déblocage"
        result.answer = (
            f"J'ai trouvé votre carte {customer.card_type} terminant par {customer.card_last4} ; "
            "elle est actuellement bloquée. Souhaitez-vous que je la débloque maintenant ?"
        )
        result.quick_replies = ["Oui, débloquer ma carte", "Non, parler à un conseiller"]
        return result

    session.mode = "normal"
    result.intent_label = "Carte bancaire · statut"
    result.answer = (
        f"Votre carte {customer.card_type} terminant par {customer.card_last4} est déjà active. "
        "Si un paiement a été refusé, vérifiez le plafond dans l'application ou demandez un conseiller."
    )
    result.quick_replies = ["Voir mon plafond", "Parler à un conseiller"]
    return result


def _handle_card_identifier(session: SessionState, session_id: str, message: str, result: ChatResult) -> ChatResult:
    if _wants_human(message):
        session.mode = "normal"
        return _escalate(session_id, message, result)

    if _detect_card_case(message) == "opposition":
        return _start_card_flow(session, session_id, message, result)

    if is_negative(message):
        session.mode = "normal"
        result.intent = "carte"
        result.intent_label = "Carte bancaire · blocage annulé"
        result.answer = "Très bien, j'annule la demande de déblocage. Votre carte reste inchangée."
        result.quick_replies = ["Parler à un conseiller"]
        return result

    # Extraire l'identifiant client ou le last4 avant les yes/non,
    # pour que "Oui CL-1002" déclenche la recherche client.
    customer_id = extract_customer_id(message)
    last4 = extract_last4(message) if not customer_id else None
    customer = find_customer(customer_id, last4)
    if not customer and not customer_id and not last4 and session.customer_id:
        customer = find_customer(session.customer_id)
    if customer:
        return _evaluate_blocked_card(session, customer, result)

    if is_affirmative(message):
        result.intent = "carte"
        result.intent_label = "Carte bancaire · blocage"
        result.answer = (
            "D'accord. Pouvez-vous me donner votre identifiant client (par exemple CL-1002) "
            "ou les quatre derniers chiffres de votre carte ?"
        )
        result.quick_replies = ["CL-1002", "Parler à un conseiller"]
        return result

    if classify_intent(message).name == "salutation" and len(normalize(message).split()) <= 3:
        result.intent = "carte"
        result.intent_label = "Carte bancaire · blocage"
        result.answer = (
            "Bonjour ! Pour débloquer votre carte, pouvez-vous me donner votre identifiant client "
            "(par exemple CL-1002) ou les quatre derniers chiffres de votre carte ?"
        )
        result.quick_replies = ["CL-1002", "Parler à un conseiller"]
        return result

    # Aucun identifiant reconnu : on relance la demande au lieu de laisser
    # la fonction retourner None (qui faisait planter _finalize en aval).
    result.intent = "carte"
    result.intent_label = "Carte bancaire · blocage"
    result.answer = (
        "Je n'ai pas reconnu d'identifiant. Donnez-moi votre identifiant client "
        "(par exemple CL-1002) ou les quatre derniers chiffres de votre carte, "
        "ou demandez à parler à un conseiller."
    )
    result.quick_replies = ["CL-1002", "Parler à un conseiller"]
    return result


def _handle_unblock_confirmation(session: SessionState, session_id: str, message: str, result: ChatResult) -> ChatResult:
    if _wants_human(message):
        session.mode = "normal"
        result.intent = "carte"
        return _escalate(session_id, message, result)

    if _detect_card_case(message) == "opposition":
        return _start_card_flow(session, session_id, message, result)

    customer = find_customer(session.customer_id)
    if not customer:
        session.mode = "normal"
        return _escalate(session_id, message, result)

    result.intent = "carte"
    result.customer = _customer_dict(customer)

    if is_negative(message):
        session.mode = "normal"
        result.intent_label = "Carte bancaire · déblocage annulé"
        result.action = "card_unblock_cancelled"
        result.answer = (
            "Très bien, je ne modifie rien. Votre carte reste bloquée. "
            "Je peux vous mettre en relation avec un conseiller si vous le souhaitez."
        )
        result.quick_replies = ["Parler à un conseiller"]
        return result

    if not is_affirmative(message):
        result.intent_label = "Carte bancaire · confirmation"
        result.answer = "Souhaitez-vous que je débloque votre carte maintenant ? Répondez par oui ou non."
        result.quick_replies = ["Oui, débloquer ma carte", "Non, parler à un conseiller"]
        return result

    set_card_status(customer, "active")
    session.mode = "normal"
    store.update_conversation(session_id, status="bot")
    result.intent_label = "Carte bancaire · carte débloquée"
    result.action = "card_unblocked"
    result.customer = _customer_dict(customer)
    result.answer = (
        f"C'est fait : votre carte {customer.card_type} terminant par {customer.card_last4} est de nouveau active. "
        "Vous pouvez l'utiliser immédiatement ; en cas de nouveau refus, contactez un conseiller."
    )
    result.quick_replies = ["Parler à un conseiller"]
    return result


def _escalate(session_id: str, message: str, result: ChatResult) -> ChatResult:
    result.intent = "conseiller"
    result.intent_label = "Transfert conseiller"
    result.escalate = True
    result.action = "escalate"
    result.answer = "Demande de transfert à un conseiller."
    store.update_conversation(session_id, status="escalated")
    ticket = _create_ticket(
        session_id, result, ticket_type="conseiller", priority="haute", summary=message
    )
    ticket_id = ticket.get("id", "—")
    result.answer = (
        f"Je transmets votre demande à un conseiller. Votre ticket {ticket_id} est ouvert ; "
        "vous serez contacté dans les meilleurs délais."
    )
    result.quick_replies = []
    return result


async def _documentary_answer(session_id: str, message: str, result: ChatResult, history: list[dict]) -> ChatResult:
    results = get_knowledge_base().search(message, limit=3)
    if not results:
        # Sans extrait pertinent, on préfère une réponse déterministe au risque
        # que le petit modèle réponde depuis ses connaissances générales.
        result.answer = NO_INFO_ANSWER
        result.action = "fallback"
        result.quick_replies = ["Parler à un conseiller"]
        return result
    context = format_context(results)
    answer = await generate_answer(message, context, history)
    result.answer = answer
    result.action = "rag_answer"
    result.sources = _sources(results)
    return result


async def handle_chat(session_id: str, message: str, customer_id: str | None = None) -> ChatResult:
    """Traite un tour de parole et retourne la réponse et ses métadonnées."""
    message = re.sub(r"\s+", " ", message).strip()
    store.ensure_conversation(session_id)
    store.append_message(session_id, "user", message)
    conversation = store.get_conversation(session_id) or {}
    history = (conversation.get("transcript") or [])[:-1]

    session = _session(session_id)
    if customer_id and not session.customer_id:
        session.customer_id = customer_id

    result = ChatResult(answer="")

    if session.mode == "await_card_id":
        # Un client peut changer d'avis ou poser une autre question en cours de
        # parcours : on ne le laisse pas bloqué sur la demande d'identifiant.
        if _is_other_intent(message):
            session.mode = "normal"
        else:
            result = _handle_card_identifier(session, session_id, message, result)
            return _finalize(session_id, result)

    if session.mode == "confirm_unblock":
        if _is_other_intent(message):
            session.mode = "normal"
        else:
            result = _handle_unblock_confirmation(session, session_id, message, result)
            return _finalize(session_id, result)

    ticket_id = _extract_ticket_id(message)
    if ticket_id:
        return _finalize(session_id, _complaint_tracking(session_id, result, ticket_id))

    intent = classify_intent(message)
    result.intent = intent.name
    result.intent_label = intent.label
    result.confidence = round(intent.confidence, 2)
    result.quick_replies = QUICK_REPLIES.get(intent.name, QUICK_REPLIES["autre"])

    if _wants_human(message):
        return _finalize(session_id, _escalate(session_id, message, result))

    if intent.name == "salutation":
        customer = find_customer(session.customer_id)
        greeting = f"Bonjour {customer.first_name} ! " if customer else "Bonjour ! "
        result.answer = greeting + GREETING.split("Bonjour ! ", 1)[-1]
        result.intent_label = "Salutation"
        result.action = "greeting"
        return _finalize(session_id, result)

    if intent.name == "carte":
        case = _detect_card_case(message)
        if case:
            return _finalize(session_id, _start_card_flow(session, session_id, message, result))

    if intent.name == "reclamation":
        if _is_complaint_followup(message):
            return _finalize(session_id, _complaint_tracking(session_id, result))
        return _finalize(session_id, await _complaint_answer(session_id, message, result, history))

    if intent.name == "agence":
        agency = find_agency(message)
        if agency:
            snapshot = affluence.for_agency(agency.name)
            live = affluence.describe(snapshot)
            if snapshot and snapshot.get("stale"):
                advice = (
                    "Les données d'affluence ne sont pas à jour ; je vous conseille de confirmer "
                    "par téléphone avant de vous déplacer."
                )
            elif snapshot and snapshot["level"] in {"forte", "moderee"}:
                advice = "Je vous conseille de venir en dehors du pic ou de prendre rendez-vous."
            else:
                advice = "L'agence est ouverte sans rendez-vous pour les opérations courantes."
            result.answer = f"{format_agency(agency)} {live} {advice}".strip()
            result.action = "agency_info"
            result.sources = [{"label": "Agences", "title": agency.name, "score": 1.0}]
            if snapshot and snapshot["level"] != "inconnu":
                result.sources.append(
                    {"label": "Affluence", "title": f"{snapshot['visibles']} personne(s)", "score": 1.0}
                )
            result.quick_replies = ["Prendre rendez-vous", "Parler à un conseiller"]
            return _finalize(session_id, result)

    return _finalize(session_id, await _documentary_answer(session_id, message, result, history))


def _complaint_tracking(session_id: str, result: ChatResult, ticket_id: str | None = None) -> ChatResult:
    """Répond à une demande de suivi sans créer un nouveau ticket."""
    result.intent = "reclamation"
    result.intent_label = "Réclamation · suivi"
    result.action = "ticket_tracking"
    result.quick_replies = ["Parler à un conseiller"]

    ticket = store.get_ticket(ticket_id) if ticket_id else None
    if ticket is None and ticket_id is None:
        conversation = store.get_conversation(session_id) or {}
        candidate = conversation.get("ticket")
        if candidate and candidate.get("type") == "reclamation":
            ticket = candidate

    if not ticket:
        if ticket_id:
            result.answer = (
                f"Je ne trouve pas le ticket {ticket_id}. Vérifiez le numéro "
                "ou indiquez-le au format REC-2026-001."
            )
        else:
            result.answer = (
                "Pour suivre votre réclamation, indiquez son numéro de ticket "
                "(par exemple REC-2026-001)."
            )
        return result

    result.ticket = ticket
    created = (ticket.get("created_at") or "").replace("T", " ")[:16]
    date_hint = f" (déposée le {created})" if created else ""
    if ticket.get("status") == "resolu":
        result.answer = (
            f"Votre réclamation {ticket['id']} est résolue{date_hint}. "
            "Si vous avez besoin d'une précision, je peux vous mettre en relation avec un conseiller."
        )
    else:
        result.answer = (
            f"Votre réclamation {ticket['id']} est en cours de traitement{date_hint}. "
            "Un conseiller suit votre dossier et vous recevrez une réponse sous 10 jours ouvrés."
        )
    result.sources = [{"label": "Réclamations", "title": "Suivi de dossier", "score": 1.0}]
    return result


async def _complaint_answer(session_id: str, message: str, result: ChatResult, history: list[dict]) -> ChatResult:
    result.intent = "reclamation"
    result.intent_label = "Réclamation"
    result.action = "ticket_created"
    results = get_knowledge_base().search(message, limit=2)
    if results:
        context = format_context(results)
        result.answer = await generate_answer(message, context, history)
        result.sources = _sources(results)
    else:
        result.answer = NO_INFO_ANSWER
    _create_ticket(session_id, result, ticket_type="reclamation", priority="normale", summary=message)
    ticket_id = result.ticket["id"] if result.ticket else "—"
    result.answer = (
        f"Votre réclamation est suivie sous le numéro {ticket_id}. "
        f"{result.answer} Un conseiller suit votre dossier et vous recevrez une réponse sous 10 jours ouvrés."
    )
    result.quick_replies = ["Suivre ma réclamation", "Parler à un conseiller"]
    return result


def _finalize(session_id: str, result: ChatResult) -> ChatResult:
    if not result.answer.strip():
        result.answer = NO_INFO_ANSWER
    store.append_message(session_id, "assistant", result.answer)
    store.update_conversation(
        session_id,
        intent=result.intent,
        summary=result.answer[:280],
    )
    return result
