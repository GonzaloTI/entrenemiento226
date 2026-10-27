"""
=============================================================================
  DETECTOR DE MANOS CON CAPTURA EN HILO SEPARADO (THREAD-SAFE)
=============================================================================
- Corre captura de cámara y MediaPipe en un hilo en segundo plano (30 FPS).
- Extrae coordenadas 3D, ángulos de articulación y clasificación de gestos.
- Provee un método 'obtener_datos()' seguro para alimentar al visor 3D a 60+ FPS.
=============================================================================
"""

import os
import sys
import time
import math
import threading
import numpy as np

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import cv2
# pyrefly: ignore [missing-import]
import mediapipe as mp

try:
    from cinematica import procesar_landmarks_a_angulos
except ImportError:
    from .cinematica import procesar_landmarks_a_angulos

PUNTAS_IDS = [4, 8, 12, 16, 20]
PIP_IDS = [2, 6, 10, 14, 18]
NOMBRES_DEDOS = ["Pulgar", "Indice", "Medio", "Anular", "Menique"]

def distancia_euclidiana(p1, p2):
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

def clasificar_dedos(puntos_px, mano_label, es_espejo=True):
    estados = [0, 0, 0, 0, 0]

    # Dedos 1 a 4
    for i in range(1, 5):
        tip_y = puntos_px[PUNTAS_IDS[i]][1]
        pip_y = puntos_px[PIP_IDS[i]][1]
        if tip_y < pip_y:
            estados[i] = 1

    # Pulgar
    p_tip_thumb = puntos_px[4]
    p_ip_thumb = puntos_px[3]
    p_mcp_thumb = puntos_px[2]
    p_wrist = puntos_px[0]
    p_index_mcp = puntos_px[5]
    p_pinky_base = puntos_px[17]

    ref_escala = distancia_euclidiana(p_wrist, puntos_px[9])
    dist_tip_index_mcp = distancia_euclidiana(p_tip_thumb, p_index_mcp)
    dist_tip_pinky = distancia_euclidiana(p_tip_thumb, p_pinky_base)
    dist_ip_pinky = distancia_euclidiana(p_ip_thumb, p_pinky_base)
    dist_tip_mcp = distancia_euclidiana(p_tip_thumb, p_mcp_thumb)
    dist_ip_mcp = distancia_euclidiana(p_ip_thumb, p_mcp_thumb)
    dist_tip_wrist = distancia_euclidiana(p_tip_thumb, p_wrist)
    dist_mcp_wrist = distancia_euclidiana(p_mcp_thumb, p_wrist)

    cerca = (dist_tip_index_mcp < ref_escala * 0.44)
    doblado = dist_tip_pinky < (dist_ip_pinky * 1.05)
    encogido = dist_tip_mcp < (dist_ip_mcp * 1.15)

    pulgar_abierto = False
    if not cerca and not encogido:
        es_pulgar_arriba = (p_tip_thumb[1] < p_ip_thumb[1] < p_mcp_thumb[1]) and (dist_tip_wrist > dist_mcp_wrist * 1.2)
        mano_rel = mano_label if es_espejo else ("Left" if mano_label == "Right" else "Right")
        if mano_rel == "Right":
            es_lateral = (p_tip_thumb[0] < p_ip_thumb[0]) and (p_tip_thumb[0] < p_mcp_thumb[0])
        else:
            es_lateral = (p_tip_thumb[0] > p_ip_thumb[0]) and (p_tip_thumb[0] > p_mcp_thumb[0])

        if es_pulgar_arriba or (es_lateral and not doblado):
            pulgar_abierto = True

    estados[0] = 1 if pulgar_abierto else 0
    conteo = sum(estados)

    # Identificación de gesto
    dist_pinch = distancia_euclidiana(puntos_px[4], puntos_px[8])
    pinch_activo = dist_pinch < max(24, int(ref_escala * 0.28))

    if pinch_activo:
        gesto = "Click / Pellizco"
    elif conteo == 0:
        gesto = "Puno cerrado"
    elif conteo == 5:
        gesto = "Mano abierta"
    elif estados == [0, 1, 0, 0, 0]:
        gesto = "Senalando (1)"
    elif estados == [0, 1, 1, 0, 0]:
        gesto = "Paz / Victoria (2)"
    elif estados == [1, 1, 0, 0, 0]:
        gesto = "Pistola (L)"
    elif estados == [0, 1, 1, 1, 0]:
        gesto = "Tres dedos (3)"
    elif estados == [0, 1, 1, 1, 1]:
        gesto = "Cuatro dedos (4)"
    elif estados == [1, 0, 0, 0, 0]:
        gesto = "Pulgar Arriba" if p_tip_thumb[1] < p_wrist[1] else "Pulgar Abajo"
    elif estados in ([0, 1, 0, 0, 1], [1, 1, 0, 0, 1]):
        gesto = "Rock / Heavy Metal"
    elif estados == [1, 0, 0, 0, 1]:
        gesto = "Shaka / Surfer"
    else:
        gesto = f"{conteo} dedos"

    return estados, conteo, gesto, pinch_activo

