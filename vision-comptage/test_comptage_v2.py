"""Comptage de personnes, version 2 : réduit le retard de l'image et les doubles comptages.
Touche q pour arrêter. Un résumé s'affiche dans le terminal à la fin."""
import threading
import time
import cv2
from ultralytics import YOLO

# --- Réglages à modifier ---
SOURCE = "http://10.10.30.123:8080/video"
MODELE = "yolo11n.pt"
TAILLE_ANALYSE = 416     # plus petit = plus rapide (essayez 320), moins précis
CONFIANCE = 0.3          # plus bas = plus de détections, mais plus de fausses alertes
LARGEUR_MAX = 640        # l'image est réduite à cette largeur avant analyse
MARGE = 25               # pixels de chaque côté de la ligne : évite les doubles comptages


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


model = YOLO(MODELE)  # se télécharge au premier lancement (internet requis)
camera = Camera(SOURCE)

ligne_x = None
cote = {}  # identifiant -> dernier côté sûr de la ligne (-1 gauche, +1 droite)
entrees = sorties = 0
durees, retards = [], []

while True:
    image, heure_capture = camera.lire()
    if image is None:
        break
    if image.shape[1] > LARGEUR_MAX:
        hauteur = int(image.shape[0] * LARGEUR_MAX / image.shape[1])
        image = cv2.resize(image, (LARGEUR_MAX, hauteur))
    if ligne_x is None:
        ligne_x = image.shape[1] // 2

    t0 = time.time()
    res = model.track(image, persist=True, classes=[0], imgsz=TAILLE_ANALYSE,
                      conf=CONFIANCE, verbose=False)[0]
    durees.append(time.time() - t0)

    if res.boxes.id is not None:
        for boite, tid in zip(res.boxes.xyxy.tolist(), res.boxes.id.int().tolist()):
            x1, y1, x2, y2 = map(int, boite)
            cx = (x1 + x2) // 2
            if cx < ligne_x - MARGE:
                nouveau = -1
            elif cx > ligne_x + MARGE:
                nouveau = 1
            else:
                nouveau = 0  # dans la marge : on ne décide pas
            if nouveau != 0:
                ancien = cote.get(tid)
                if ancien == -1 and nouveau == 1:
                    entrees += 1
                elif ancien == 1 and nouveau == -1:
                    sorties += 1
                cote[tid] = nouveau
            cv2.rectangle(image, (x1, y1), (x2, y2), (200, 160, 30), 2)
            cv2.putText(image, f"id {tid}", (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 160, 30), 2)

    retards.append(time.time() - heure_capture)
    fps = len(durees[-30:]) / sum(durees[-30:])
    cv2.line(image, (ligne_x, 0), (ligne_x, image.shape[0]), (0, 0, 255), 2)
    cv2.line(image, (ligne_x - MARGE, 0), (ligne_x - MARGE, image.shape[0]), (80, 80, 255), 1)
    cv2.line(image, (ligne_x + MARGE, 0), (ligne_x + MARGE, image.shape[0]), (80, 80, 255), 1)
    cv2.putText(image, f"G->D: {entrees}  D->G: {sorties}  presents: {entrees - sorties}",
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
    cv2.putText(image, f"{fps:.1f} images/s  retard: {retards[-1] * 1000:.0f} ms",
                (10, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
    cv2.imshow("Comptage v2 (q pour quitter)", image)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.fermer()
cv2.destroyAllWindows()

utiles = durees[5:] or durees  # on ignore les premières images (démarrage du modèle)
if utiles:
    moyenne = sum(utiles) / len(utiles)
    print(f"\nTemps d'analyse moyen : {moyenne * 1000:.0f} ms par image ({1 / moyenne:.1f} images/s)")
    print(f"Retard moyen (de la capture à l'affichage) : {sum(retards[5:] or retards) / len(retards[5:] or retards) * 1000:.0f} ms")
    print(f"Passages : {entrees} gauche->droite, {sorties} droite->gauche, présents : {entrees - sorties}")
