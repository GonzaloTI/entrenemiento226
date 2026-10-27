"""
=============================================================================
  DETECTOR DE MANOS CON GESTIÓN ROBUSTA DE CÁMARAS (USB E INTEGRADA)
=============================================================================
- Compatible con Cámara Integrada (0) y Cámara Externa USB (1).
- Cambio dinámico en caliente con la tecla [C].
- Detección segura: Si una cámara no responde, no crashea ni se queda en negro,
  mantiene la cámara activa automáticamente.
- Modos de captura DirectShow y nativo para Windows.
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

def probar_camara(idx):
    """Verifica si un índice de cámara realmente entrega fotogramas."""
    for backend in [cv2.CAP_DSHOW, cv2.CAP_ANY]:
        cap = cv2.VideoCapture(idx, backend)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None and frame.size > 0:
                return True
    return False

def abrir_dispositivo_camara(idx, ancho=1280, alto=720):
    """Abre la cámara con respaldo de backends seguros para Windows."""
    for backend in [cv2.CAP_DSHOW, cv2.CAP_ANY]:
        cap = cv2.VideoCapture(idx, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
            ret, frame = cap.read()
            if ret and frame is not None:
                return cap
            cap.release()
    return None

def clasificar_dedos(puntos_px, mano_label, es_espejo=True):
    estados = [0, 0, 0, 0, 0]

    for i in range(1, 5):
        tip_y = puntos_px[PUNTAS_IDS[i]][1]
        pip_y = puntos_px[PIP_IDS[i]][1]
        if tip_y < pip_y:
            estados[i] = 1

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
    """Gestiona captura de video con selector automático y cambio en caliente."""
    def __init__(self, camera_index=None, mostrar_ventana_cam=True, espejo=True):
        self.mostrar_ventana_cam = mostrar_ventana_cam
        self.espejo = espejo
        self.running = False
        self.thread = None
        self.lock = threading.Lock()

        # Determinar cámara inicial
        if camera_index is not None:
            self.camera_index = camera_index
        else:
            self.camera_index = self._seleccionar_camara_inicial()

        self.solicitar_cambio_cam = False
        self.nuevo_indice_cam = self.camera_index

        # Datos compartidos con el visor
        self.mano_detectada = False
        self.etiqueta_mano = "Right"
        self.angulos_actuales = None
        self.estados_dedos = [0, 0, 0, 0, 0]
        self.gesto_actual = "Buscando..."
        self.fps = 0.0
        self.cam_nombre = "Cámara 0"

    def _seleccionar_camara_inicial(self):
        """Si la cámara USB (1) está conectada la prioriza; de lo contrario usa la 0."""
        print("\n[INFO] Escaneando puertos de cámara disponibles...")
        cam1_ok = probar_camara(1)
        cam0_ok = probar_camara(0)

        if cam1_ok:
            print("[OK] Cámara USB (Puerto 1) detectada y lista.")
            return 1
        elif cam0_ok:
            print("[OK] Cámara Integrada (Puerto 0) detectada y lista.")
            return 0
        else:
            print("[AVISO] No se detectó cámara en puertos 0 o 1. Intentando puerto 0 por defecto.")
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
        """Solicita alternar entre cámara 0 y cámara 1."""
        with self.lock:
            siguiente = 0 if self.camera_index == 1 else 1
            print(f"\n[CAMBIO] Solicitando cambio a Cámara {siguiente}...")
            self.nuevo_indice_cam = siguiente
            self.solicitar_cambio_cam = True

    def alternar_espejo(self):
        with self.lock:
            self.espejo = not self.espejo
            print(f"[ESPEJO] Modo espejo: {'ACTIVADO' if self.espejo else 'DESACTIVADO'}")

    def obtener_datos(self):
        with self.lock:
            return {
                "detectada": self.mano_detectada,
                "etiqueta": self.etiqueta_mano,
                "angulos": self.angulos_actuales,
                "estados": list(self.estados_dedos),
                "gesto": self.gesto_actual,
                "fps": self.fps,
                "cam_idx": self.camera_index,
                "cam_nombre": self.cam_nombre
            }

    def _bucle_captura(self):
        cap = abrir_dispositivo_camara(self.camera_index)
        if cap is None:
            # Respaldo inmediato a la otra cámara si falló
            otro = 0 if self.camera_index == 1 else 1
            print(f"[AVISO] Cámara {self.camera_index} no respondió. Probando cámara de respaldo {otro}...")
            cap = abrir_dispositivo_camara(otro)
            if cap is not None:
                self.camera_index = otro

        if cap is None:
            print(f"[ERROR CRÍTICO] No se pudo abrir ninguna cámara (ni 0 ni 1). Verifica los permisos de cámara en Windows.")
            self.running = False
            return

        tipo_cam = "USB Externa" if self.camera_index == 1 else "Integrada Laptop"
        self.cam_nombre = f"Cam {self.camera_index} ({tipo_cam})"
        print(f"[CONECTADO] {self.cam_nombre} activa y capturando.")

        mp_hands = mp.solutions.hands
        mp_drawing = mp.solutions.drawing_utils

        hands = mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.55,
            min_tracking_confidence=0.5
        )

        prev_time = time.time()

        while self.running:
            # 1. Gestionar cambio de cámara en caliente
            if self.solicitar_cambio_cam:
                self.solicitar_cambio_cam = False
                target_idx = self.nuevo_indice_cam
                print(f"[CAMBIO] Probando conexión con Cámara {target_idx}...")
                test_nueva = abrir_dispositivo_camara(target_idx)
                if test_nueva is not None:
                    cap.release()
                    cap = test_nueva
                    self.camera_index = target_idx
                    tipo = "USB Externa" if target_idx == 1 else "Integrada Laptop"
                    self.cam_nombre = f"Cam {target_idx} ({tipo})"
                    print(f"[OK] Cambio exitoso a: {self.cam_nombre}")
                else:
                    print(f"[AVISO] No se pudo conectar a Cámara {target_idx}. Se mantiene {self.cam_nombre}.")

            # 2. Lectura de fotograma
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            if self.espejo:
                frame = cv2.flip(frame, 1)

            h, w, _ = frame.shape
            t_now = time.time()
            dt = t_now - prev_time
            calc_fps = 0.9 * self.fps + 0.1 * (1.0 / dt) if dt > 0 else 30.0
            prev_time = t_now

            # 3. Detección con MediaPipe
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

            # 4. Actualizar estado compartido
            with self.lock:
                self.mano_detectada = detectada
                self.angulos_actuales = angulos
                self.etiqueta_mano = etiqueta
                self.estados_dedos = estados
                self.gesto_actual = gesto
                self.fps = calc_fps

            # 5. Ventana monitor de OpenCV
            if self.mostrar_ventana_cam:
                cv2.rectangle(frame, (10, 10), (480, 80), (22, 25, 33), -1)
                cv2.rectangle(frame, (10, 10), (480, 80), (0, 255, 200), 1)

                col_st = (0, 255, 150) if detectada else (120, 140, 255)
                texto_st = f"ESTADO: {'MANO DETECTADA' if detectada else 'BUSCANDO MANO...'}"
                cv2.putText(frame, texto_st, (20, 35), cv2.FONT_HERSHEY_DUPLEX, 0.55, col_st, 1)

                cv2.putText(frame, f"GESTO: {gesto.upper()} | FPS: {int(calc_fps)}", (20, 56),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1)

                cv2.putText(frame, f"{self.cam_nombre} | [C] Cambiar Cam | [M] Espejo", (20, 74),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 220, 255), 1)

                cv2.imshow("Monitor Camara (MediaPipe)", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == 27 or key == ord('q'):
                    self.running = False
                    break
                elif key == ord('c') or key == ord('C'):
                    self.cambiar_camara()
                elif key == ord('m') or key == ord('M'):
                    self.alternar_espejo()

        cap.release()
        hands.close()
        cv2.destroyAllWindows()
