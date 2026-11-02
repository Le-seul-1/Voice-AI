"""Classification d'intention par règles, rapide et déterministe.

Le petit modèle local reste ainsi réservé à la rédaction des réponses : le
routage des six familles de demandes ne dépend pas de sa stabilité.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .rag import normalize

INTENT_LABELS = {
    "compte": "Ouverture de compte",
    "carte": "Carte bancaire",
    "credit": "Crédit",
    "agence": "Agence",
    "reclamation": "Réclamation",
    "produit": "Produits et services",
    "salutation": "Salutation",
    "autre": "Demande générale",
}

# Les expressions multi-mots pèsent plus lourd qu'un mot isolé.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "compte": (
        "compte", "ouvrir un compte", "ouvrir compte", "ouverture de compte",
        "ouverture d'un compte", "creer un compte", "créer un compte", "compte bancaire",
        "compte courant", "compte joint", "compte jeune", "compte professionnel",
        "cloture", "clôture", "fermer mon compte", "fermeture de compte",
        "procuration", "piece d'identite", "pièce d'identité", "justificatif de domicile",
        "justificatif de revenus", "documents", "frais d'ouverture", "premier depot",
    ),
    "carte": (
        "carte", "carte bancaire", "carte bloquee", "carte bloquée", "carte perdue",
        "carte volee", "carte volée", "carte de credit", "carte de crédit",
        "opposition", "debloquer", "débloquer", "deblocage", "déblocage",
        "code secret", "plafond", "visa", "carte visa", "renouveler ma carte",
        "commander une carte", "paiement refuse", "paiement refusé", "retrait",
        "perdu", "perdue", "perdu ma carte", "perdre ma carte", "j'ai perdu ma carte",
        "vole", "volee", "volée", "vol", "fraude", "suspect", "suspecte",
    ),
    "credit": (
        "credit", "crédit", "pret", "prêt", "immobilier", "consommation", "taux",
        "emprunt", "emprunter", "emprunte", "mensualite", "mensualité", "endettement",
        "apport", "remboursement anticipe", "remboursement anticipé", "financement",
        "simulation de credit", "simulation de crédit", "simuler un credit",
        "simuler un crédit",
    ),
    "agence": (
        "agence", "horaires", "horaire", "adresse", "ou se trouve", "où se trouve",
        "ou est", "où est", "rendez-vous", "rendez vous", "metro", "métro", "parking",
        "bellecour", "republique", "république", "prado", "lille", "paris", "lyon",
        "marseille", "contact", "contacter", "telephone", "téléphone", "coordonnees",
        "coordonnées", "service client", "joindre",
    ),
    "reclamation": (
        "reclamation", "réclamation", "plainte", "litige", "prelevement", "prélèvement",
        "remboursement", "contest", "fraude", "erreur", "mecontent", "mécontent",
        "satisfait", "probleme", "problème", "operation suspecte", "opération suspecte",
        "suivi de dossier",
    ),
    "produit": (
        "produit", "service", "epargne", "épargne", "livret", "assurance", "placement",
        "compte pro", "compte epargne", "compte épargne", "application", "virement",
        "rib", "banque", "services numeriques", "services numériques",
        "assurance habitation", "assurance auto", "taux du livret", "livret claire",
        "frais bancaires",
    ),
    "salutation": ("bonjour", "bonsoir", "salut", "hello", "coucou"),
}

CARD_BLOCK_TERMS = ("bloqu", "opposition", "perdu", "vol", "debloqu", "débloqu")
CARD_ORDER_TERMS = ("commander", "renouveler", "nouvelle carte", "reedition", "réédition")
CARD_LIMIT_TERMS = ("plafond", "paiement", "retrait", "etranger", "étranger")

# Les cartes non bancaires ne doivent pas déclencher le parcours carte.
NON_BANKING_CARD_TERMS = (
    "carte d'identite", "carte vitale", "carte grise", "carte cadeau", "carte sim",
)
BANKING_CARD_TERMS = (
    "bancaire", "bloqu", "perdu", "vole", "opposition", "paiement", "retrait",
    "plafond", "fraude", "visa", "mastercard", "debit",
)

# En cas d'égalité, la famille la plus spécifique passe devant.
INTENT_PRIORITY = (
    "reclamation", "carte", "compte", "credit", "agence", "produit", "salutation", "autre",
)


@dataclass(frozen=True)
class Intent:
    name: str
    confidence: float
    sub_intent: str | None = None
    matched: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return INTENT_LABELS.get(self.name, self.name)


def _keyword_weight(keyword: str) -> float:
    return 2.0 if " " in keyword else 1.0


@lru_cache(maxsize=512)
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Motif à frontières de mots, pour éviter « vol » dans « volontiers »."""
    normalized_keyword = normalize(keyword).strip()
    escaped = re.escape(normalized_keyword).replace(r"\ ", r"\s+").replace(" ", r"\s+")
    return re.compile(rf"(?<!\w){escaped}(?!\w)")


