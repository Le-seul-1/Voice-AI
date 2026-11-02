"""Transcription locale avec faster-whisper (CPU, quantization int8)."""

from __future__ import annotations

import os
from functools import lru_cache

from ..config import WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL


@lru_cache(maxsize=1)
def _get_model():
    from faster_whisper import WhisperModel

    download_root = os.getenv("WHISPER_DOWNLOAD_ROOT") or None
    return WhisperModel(
        WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
        download_root=download_root,
        cpu_threads=int(os.getenv("WHISPER_CPU_THREADS", "4")),
    )


def transcribe_audio(audio_path: str) -> str:
    """Transcrit un fichier audio en français et retourne le texte reconnu."""
    segments, _ = _get_model().transcribe(
        audio_path,
        language="fr",
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    transcript = " ".join(segment.text.strip() for segment in segments).strip()
    if not transcript:
        raise ValueError("Aucune parole n'a été détectée dans l'enregistrement.")
    return transcript
