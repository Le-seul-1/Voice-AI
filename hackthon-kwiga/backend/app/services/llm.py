"""Génération de réponses bancaires avec Ollama, ancrée sur la base locale."""

from __future__ import annotations

import logging
import re

import httpx

from ..config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_PREDICT,
    OLLAMA_TEMPERATURE,
    OLLAMA_TIMEOUT,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Tu es l'assistant téléphonique de Banque Claire, une banque fictive. "
    "Tu réponds en français, avec un ton professionnel, chaleureux et direct. "
    "Réponds en 2 ou 3 phrases maximum, car ta réponse est lue à voix haute. "
    "Utilise uniquement les informations du CONTEXTE fourni. "
    "Si le contexte ne contient pas la réponse, dis-le clairement et propose de transférer à un conseiller. "
    "N'invente jamais de tarif, de délai, de numéro ou de condition. "
    "Ne demande jamais de code secret, de mot de passe ni de numéro de carte complet. "
    "Ne dis pas que tu es une intelligence artificielle ; tu es l'assistant Banque Claire."
)


def _clean(answer: str) -> str:
    answer = answer.strip()
    answer = re.sub(r"^```.*?\n|```$", "", answer, flags=re.MULTILINE)
    answer = re.sub(r"\*\*(.+?)\*\*", r"\1", answer)
    answer = re.sub(r"^#+\s*", "", answer, flags=re.MULTILINE)
    answer = re.sub(r"\s+", " ", answer).strip()
    return answer


def extractive_fallback(context: str) -> str:
    """Réponse de secours si Ollama est indisponible : extrait du contexte."""
    no_info = (
        "Je n'ai pas cette information sous la main. Je peux transmettre votre demande "
        "à un conseiller qui vous répondra rapidement."
    )
    if not context:
        return no_info
    text = re.sub(r"^\[\d+\].*$", "", context, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    selected = " ".join(sentences[:2]).strip()
    if len(selected) > 420:
        selected = selected[:417].rsplit(" ", 1)[0] + "…"
    return selected or text[:400] or no_info


async def generate_answer(
    question: str,
    context: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Interroge Gemma avec le contexte RAG et un court historique."""
    if not context.strip():
        # Sans contexte, le petit modèle est trop susceptible d'inventer une
        # réponse bancaire : on renvoie tout de suite le texte de secours.
        return extractive_fallback("")

    messages: list[dict[str, str]] = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nCONTEXTE :\n{context}"}
    ]
    for turn in (history or [])[-4:]:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
        if role in {"user", "assistant"} and text:
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": question})

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": messages,
        "options": {
            "temperature": OLLAMA_TEMPERATURE,
            "num_ctx": OLLAMA_NUM_CTX,
            "num_predict": OLLAMA_NUM_PREDICT,
        },
    }

    try:
        timeout = httpx.Timeout(OLLAMA_TIMEOUT, connect=min(10.0, OLLAMA_TIMEOUT))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
        answer = _clean(response.json().get("message", {}).get("content", ""))
        if answer:
            return answer
        logger.warning("Ollama a renvoyé une réponse vide, utilisation du fallback.")
    except Exception as error:
        logger.warning("Ollama indisponible (%s) : %s", OLLAMA_MODEL, error)

    return extractive_fallback(context)


async def generate_response(text: str) -> str:
    """Compatibilité avec l'ancien point d'entrée (sans RAG)."""
    return await generate_answer(text, context="")


async def check_ollama() -> dict:
    """Vérifie la disponibilité d'Ollama et du modèle configuré."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            response.raise_for_status()
        models = [model.get("name", "") for model in response.json().get("models", [])]
        available = any(name == OLLAMA_MODEL or name.startswith(f"{OLLAMA_MODEL}:") for name in models)
        return {"reachable": True, "model": OLLAMA_MODEL, "model_available": available}
    except Exception as error:
        return {"reachable": False, "model": OLLAMA_MODEL, "error": str(error)}