def _keyword_matches(keyword: str, normalized_text: str) -> bool:
    normalized_keyword = normalize(keyword).strip()
    return bool(normalized_keyword and _keyword_pattern(keyword).search(normalized_text))


def classify_intent(text: str) -> Intent:
    normalized = normalize(text)
    if not normalized.strip():
        return Intent("autre", 0.0)

    scores: dict[str, float] = {}
    matched_terms: dict[str, list[str]] = {}
    for intent, keywords in KEYWORDS.items():
        for keyword in keywords:
            if _keyword_matches(keyword, normalized):
                scores[intent] = scores.get(intent, 0.0) + _keyword_weight(keyword)
                matched_terms.setdefault(intent, []).append(keyword)

    # « carte d'identité » dans une demande d'ouverture de compte ne doit pas
    # être confondu avec une demande liée à la carte bancaire.
    # normalize() enlève les accents (identité → identite) etReplace les guillemets.
    # On vérifie les deux formes possibles dans le texte normalisé.
    has_id_card = ("carte d'identite" in normalized or
                   "carte didentite" in normalized or
                   ("carte" in normalized and "identite" in normalized.split()))
    has_account = "compte" in normalized
    if has_id_card and has_account:
        scores.pop("carte", None)
        scores["compte"] = scores.get("compte", 0.0) + 2.0
    elif any(term in normalized for term in NON_BANKING_CARD_TERMS):
        if not any(term in normalized for term in BANKING_CARD_TERMS):
            scores.pop("carte", None)

    if not scores:
        return Intent("autre", 0.0)

    best_intent = max(
        scores,
        key=lambda name: (scores[name], -INTENT_PRIORITY.index(name)),
    )
    best_score = scores[best_intent]
    confidence = min(1.0, best_score / 4.0)
    sub_intent = None
    if best_intent == "carte":
        if any(term in normalized for term in CARD_BLOCK_TERMS):
            sub_intent = "blocage"
        elif any(term in normalized for term in CARD_ORDER_TERMS):
            sub_intent = "commande"
        elif any(term in normalized for term in CARD_LIMIT_TERMS):
            sub_intent = "plafond"

    return Intent(best_intent, confidence, sub_intent, tuple(matched_terms.get(best_intent, ())))


def is_affirmative(text: str) -> bool:
    normalized = normalize(text).strip()
    return bool(
        re.search(
            r"\b(oui|ouais|ok|d'accord|accord|confirme|volontiers|allez[- ]y|"
            r"yes|yep|bien sur|je veux bien)\b",
            normalized,
        )
    )


def is_negative(text: str) -> bool:
    normalized = normalize(text).strip()
    return bool(
        re.search(
            r"\b(non|no|nope|pas maintenant|annule|annuler|laisse tomber|pas besoin|"
            r"pas du tout|je ne veux pas|je ne souhaite pas)\b",
            normalized,
        )
    )


def extract_customer_id(text: str) -> str | None:
    match = re.search(r"\bcl[\s-]?(\d{4})\b", normalize(text), re.IGNORECASE)
    return f"CL-{match.group(1)}" if match else None


def extract_last4(text: str) -> str | None:
    """Extrait les quatre derniers chiffres d'une carte, sans code secret."""
    normalized = normalize(text)
    matches = list(re.finditer(r"(?<!\d)(\d{4})(?!\d)", normalized))
    for match in reversed(matches):
        before = normalized[max(0, match.start() - 20):match.start()]
        if re.search(r"\b(code|pin|mot de passe|secret)\b", before) and not re.search(
            r"\b(carte|termine|finit|derniers?|chiffres?)\b", before
        ):
            # Ne jamais prendre un code secret pour un numéro de carte.
            continue
        return match.group(1)
    return None
