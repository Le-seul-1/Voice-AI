"""Configuration partagée de l'assistant bancaire."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
KNOWLEDGE_DIR = Path(os.getenv("KNOWLEDGE_DIR", str(BASE_DIR / "knowledge")))
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "callcenter.db")))
AFFLUENCE_CSV = Path(os.getenv("AFFLUENCE_CSV", str(DATA_DIR / "affluence.csv")))
STATIC_DIR = Path(os.getenv("STATIC_DIR", str(BASE_DIR / "static")))

# La démo Jetson expose Ollama sur 11435 pour ne pas le confondre avec un
# service local standard. Surcharger OLLAMA_BASE_URL pour un Ollama sur 11434.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11435").rstrip("/")
# gemma3:1b est le modèle léger de la démo ; Gemma 4 reste utilisable via
# OLLAMA_MODEL (ex. gemma4:e2b-it-qat) sans changement de code.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:1b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "180"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))

# TTS : auto = cache Qwen3 -> Qwen3 en ligne -> Piper -> navigateur.
TTS_ENGINE = os.getenv("TTS_ENGINE", "auto").lower()
TTS_CACHE_DIR = Path(os.getenv("TTS_CACHE_DIR", str(DATA_DIR / "tts_cache")))
QWEN3_TTS_URL = os.getenv("QWEN3_TTS_URL", "").rstrip("/")
QWEN3_TTS_VOICE = os.getenv("QWEN3_TTS_VOICE", "fr_female")
QWEN3_TTS_TIMEOUT = float(os.getenv("QWEN3_TTS_TIMEOUT", "45"))
PIPER_BINARY = os.getenv("PIPER_BINARY", "piper")
PIPER_VOICE = os.getenv("PIPER_VOICE", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv(
    "WHISPER_COMPUTE_TYPE", "int8" if WHISPER_DEVICE == "cpu" else "float16"
)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_AUDIO_EXTENSIONS = {".webm", ".wav", ".mp3", ".m4a", ".mp4", ".ogg", ".flac"}
