# Assistant vocal bancaire

Prototype Vue 3 et FastAPI d’un assistant vocal en français. Les réponses bancaires, agences et opérations sont fictives ; le prototype ne peut effectuer aucune opération réelle.

## Démarrage

Prérequis : Python 3.10+, Node.js 22+, Ollama et un modèle compatible, par exemple `gemma:2b`.

1. Installer les dépendances Python depuis la racine du dépôt :

	```sh
	python -m pip install -r requirements.txt
	```

2. Démarrer Ollama et télécharger le modèle :

	```sh
	ollama pull gemma:2b
	ollama serve
	```

3. Démarrer l’API depuis la racine :

	```sh
	uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
	```

4. Dans un autre terminal, démarrer Vue :

	```sh
	cd frontend/kwaga
	npm install
	VITE_API_URL=http://192.168.55.1:8000 npm run dev -- --host 0.0.0.0
	```

	Remplacez l’adresse par celle de votre backend. Pour un accès LAN, l’API doit être joignable depuis le navigateur.

Le microphone exige un contexte sécurisé dans le navigateur : utilisez `localhost` ou servez le frontend en HTTPS sur le réseau local. Le modèle Whisper `tiny` est téléchargé au premier appel. `WHISPER_MODEL`, `WHISPER_DEVICE` et `WHISPER_COMPUTE_TYPE` permettent de configurer son exécution ; `OLLAMA_BASE_URL` et `OLLAMA_MODEL` configurent Ollama.

## API et limites

- `GET /health` vérifie que l’API est démarrée.
- `POST /api/voice-chat` accepte un fichier audio multipart nommé `file` et renvoie la transcription, le texte de réponse et l’audio MP3 encodé en base64.
- Les fichiers audio temporaires sont supprimés après traitement ; la taille d’un enregistrement est limitée à 15 Mo.
- Whisper et Ollama fonctionnent localement par défaut. gTTS nécessite Internet et transmet le texte de réponse à son service externe pour générer la voix. N’utilisez pas de données personnelles ou bancaires réelles.
- CORS est ouvert pour le développement uniquement. Restreignez les origines avant tout déploiement.

## Tests

Des tests de fumée sans dépendance lourde (pas de pytest requis) couvrent le
routage d'intentions et le parcours « carte bloquée » (identification client,
confirmation, déblocage, refus, escalade conseiller) :

```sh
cd backend
python tests/test_smoke.py
```

Ils isolent la base SQLite et le CSV d'affluence dans un dossier temporaire :
aucune donnée de démonstration n'est modifiée.