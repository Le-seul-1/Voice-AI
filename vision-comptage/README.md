# Comptage de personnes (hackathon AI offline first)

Installation (avec internet, une seule fois) :

```bash
python3 -m venv --without-pip ~/venv-vision
pip --python ~/venv-vision/bin/python install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip --python ~/venv-vision/bin/python install ultralytics lap
```

Lancer :

```bash
~/venv-vision/bin/python test_comptage_v3.py
```

La source caméra se règle avec `CAMERA_SOURCE` (0, chemin de vidéo, ou
`http://IP:8080/video`) :

```bash
CAMERA_SOURCE=http://10.111.11.7:8080/video \
AGENCE=République \
AFFLUENCE_CSV=/home/admin-nano/callcenter/backend/app/data/affluence.csv \
~/venv-vision/bin/python test_comptage_v3.py
```

## Lien avec le call center

`test_comptage_v3.py` écrit toutes les 2 secondes une ligne dans `affluence.csv` :

```csv
heure,agence,visibles,entrees,sorties,alerte
2026-11-02T14:31:55,République,12,48,36,true
```

Le backend Banque Claire lit ce fichier via `GET /api/affluence` et l'utilise pour :

- orienter le client vers l'agence la moins fréquentée ;
- afficher l'affluence en direct sur le poste conseiller ;
- signaler une zone d'attente en alerte.

Variables utiles : `AGENCE`, `AFFLUENCE_CSV`, `INTERVALLE_AFFLUENCE` (secondes).
Le module `affluence_bridge.py` peut aussi être appelé seul pour tester :

```bash
python3 affluence_bridge.py
```
