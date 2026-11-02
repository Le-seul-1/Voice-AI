#!/usr/bin/env python3
"""Pré-génère les phrases de démonstration avec Qwen3-TTS.

Exemple :
    QWEN3_TTS_URL=http://127.0.0.1:8001 \
    python backend/scripts/pregen_voice.py --voice fr_female

Les WAV sont écrits dans backend/app/data/tts_cache. Le backend les sert ensuite
instantanément, sans charger Qwen3-TTS pendant l'appel.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Pré-génère la voix Qwen3 des phrases de démo.")
    parser.add_argument("--url", default=os.getenv("QWEN3_TTS_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--voice", default=os.getenv("QWEN3_TTS_VOICE", "fr_female"))
    parser.add_argument("--lines", default=str(ROOT / "app" / "data" / "voice_lines.json"))
    parser.add_argument("--force", action="store_true", help="Régénère même si le cache existe.")
    args = parser.parse_args()

    os.environ["QWEN3_TTS_URL"] = args.url.rstrip("/")
    os.environ["QWEN3_TTS_VOICE"] = args.voice
    os.environ["TTS_ENGINE"] = "qwen3"

    from app.services.tts import _qwen3_tts, cache_audio, cached_audio

    lines = json.loads(Path(args.lines).read_text(encoding="utf-8"))
    print(f"{len(lines)} phrases · Qwen3-TTS = {args.url} · voix = {args.voice}")

    generated = cached = failed = 0
    for index, line in enumerate(lines, start=1):
        if not args.force and cached_audio(line):
            cached += 1
            print(f"[{index:02d}] cache   {line[:70]}…")
            continue
        result = _qwen3_tts(line)
        if not result:
            failed += 1
            print(f"[{index:02d}] ÉCHEC   {line[:70]}…")
            continue
        audio, mime_type = result
        cache_audio(line, audio, mime_type)
        generated += 1
        print(f"[{index:02d}] OK      {len(audio) / 1024:.0f} Ko · {line[:60]}…")

    print(f"\nTerminé : {generated} générée(s), {cached} déjà en cache, {failed} échec(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
