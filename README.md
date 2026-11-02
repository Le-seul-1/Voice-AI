# voice-ai

Prototypes réalisés pour un hackathon bancaire : un assistant vocal de centre
d'appels et un module de comptage de personnes par caméra, reliés par un
simple fichier CSV d'affluence.

## Sous-projets

### [`hackthon-kwiga/`](hackthon-kwiga) — Assistant vocal bancaire « Banque Claire »

Prototype Vue 3 + FastAPI, 100 % francophone et conçu pour tourner en local
(offline-first) :

- **Backend** (`hackthon-kwiga/backend`) : FastAPI, routage d'intentions
  déterministe, RAG BM25 sur une base de connaissances Markdown, LLM local via
  Ollama (Gemma), transcription locale (faster-whisper) et synthèse vocale en
  cascade (cache → Qwen3-TTS → Piper → eSpeak → navigateur).
- **Frontend** (`hackthon-kwiga/frontend/kwaga`) : interface Vue 3 (Vite) pour
  parler ou écrire à l'assistant.

Voir [`hackthon-kwiga/README.md`](hackthon-kwiga/README.md) pour le démarrage
complet et [`hackthon-kwiga/backend/tests/test_smoke.py`](hackthon-kwiga/backend/tests/test_smoke.py)
pour les tests de fumée.

### [`vision-comptage/`](vision-comptage) — Comptage de personnes par caméra

Script de comptage basé sur YOLO11 (`ultralytics`) qui détecte les entrées et
sorties depuis un flux caméra et écrit l'affluence toutes les 2 secondes dans
un CSV partagé. Ce CSV est lu par le backend `hackthon-kwiga` (`GET
/api/affluence`) pour orienter les clients vers l'agence la moins fréquentée
et alerter le poste conseiller en cas d'affluence forte.

Voir [`vision-comptage/README.md`](vision-comptage/README.md).

## Avertissement

Ce sont des prototypes de démonstration : les données bancaires, les clients
et les agences sont fictifs. Aucune opération réelle n'est possible.
