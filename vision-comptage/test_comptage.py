"""Test de faisabilité : détection, suivi et comptage de personnes avec la webcam.
Touche q pour arrêter. Un résumé s'affiche dans le terminal à la fin."""
import time
import cv2
from ultralytics import YOLO

INDEX_CAMERA = "http://192.168.42.146:8080/video"
TAILLE_ANALYSE = 640

model = YOLO("yolo11n.pt")  # se télécharge au premier lancement (internet requis)
cap = cv2.VideoCapture(INDEX_CAMERA)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
if not cap.isOpened():
    raise SystemExit("Webcam introuvable : changez INDEX_CAMERA")

ligne_x = None
dernier_x = {}  # identifiant de la personne -> dernière position horizontale
entrees = sorties = 0
durees = []

while True:
    ok, frame = cap.read()
    if not ok:
        break
    if ligne_x is None:
        ligne_x = frame.shape[1] // 2

    t0 = time.time()
    res = model.track(frame, persist=True, classes=[0], imgsz=TAILLE_ANALYSE,
                      conf=0.4, verbose=False)[0]
    durees.append(time.time() - t0)

    if res.boxes.id is not None:
        for box, tid in zip(res.boxes.xyxy.tolist(), res.boxes.id.int().tolist()):
            x1, y1, x2, y2 = map(int, box)
            cx = (x1 + x2) // 2
            if tid in dernier_x:
                if dernier_x[tid] < ligne_x <= cx:
                    entrees += 1
                elif dernier_x[tid] >= ligne_x > cx:
                    sorties += 1
            dernier_x[tid] = cx
            cv2.rectangle(frame, (x1, y1), (x2, y2), (200, 160, 30), 2)
            cv2.putText(frame, f"id {tid}", (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 160, 30), 2)

    recent = durees[-30:]
    fps = len(recent) / sum(recent)
    cv2.line(frame, (ligne_x, 0), (ligne_x, frame.shape[0]), (0, 0, 255), 2)
    cv2.putText(frame, f"gauche->droite: {entrees}  droite->gauche: {sorties}",
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.putText(frame, f"{fps:.1f} images/s", (10, 58),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.imshow("Test comptage (q pour quitter)", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()

utiles = durees[5:] or durees  # on ignore les premières images (démarrage du modèle)
if utiles:
    moyenne = sum(utiles) / len(utiles)
    fps = 1 / moyenne
    print(f"\nTemps moyen par image : {moyenne * 1000:.0f} ms ({fps:.1f} images/s)")
    print(f"Passages comptés : {entrees} gauche->droite, {sorties} droite->gauche")
    if fps >= 8:
        print("Verdict : confortable pour le comptage.")
    elif fps >= 5:
        print("Verdict : jouable, testez avec des personnes qui marchent vite.")
    else:
        print("Verdict : trop lent. Baissez TAILLE_ANALYSE ou comptez sur le Jetson.")
