"""Synthèse vocale locale avec cache et repli progressif.

Ordre de priorité en mode `auto` :
1. cache audio (voix Qwen3 pré-générée pour les phrases de démo) ;
2. service Qwen3-TTS local (HTTP) ;
3. Piper en local sur CPU ;
4. navigateur (`speechSynthesis`), si aucun moteur serveur n'est disponible.

Le cache est la clé pour garder la belle voix Qwen3 sans faire cohabiter Gemma 4
et Qwen3-TTS dans les 8 Go de mémoire unifiée de l'Orin Nano.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import httpx

from ..config import (
    PIPER_BINARY,
    PIPER_VOICE,
    QWEN3_TTS_TIMEOUT,
    QWEN3_TTS_URL,
    QWEN3_TTS_VOICE,
    TTS_CACHE_DIR,
    TTS_ENGINE,
)

logger = logging.getLogger(__name__)


def _cache_path(text: str) -> Path:
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    return Path(TTS_CACHE_DIR) / f"{digest}.wav"


def _cache_meta_path(text: str) -> Path:
    return _cache_path(text).with_suffix(".mime")


def _guess_mime(audio: bytes) -> str:
    if audio.startswith(b"RIFF"):
        return "audio/wav"
    if audio.startswith(b"ID3") or audio.startswith(b"\xff\xfb") or audio.startswith(b"\xff\xf3"):
        return "audio/mpeg"
    if audio.startswith(b"OggS"):
        return "audio/ogg"
    return "audio/wav"


def cached_audio(text: str) -> bytes | None:
    path = _cache_path(text)
    try:
        if path.exists() and path.stat().st_size > 0:
            return path.read_bytes()
    except OSError:
        logger.warning("Cache audio illisible : %s", path, exc_info=True)
    return None


def cached_mime_type(text: str) -> str:
    meta = _cache_meta_path(text)
    try:
        if meta.exists():
            value = meta.read_text(encoding="utf-8").strip()
            if value.startswith("audio/"):
                return value
    except OSError:
        logger.warning("Métadonnée de cache illisible : %s", meta, exc_info=True)
    audio = cached_audio(text)
    return _guess_mime(audio) if audio else "audio/wav"


def cache_audio(text: str, audio: bytes, mime_type: str = "audio/wav") -> Path | None:
    mime_type = (mime_type or "").split(";")[0].strip()
    if not audio or not mime_type.startswith("audio/"):
        return None
    path = _cache_path(text)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
        temp_path.write_bytes(audio)
        os.replace(temp_path, path)
        _cache_meta_path(text).write_text(mime_type, encoding="utf-8")
    except OSError:
        logger.warning("Écriture du cache audio impossible : %s", path, exc_info=True)
        return None
    return path


def _qwen3_tts(text: str) -> tuple[bytes, str] | None:
    if not QWEN3_TTS_URL:
        return None
    try:
        payload = {
            "text": text,
            "language": "french",
            "voice": QWEN3_TTS_VOICE,
            "voice_id": QWEN3_TTS_VOICE,
            "format": "wav",
        }
        endpoint = f"{QWEN3_TTS_URL}/tts" if not QWEN3_TTS_URL.endswith("/tts") else QWEN3_TTS_URL
        with httpx.Client(timeout=QWEN3_TTS_TIMEOUT) as client:
            response = client.post(endpoint, json=payload)
            response.raise_for_status()

        content_type = (response.headers.get("content-type") or "audio/wav").split(";")[0].strip().lower()
        if "json" in content_type:
            data = response.json()
            encoded = data.get("audio_base64") or data.get("audio")
            if not encoded:
                return None
            if encoded.startswith("data:") and "," in encoded:
                encoded = encoded.split(",", 1)[1]
            audio = base64.b64decode(encoded)
            if not audio:
                return None
            return audio, data.get("mime_type", "audio/wav")
        if not (content_type.startswith("audio/") or content_type == "application/octet-stream"):
            logger.warning("Qwen3-TTS a renvoyé un contenu inattendu : %s", content_type)
            return None
        if response.content:
            return response.content, content_type or "audio/wav"
    except Exception:
        logger.exception("Qwen3-TTS indisponible (%s)", QWEN3_TTS_URL)
    return None


def _piper_tts(text: str) -> tuple[bytes, str] | None:
    binary = shutil.which(PIPER_BINARY) if PIPER_BINARY else None
    if not binary or not PIPER_VOICE or not Path(PIPER_VOICE).exists():
        return None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
        audio_path = audio_file.name
    try:
        subprocess.run(
            [binary, "--model", PIPER_VOICE, "--output_file", audio_path],
            input=text.encode("utf-8"),
            check=True,
            capture_output=True,
            timeout=60,
        )
        audio = Path(audio_path).read_bytes()
        return (audio, "audio/wav") if audio else None
    except Exception:
        logger.exception("Piper indisponible")
        return None
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


def _gtts_tts(text: str) -> tuple[bytes, str] | None:
    try:
        from gtts import gTTS
    except ImportError:
        return None
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as audio_file:
        audio_path = audio_file.name
    try:
        gTTS(text=text, lang="fr", slow=False).save(audio_path)
        audio = Path(audio_path).read_bytes()
        return (audio, "audio/mpeg") if audio else None
    except Exception:
        logger.exception("gTTS indisponible")
        return None
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


def _espeak_tts(text: str) -> tuple[bytes, str] | None:
    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    if not binary:
        return None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
        audio_path = audio_file.name
    try:
        subprocess.run(
            [binary, "-v", "fr", "-s", "150", "-w", audio_path, text],
            check=True,
            capture_output=True,
            timeout=30,
        )
        audio = Path(audio_path).read_bytes()
        return (audio, "audio/wav") if audio else None
    except Exception:
        logger.exception("eSpeak indisponible")
        return None
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


def synthesize_speech(text: str) -> tuple[bytes, str]:
    """Retourne (audio, mime_type), ou (b'', '') pour laisser le navigateur parler."""
    text = (text or "").strip()
    if not text:
        return b"", ""

    cached = cached_audio(text)
    if cached:
        return cached, cached_mime_type(text)

    engine = TTS_ENGINE
    result: tuple[bytes, str] | None = None

    if engine == "auto":
        result = _qwen3_tts(text) or _piper_tts(text) or _espeak_tts(text)
    elif engine == "qwen3":
        result = _qwen3_tts(text) or _piper_tts(text)
    elif engine == "piper":
        result = _piper_tts(text)
    elif engine == "gtts":
        result = _gtts_tts(text)
    elif engine == "espeak":
        result = _espeak_tts(text)
    elif engine in {"browser", "none", ""}:
        return b"", ""

    if not result:
        return b"", ""

    audio, mime_type = result
    if audio:
        cache_audio(text, audio, mime_type)
    return audio, mime_type


def audio_mime_type() -> str:
    """Compatibilité avec l'ancienne API ; préférer le mime retourné par synthesize_speech."""
    if TTS_ENGINE in {"browser", "none", ""}:
        return ""
    return "audio/wav" if TTS_ENGINE in {"auto", "qwen3", "piper", "espeak"} else "audio/mpeg"
