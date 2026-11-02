"""Comptage de personnes, version 3 : ajoute une zone d'alerte et un journal CSV local.
Touches : q = quitter, r = remettre les compteurs à zéro."""
import csv
import os
import threading
import time
from datetime import datetime
import cv2
from ultralytics import YOLO

from affluence_bridge import write_snapshot

# --- Réglages à modifier ---
SOURCE = os.getenv("CAMERA_SOURCE", "http://192.168.3.103:8080/video")
AGENCE = os.getenv("AGENCE", "République")
AFFLUENCE_CSV = os.getenv("AFFLUENCE_CSV", "affluence.csv")
INTERVALLE_AFFLUENCE = float(os.getenv("INTERVALLE_AFFLUENCE", "2"))
MODELE = "yolo11n.pt"
TAILLE_ANALYSE = 416     # plus petit = plus rapide (essayez 320), moins précis
CONFIANCE = 0.3          # plus bas = plus de détections, mais plus de fausses alertes
LARGEUR_MAX = 640        # l'image est réduite à cette largeur avant analyse
MARGE = 25               # pixels de chaque côté de la ligne : évite les doubles comptages
ZONE = (0.65, 0.15, 0.98, 0.95)  # zone d'alerte (gauche, haut, droite, bas), en fraction de l'image
DELAI_ALERTE = 3.0       # secondes passées dans la zone avant le déclenchement de l'alerte
JOURNAL = "evenements.csv"
CAPTURES = True          # True : enregistre une image à chaque passage et alerte (False : aucune image)
DOSSIER_CAPTURES = "captures"
JOURS_CONSERVATION = 7   # les captures plus anciennes sont supprimées au démarrage


class Camera:
    """En direct (webcam, flux réseau), une tâche lit sans arrêt et ne garde que l'image
    la plus récente. Sans cela, les images s'accumulent et le retard grandit."""

    def __init__(self, source):
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise SystemExit("Source introuvable : vérifiez SOURCE")
        self.direct = isinstance(source, int) or str(source).startswith(("http", "rtsp"))
        self.actif = True
        self.derniere = None
        self.heure = 0.0
        self.deja_lue = None
        if self.direct:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            threading.Thread(target=self._boucle, daemon=True).start()

    def _boucle(self):
        while self.actif:
            ok, image = self.cap.read()
            if not ok:
                self.actif = False
                break
            self.heure = time.time()
            self.derniere = image

    def lire(self):
        """Renvoie (image, heure de capture), ou (None, 0) à la fin."""
        if not self.direct:  # fichier vidéo : on lit toutes les images dans l'ordre
            ok, image = self.cap.read()
            return (image, time.time()) if ok else (None, 0.0)
        while self.actif:
            image = self.derniere
            if image is not None and image is not self.deja_lue:
                self.deja_lue = image
                return image, self.heure
            time.sleep(0.005)
        return None, 0.0

    def fermer(self):
        self.actif = False
        self.cap.release()


# Journal local : chaque événement est écrit tout de suite dans un fichier CSV
nouveau = not os.path.exists(JOURNAL) or os.path.getsize(JOURNAL) == 0
fichier = open(JOURNAL, "a", newline="", encoding="utf-8")
journal = csv.writer(fichier)
if nouveau:
    journal.writerow(["heure", "evenement", "id", "capture"])

if CAPTURES:
    os.makedirs(DOSSIER_CAPTURES, exist_ok=True)
    limite = time.time() - JOURS_CONSERVATION * 86400
    for nom in os.listdir(DOSSIER_CAPTURES):  # suppression automatique des anciennes captures
        chemin = os.path.join(DOSSIER_CAPTURES, nom)
        if os.path.isfile(chemin) and os.path.getmtime(chemin) < limite:
            os.remove(chemin)


def noter(evenement, tid="", image=None):
    nom = ""
    if CAPTURES and image is not None:
        nom = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{evenement}_id{tid}.jpg"
        cv2.imwrite(os.path.join(DOSSIER_CAPTURES, nom), image)
    journal.writerow([datetime.now().isoformat(timespec="seconds"), evenement, tid, nom])
    fichier.flush()


model = YOLO(MODELE)  # se télécharge au premier lancement (internet requis)
camera = Camera(SOURCE)
noter("demarrage")
write_snapshot(0, 0, 0, False, agence=AGENCE, path=AFFLUENCE_CSV)

ligne_x = None
cote = {}        # identifiant -> dernier côté sûr de la ligne (-1 gauche, +1 droite)
dans_zone = {}   # identifiant -> [début, dernier vu, alerte déclenchée]
entrees = sorties = nb_alertes = 0
max_visibles = 0
durees, retards = [], []
derniere_affluence = 0.0

