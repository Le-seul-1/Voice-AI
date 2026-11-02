"""API FastAPI du centre d'appels bancaire Banque Claire."""

from __future__ import annotations

import base64
import logging
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import affluence, store
from app.config import (
    ALLOWED_AUDIO_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    OLLAMA_MODEL,
    STATIC_DIR,
    TTS_ENGINE,
    WHISPER_MODEL,
)
from app.orchestrator import handle_chat
from app.services.llm import check_ollama
from app.services.stt import transcribe_audio
from app.services.tts import synthesize_speech

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init_db()
    logger.info("Base SQLite initialisée : %s", store.DB_PATH)
    logger.info("Modèle Ollama : %s · TTS : %s · Whisper : %s", OLLAMA_MODEL, TTS_ENGINE, WHISPER_MODEL)
    yield


app = FastAPI(
    title="Assistant call center Banque Claire",
    description="Prototype 100 % local : Gemma, RAG BM25, Whisper et SQLite.",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=80)
    customer_id: str | None = Field(default=None, max_length=20)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _new_session_id() -> str:
    return f"ses-{uuid.uuid4().hex[:12]}"


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "model": OLLAMA_MODEL,
        "tts_engine": TTS_ENGINE,
        "whisper_model": WHISPER_MODEL,
    }


@app.get("/api/health")
async def detailed_health():
    return {
        "status": "ok",
        "ollama": await check_ollama(),
        "model": OLLAMA_MODEL,
        "tts_engine": TTS_ENGINE,
        "whisper_model": WHISPER_MODEL,
        "static_frontend": (STATIC_DIR / "index.html").exists(),
    }


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Traite un message texte et retourne la réponse et ses métadonnées."""
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Le message ne peut pas être vide.")
    session_id = request.session_id or _new_session_id()
    try:
        result = await handle_chat(session_id, message, request.customer_id)
    except Exception as error:
        logger.exception("Échec du traitement du message")
        raise HTTPException(status_code=503, detail="L'assistant est momentanément indisponible.") from error

    payload = result.to_dict()
    payload["session_id"] = session_id
    # Champs optionnels uniformisés : le mode texte n'a ni transcription ni audio.
    payload.setdefault("transcription", None)
    payload.setdefault("audio_base64", "")
    payload.setdefault("audio_mime_type", "")
    return payload


@app.post("/api/voice-chat")
async def voice_chat(
    file: UploadFile = File(...),
    session_id: str | None = Form(default=None),
    customer_id: str | None = Form(default=None),
):
    """Transcrit un enregistrement, génère une réponse et éventuellement l'audio."""
    suffix = Path(file.filename or "audio.webm").suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Format audio non pris en charge.")

    audio_data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not audio_data:
        raise HTTPException(status_code=400, detail="Le fichier audio est vide.")
    if len(audio_data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="L'enregistrement dépasse la limite de 15 Mo.")

    session_id = session_id or _new_session_id()
    audio_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as audio_file:
            audio_file.write(audio_data)
            audio_path = audio_file.name

        transcript = await run_in_threadpool(transcribe_audio, audio_path)
        result = await handle_chat(session_id, transcript, customer_id)
        payload = result.to_dict()
        payload["session_id"] = session_id
        payload["transcription"] = transcript
        payload["response"] = result.answer

        audio_bytes, audio_mime = b"", ""
        if TTS_ENGINE not in {"browser", "none", ""}:
            try:
                audio_bytes, audio_mime = await run_in_threadpool(synthesize_speech, result.answer)
            except Exception:
                logger.exception("Échec de la synthèse vocale, le navigateur prendra le relais.")
        payload["audio_base64"] = base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else ""
        payload["audio_mime_type"] = audio_mime
        return payload
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ImportError as error:
        logger.exception("faster-whisper indisponible")
        raise HTTPException(
            status_code=503,
            detail="La transcription vocale n'est pas installée sur ce serveur. Utilisez le mode texte.",
        ) from error
    except Exception as error:
        logger.exception("Échec du traitement audio")
        raise HTTPException(
            status_code=503,
            detail="Le service vocal est indisponible. Vérifiez Whisper et Ollama.",
        ) from error
    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)


@app.post("/api/tts")
async def tts(request: TTSRequest):
    """Synthèse à la demande : cache Qwen3, Qwen3 en ligne, Piper, sinon navigateur."""
    try:
        audio, mime_type = await run_in_threadpool(synthesize_speech, request.text)
    except Exception as error:
        logger.exception("Échec de la synthèse vocale")
        raise HTTPException(status_code=503, detail="La synthèse vocale est indisponible.") from error
    return {
        "audio_base64": base64.b64encode(audio).decode("ascii") if audio else "",
        "audio_mime_type": mime_type,
        "engine": TTS_ENGINE,
    }


@app.get("/api/affluence")
async def agency_affluence():
    """Affluence locale des agences, alimentée par le CSV du module vidéo."""
    return {"agencies": affluence.snapshots()}


@app.get("/api/agent/conversations")
async def agent_conversations(limit: int = 50):
    return {"conversations": store.list_conversations(limit=max(1, min(limit, 200)))}


@app.get("/api/agent/conversations/{session_id}")
async def agent_conversation(session_id: str):
    conversation = store.get_conversation(session_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    return conversation


@app.get("/api/agent/tickets")
async def agent_tickets(status: str | None = None, limit: int = 100):
    return {"tickets": store.list_tickets(status=status, limit=max(1, min(limit, 500)))}


@app.post("/api/agent/tickets/{ticket_id}/resolve")
async def agent_resolve_ticket(ticket_id: str):
    resolved = store.resolve_ticket(ticket_id)
    if not resolved:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    return {"resolved": True, "ticket_id": ticket_id}


@app.get("/api/agent/stats")
async def agent_stats():
    return store.stats()


if STATIC_DIR.exists():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (STATIC_DIR / full_path).resolve()
        if full_path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