class DetectorManoThread:
    """Hilo secundario de captura para alimentar al visor 3D."""
    def __init__(self, camera_index=None, mostrar_ventana_cam=True, espejo=True):
        self.camera_index = camera_index if camera_index is not None else self._autodetectar_camara()
        self.mostrar_ventana_cam = mostrar_ventana_cam
        self.espejo = espejo
        self.running = False
        self.thread = None
        self.lock = threading.Lock()

        # Datos compartidos
        self.mano_detectada = False
        self.etiqueta_mano = "Right"
        self.angulos_actuales = None
        self.estados_dedos = [0, 0, 0, 0, 0]
        self.gesto_actual = "Ninguno"
        self.fps = 0.0

    def _autodetectar_camara(self):
        """Prueba si hay cámara 1 (USB externa) disponible; si no, usa la 0."""
        for idx in [1, 0]:
            test_cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if not test_cap.isOpened():
                test_cap = cv2.VideoCapture(idx)
            if test_cap.isOpened():
                ret, _ = test_cap.read()
                test_cap.release()
                if ret:
                    return idx
        return 0

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._bucle_captura, daemon=True)
            self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)

    def cambiar_camara(self):
        with self.lock:
            self.camera_index = 1 if self.camera_index == 0 else 0
            print(f"[CAMBIO DE CAMARA] Nueva camara asignada: {self.camera_index}")

    def obtener_datos(self):
        with self.lock:
            return {
                "detectada": self.mano_detectada,
                "etiqueta": self.etiqueta_mano,
                "angulos": self.angulos_actuales,
                "estados": list(self.estados_dedos),
                "gesto": self.gesto_actual,
                "fps": self.fps,
                "cam_idx": self.camera_index
            }

    def _bucle_captura(self):
        indice_actual = self.camera_index
        cap = cv2.VideoCapture(indice_actual, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(indice_actual)

        if not cap.isOpened():
            print(f"[ERROR] No se pudo abrir la camara {indice_actual}")
            self.running = False
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        mp_hands = mp.solutions.hands
        mp_drawing = mp.solutions.drawing_utils

        hands = mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5
        )

        prev_time = time.time()

        while self.running:
            # Si el usuario solicitó cambio de cámara
            if self.camera_index != indice_actual:
                cap.release()
                indice_actual = self.camera_index
                cap = cv2.VideoCapture(indice_actual, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(indice_actual)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            if self.espejo:
                frame = cv2.flip(frame, 1)

            h, w, _ = frame.shape
            t_now = time.time()
            dt = t_now - prev_time
            calc_fps = 0.9 * self.fps + 0.1 * (1.0 / dt) if dt > 0 else 30.0
            prev_time = t_now

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = hands.process(rgb)
            rgb.flags.writeable = True

            detectada = False
            angulos = None
            etiqueta = "Right"
            estados = [0, 0, 0, 0, 0]
            gesto = "Buscando..."

            if results.multi_hand_landmarks and results.multi_handedness:
                detectada = True
                hand_landmarks = results.multi_hand_landmarks[0]
                handedness = results.multi_handedness[0]
                etiqueta = handedness.classification[0].label

                puntos_px = [(int(lm.x * w), int(lm.y * h)) for lm in hand_landmarks.landmark]
                estados, conteo, gesto, _ = clasificar_dedos(puntos_px, etiqueta, self.espejo)
                angulos = procesar_landmarks_a_angulos(hand_landmarks.landmark)

                if self.mostrar_ventana_cam:
                    mp_drawing.draw_landmarks(
                        frame,
                        hand_landmarks,
                        mp_hands.HAND_CONNECTIONS,
                        landmark_drawing_spec=mp_drawing.DrawingSpec(color=(0, 255, 255), thickness=2, circle_radius=3),
                        connection_drawing_spec=mp_drawing.DrawingSpec(color=(0, 255, 150), thickness=2)
                    )

            with self.lock:
                self.mano_detectada = detectada
                self.angulos_actuales = angulos
                self.etiqueta_mano = etiqueta
                self.estados_dedos = estados
                self.gesto_actual = gesto
                self.fps = calc_fps

            if self.mostrar_ventana_cam:
                cv2.rectangle(frame, (10, 10), (450, 75), (25, 28, 36), -1)
                cv2.rectangle(frame, (10, 10), (450, 75), (0, 255, 200), 1)
                color_st = (0, 255, 150) if detectada else (120, 120, 255)
                cv2.putText(frame, f"ESTADO: {'DETECTADA' if detectada else 'BUSCANDO...'}", (20, 35),
                            cv2.FONT_HERSHEY_DUPLEX, 0.55, color_st, 1)
                cv2.putText(frame, f"GESTO: {gesto.upper()} | Cam: {indice_actual}", (20, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1)
                cv2.imshow("Monitor Camara (MediaPipe)", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == 27 or key == ord('q'):
                    self.running = False
                    break

        cap.release()
        hands.close()
        cv2.destroyAllWindows()