while True:
    image, heure_capture = camera.lire()
    if image is None:
        break
    if image.shape[1] > LARGEUR_MAX:
        hauteur = int(image.shape[0] * LARGEUR_MAX / image.shape[1])
        image = cv2.resize(image, (LARGEUR_MAX, hauteur))
    if ligne_x is None:
        h, w = image.shape[:2]
        ligne_x = w // 2
        zx1, zy1 = int(ZONE[0] * w), int(ZONE[1] * h)
        zx2, zy2 = int(ZONE[2] * w), int(ZONE[3] * h)

    maintenant = time.time()
    res = model.track(image, persist=True, classes=[0], imgsz=TAILLE_ANALYSE,
                      conf=CONFIANCE, verbose=False)[0]
    durees.append(time.time() - maintenant)

    visibles = len(res.boxes)  # personnes détectées dans l'image, qu'elles bougent ou non
    max_visibles = max(max_visibles, visibles)
    evenements = []  # événements de cette image, enregistrés avec une capture
    ids_dans_zone = set()
    if res.boxes.id is not None:
        for boite, tid in zip(res.boxes.xyxy.tolist(), res.boxes.id.int().tolist()):
            x1, y1, x2, y2 = map(int, boite)
            cx = (x1 + x2) // 2

            # Comptage des passages, avec une marge de chaque côté de la ligne
            if cx < ligne_x - MARGE:
                nouveau_cote = -1
            elif cx > ligne_x + MARGE:
                nouveau_cote = 1
            else:
                nouveau_cote = 0  # dans la marge : on ne décide pas
            if nouveau_cote != 0:
                ancien = cote.get(tid)
                if ancien == -1 and nouveau_cote == 1:
                    entrees += 1
                    evenements.append(("passage_gauche_droite", tid))
                elif ancien == 1 and nouveau_cote == -1:
                    sorties += 1
                    evenements.append(("passage_droite_gauche", tid))
                cote[tid] = nouveau_cote

            # Zone d'alerte : on regarde les pieds de la personne (bas du cadre)
            if zx1 <= cx <= zx2 and zy1 <= y2 <= zy2:
                ids_dans_zone.add(tid)
                etat = dans_zone.setdefault(tid, [maintenant, maintenant, False])
                etat[1] = maintenant
                if not etat[2] and maintenant - etat[0] >= DELAI_ALERTE:
                    etat[2] = True
                    nb_alertes += 1
                    evenements.append(("alerte_debut", tid))

            cv2.rectangle(image, (x1, y1), (x2, y2), (200, 160, 30), 2)
            cv2.putText(image, f"id {tid}", (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 160, 30), 2)

    # Une personne absente de la zone depuis plus d'une seconde en est sortie
    for tid in list(dans_zone):
        if tid not in ids_dans_zone and maintenant - dans_zone[tid][1] > 1.0:
            if dans_zone[tid][2]:
                noter("alerte_fin", tid)
            del dans_zone[tid]
    alerte = any(etat[2] for etat in dans_zone.values())

    # Pont vers le call center : une mesure toutes les 2 secondes par défaut.
    if maintenant - derniere_affluence >= INTERVALLE_AFFLUENCE:
        write_snapshot(visibles, entrees, sorties, alerte, agence=AGENCE, path=AFFLUENCE_CSV)
        derniere_affluence = maintenant

    retards.append(time.time() - heure_capture)
    fps = len(durees[-30:]) / sum(durees[-30:])
    cv2.line(image, (ligne_x, 0), (ligne_x, image.shape[0]), (0, 0, 255), 2)
    cv2.line(image, (ligne_x - MARGE, 0), (ligne_x - MARGE, image.shape[0]), (80, 80, 255), 1)
    cv2.line(image, (ligne_x + MARGE, 0), (ligne_x + MARGE, image.shape[0]), (80, 80, 255), 1)
    couleur_zone = (0, 0, 255) if alerte else (0, 165, 255)
    cv2.rectangle(image, (zx1, zy1), (zx2, zy2), couleur_zone, 4 if alerte else 2)
    if alerte:
        cv2.rectangle(image, (0, image.shape[0] - 40), (image.shape[1], image.shape[0]),
                      (0, 0, 255), -1)
        cv2.putText(image, "ALERTE : PERSONNE DANS LA ZONE", (10, image.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(image, f"G->D: {entrees}  D->G: {sorties}  presents: {entrees - sorties}",
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
    cv2.putText(image, f"{fps:.1f} img/s  retard: {retards[-1] * 1000:.0f} ms  visibles: {visibles}",
                (10, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
    for evenement, tid in evenements:
        noter(evenement, tid, image)
    cv2.imshow("Comptage v3 (q: quitter, r: remise a zero)", image)
    touche = cv2.waitKey(1) & 0xFF
    if touche == ord("q"):
        break
    if touche == ord("r"):
        entrees = sorties = 0
        noter("remise_a_zero")

noter("arret")
camera.fermer()
cv2.destroyAllWindows()
fichier.close()

utiles = durees[5:] or durees  # on ignore les premières images (démarrage du modèle)
if utiles:
    moyenne = sum(utiles) / len(utiles)
    retards_utiles = retards[5:] or retards
    print(f"\nTemps d'analyse moyen : {moyenne * 1000:.0f} ms par image ({1 / moyenne:.1f} images/s)")
    print(f"Retard moyen (de la capture à l'affichage) : {sum(retards_utiles) / len(retards_utiles) * 1000:.0f} ms")
    print(f"Passages : {entrees} gauche->droite, {sorties} droite->gauche, présents : {entrees - sorties}")
    print(f"Alertes déclenchées : {nb_alertes}")
    print(f"Maximum de personnes visibles en même temps : {max_visibles}")
    print(f"Journal enregistré dans : {os.path.abspath(JOURNAL)}")
    if CAPTURES:
        print(f"Captures enregistrées dans : {os.path.abspath(DOSSIER_CAPTURES)}")
