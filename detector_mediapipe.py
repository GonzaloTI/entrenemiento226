"""
=============================================================================
  DETECTOR MULTIMODAL MEDIAPIPE - DETECCION DE DEDOS, MANOS, POSE Y ROSTRO
=============================================================================
Este script implementa todas las capacidades de detección de MediaPipe con OpenCV:
  1. MODO HOLISTIC (Todo en Uno): Rostro (468 pts) + Cuerpo (33 pts) + Manos (21 pts c/u).
  2. MODO MANOS & DEDOS PRO:
       - Detección precisa de cada dedo (Pulgar, Índice, Medio, Anular, Meñique).
       - Conteo exacto de dedos levantados (0 a 10).
       - Reconocimiento de gestos (Paz, Like, Dislike, Puño, Mano abierta, Rock, etc.).
       - Detección de pellizco (Pinch / Click) con medición de distancia.
  3. MODO POSE (Cuerpo y Postura): 33 puntos del esqueleto con cálculo de ángulos corporales.
  4. MODO MALLA FACIAL (Face Mesh): 468 puntos faciales y seguimiento de contornos.
  5. MODO DETECCION FACIAL: Detección rápida de rostros con bounding box y confianza.
  6. MODO SEGMENTACION: Desenfoque de fondo en tiempo real (Virtual Blur).

Controles de teclado:
  [1] a [6] : Cambiar de modo
  [M]       : Activar/desactivar efecto espejo
  [H]       : Mostrar/ocultar interfaz gráfica (HUD)
  [S]       : Guardar captura de pantalla (foto)
  [Q] o ESC : Salir
=============================================================================
"""

import os
import sys
import time
import math
import argparse
import numpy as np

# Suprimir advertencias y logs innecesarios de TensorFlow
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import cv2
# pyrefly: ignore [missing-import]
import mediapipe as mp

# =============================================================================
# UTILIDADES MATEMÁTICAS Y DE DIBUJO
# =============================================================================

def calcular_angulo(p1, p2, p3):
    """Calcula el ángulo en grados formado por tres puntos (p2 es el vértice)."""
    a = np.array(p1)
    b = np.array(p2)
    c = np.array(p3)
    rad = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
    ang = np.abs(rad * 180.0 / np.pi)
    if ang > 180.0:
        ang = 360.0 - ang
    return int(ang)

def calcular_distancia(p1, p2):
    """Calcula la distancia euclidiana entre dos puntos (x, y)."""
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

def dibujar_rect_redondeado_translucido(img, pt1, pt2, color, alpha=0.6, radio=12):
    """Dibuja una tarjeta semitransparente con esquinas redondeadas."""
    x1, y1 = pt1
    x2, y2 = pt2
    overlay = img.copy()
    
    # Dibujar cuerpo rectangular y esquinas
    cv2.rectangle(overlay, (x1 + radio, y1), (x2 - radio, y2), color, -1)
    cv2.rectangle(overlay, (x1, y1 + radio), (x2, y2 - radio), color, -1)
    cv2.circle(overlay, (x1 + radio, y1 + radio), radio, color, -1)
    cv2.circle(overlay, (x2 - radio, y1 + radio), radio, color, -1)
    cv2.circle(overlay, (x1 + radio, y2 - radio), radio, color, -1)
    cv2.circle(overlay, (x2 - radio, y2 - radio), radio, color, -1)
    
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
    # Borde sutil
    cv2.rectangle(img, (x1 + radio, y1), (x2 - radio, y1), (255, 255, 255), 1)
    cv2.rectangle(img, (x1 + radio, y2), (x2 - radio, y2), (180, 180, 180), 1)

# =============================================================================
# DETECCIÓN Y CLASIFICACIÓN DE DEDOS
# =============================================================================

NOMBRES_DEDOS = ["Pulgar", "Indice", "Medio", "Anular", "Menique"]
PUNTAS_IDS = [4, 8, 12, 16, 20]
PIP_IDS = [2, 6, 10, 14, 18]

def analizar_dedos_mano(puntos_px, handedness_label="Right", es_espejo=True):
    """
    Analiza los 21 puntos de una mano para determinar qué dedos están levantados.
    
    Retorna:
      - estados: lista de 5 booleanos [Pulgar, Indice, Medio, Anular, Menique]
      - conteo: entero con la cantidad de dedos levantados (0 a 5)
      - gesto: string con el gesto detectado
      - pinch_info: tupla (activo, dist, p_medio) indicando si hay pellizco entre pulgar e índice
    """
    estados = [0, 0, 0, 0, 0]
    
    # --- 1. Detección de los 4 dedos superiores (Índice, Medio, Anular, Meñique) ---
    for i in range(1, 5):
        tip_id = PUNTAS_IDS[i]
        pip_id = PIP_IDS[i]
        # Si la coordenada Y de la punta está por encima (menor Y) de la articulación PIP
        if puntos_px[tip_id][1] < puntos_px[pip_id][1]:
            estados[i] = 1
        else:
            estados[i] = 0

    # --- 2. Detección precisa del Pulgar ---
    # Un pulgar levantado/extendido debe estar separado de la mano y no doblado hacia la palma o pegado al índice.
    tip_thumb = puntos_px[4]
    ip_thumb = puntos_px[3]
    mcp_thumb = puntos_px[2]
    wrist = puntos_px[0]
    index_mcp = puntos_px[5]
    index_pip = puntos_px[6]
    pinky_mcp = puntos_px[17]

    # Escala de referencia de la palma (muñeca a base de dedo medio)
    ref_scale = calcular_distancia(wrist, puntos_px[9])

    dist_tip_index_mcp = calcular_distancia(tip_thumb, index_mcp)
    dist_tip_index_pip = calcular_distancia(tip_thumb, index_pip)
    dist_tip_pinky = calcular_distancia(tip_thumb, pinky_mcp)
    dist_ip_pinky = calcular_distancia(ip_thumb, pinky_mcp)
    dist_tip_mcp = calcular_distancia(tip_thumb, mcp_thumb)
    dist_ip_mcp = calcular_distancia(ip_thumb, mcp_thumb)
    dist_tip_wrist = calcular_distancia(tip_thumb, wrist)
    dist_mcp_wrist = calcular_distancia(mcp_thumb, wrist)

    # 1. Si el pulgar está cerca de la mano (pegado al índice o al borde de la palma) -> ABAJO
    cerca_de_la_mano = (dist_tip_index_mcp < ref_scale * 0.44) or (dist_tip_index_pip < ref_scale * 0.35)

    # 2. Si el pulgar está doblado hacia la palma / meñique -> ABAJO
    doblado_hacia_palma = dist_tip_pinky < (dist_ip_pinky * 1.05)

    # 3. Si la punta está encogida respecto al nudillo MCP -> ABAJO
    encogido = dist_tip_mcp < (dist_ip_mcp * 1.15)

    pulgar_abierto = False
    if not cerca_de_la_mano and not encogido:
        # Caso A: Pulgar Arriba (Like) claramente vertical hacia arriba
        es_pulgar_arriba = (tip_thumb[1] < ip_thumb[1] < mcp_thumb[1]) and (dist_tip_wrist > dist_mcp_wrist * 1.2)

        # Caso B: Extensión lateral hacia afuera de la mano
        mano_efectiva = handedness_label if es_espejo else ("Left" if handedness_label == "Right" else "Right")
        if mano_efectiva == "Right":
            es_lateral = (tip_thumb[0] < ip_thumb[0]) and (tip_thumb[0] < mcp_thumb[0])
        else:
            es_lateral = (tip_thumb[0] > ip_thumb[0]) and (tip_thumb[0] > mcp_thumb[0])

        if es_pulgar_arriba:
            pulgar_abierto = True
        elif es_lateral and not doblado_hacia_palma:
            pulgar_abierto = True

    if pulgar_abierto:
        estados[0] = 1
    else:
        estados[0] = 0

    conteo = sum(estados)

    # --- 3. Detección de Pellizco (Pinch / Click) ---
    dist_pinch = calcular_distancia(puntos_px[4], puntos_px[8])
    ref_scale = calcular_distancia(puntos_px[0], puntos_px[9])  # escala muñeca a nudillo medio
    umbral_pinch = max(25, int(ref_scale * 0.28))
    pinch_activo = dist_pinch < umbral_pinch
    pinch_midpoint = (
        (puntos_px[4][0] + puntos_px[8][0]) // 2,
        (puntos_px[4][1] + puntos_px[8][1]) // 2
    )

    # --- 4. Clasificación de Gestos ---
    gesto = "Indeterminado"
    if pinch_activo:
        gesto = "Click / Pellizco [OK]"
    elif conteo == 0:
        gesto = "Puno cerrado"
    elif conteo == 5:
        gesto = "Mano abierta"
    elif estados == [0, 1, 0, 0, 0]:
        gesto = "Senalando (1)"
    elif estados == [0, 1, 1, 0, 0]:
        gesto = "Paz / Victoria"
    elif estados == [1, 1, 0, 0, 0]:
        gesto = "Pistola (L)"
    elif estados == [0, 1, 1, 1, 0]:
        gesto = "Tres (3)"
    elif estados == [0, 1, 1, 1, 1]:
        gesto = "Cuatro (4)"
    elif estados == [1, 0, 0, 0, 0]:
        # Pulgar solo: verificar si apunta hacia arriba o hacia abajo
        if tip_thumb[1] < wrist[1]:
            gesto = "Pulgar arriba (Like)"
        else:
            gesto = "Pulgar abajo (Dislike)"
    elif estados == [0, 0, 0, 0, 1]:
        gesto = "Menique solo"
    elif estados == [0, 1, 0, 0, 1] or estados == [1, 1, 0, 0, 1]:
        gesto = "Rock / Heavy metal"
    elif estados == [1, 0, 0, 0, 1]:
        gesto = "Shaka / Surfer"
    elif estados == [0, 0, 1, 0, 0]:
        gesto = "Dedo medio"
    else:
        gesto = f"{conteo} dedos levantados"

    return estados, conteo, gesto, (pinch_activo, dist_pinch, pinch_midpoint)

# =============================================================================
# CLASE PRINCIPAL: DETECTOR MEDIAPIPE TODO EN UNO
# =============================================================================

class MediaPipeMultimodalApp:
    def __init__(self, camera_idx=0, video_path=None, width=1280, height=720):
        self.camera_idx = camera_idx
        self.video_path = video_path
        self.width = width
        self.height = height
        
        # Opciones de visualización
        self.es_espejo = True
        self.mostrar_hud = True
        self.modo_actual = 1  # 1: Holistic, 2: Manos/Dedos, 3: Pose, 4: FaceMesh, 5: FaceDetect, 6: Segmentacion
        
        # Mapeo de nombres de modos
        self.MODOS = {
            1: "1. HOLISTIC (Todo en Uno: Rostro + Manos + Cuerpo)",
            2: "2. MANOS & DEDOS PRO (Conteo, Gestos y Coordenadas)",
            3: "3. POSE (Esqueleto Corporal y Angulos)",
            4: "4. MALLA FACIAL (Face Mesh 468 Puntos)",
            5: "5. DETECCION FACIAL RAPIDA (Bounding Box)",
            6: "6. SEGMENTACION DE FONDO (Efecto Blur Virtual)"
        }

        # Inicializar soluciones de MediaPipe
        print("[INFO] Inicializando módulos de MediaPipe...")
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles

        # 1. Holistic
        self.holistic = mp.solutions.holistic.Holistic(
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
            refine_face_landmarks=True
        )

        # 2. Hands (Manos detallado)
        self.hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5
        )

        # 3. Pose
        self.pose = mp.solutions.pose.Pose(
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

        # 4. Face Mesh
        self.face_mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=2,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

        # 5. Face Detection
        self.face_detection = mp.solutions.face_detection.FaceDetection(
            min_detection_confidence=0.6
        )

        # 6. Selfie Segmentation
        self.segmentation = mp.solutions.selfie_segmentation.SelfieSegmentation(
            model_selection=1
        )

        # Conexiones estándar
        self.mp_holistic_conn = mp.solutions.holistic
        self.mp_hands_conn = mp.solutions.hands
        self.mp_pose_conn = mp.solutions.pose
        self.mp_facemesh_conn = mp.solutions.face_mesh

        print("[OK] Todos los módulos de MediaPipe se han inicializado correctamente.")

    def abrir_fuente_video(self):
        """Abre la cámara web o archivo de video."""
        if self.video_path:
            cap = cv2.VideoCapture(self.video_path)
            print(f"[INFO] Reproduciendo archivo de video: {self.video_path}")
        else:
            cap = cv2.VideoCapture(self.camera_idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                # Reintento con backend estándar
                cap = cv2.VideoCapture(self.camera_idx)
            print(f"[INFO] Abriendo cámara web índice: {self.camera_idx}")

        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        return cap

    # -------------------------------------------------------------------------
    # PROCESAMIENTO MODO 1: HOLISTIC (TODO EN UNO)
    # -------------------------------------------------------------------------
    def procesar_holistic(self, frame, rgb_frame):
        h, w, _ = frame.shape
        results = self.holistic.process(rgb_frame)

        # 1. Dibujar Malla Facial simplificada
        if results.face_landmarks:
            self.mp_drawing.draw_landmarks(
                frame,
                results.face_landmarks,
                self.mp_holistic_conn.FACEMESH_CONTOURS,
                landmark_drawing_spec=None,
                connection_drawing_spec=self.mp_drawing.DrawingSpec(color=(220, 220, 100), thickness=1, circle_radius=1)
            )

        # 2. Dibujar Esqueleto Corporal (Pose)
        if results.pose_landmarks:
            self.mp_drawing.draw_landmarks(
                frame,
                results.pose_landmarks,
                self.mp_holistic_conn.POSE_CONNECTIONS,
                landmark_drawing_spec=self.mp_drawing.DrawingSpec(color=(0, 255, 255), thickness=2, circle_radius=3),
                connection_drawing_spec=self.mp_drawing.DrawingSpec(color=(255, 120, 0), thickness=2)
            )

        # 3. Dibujar Mano Izquierda y contar dedos
        dedos_izq = 0
        if results.left_hand_landmarks:
            self.mp_drawing.draw_landmarks(
                frame,
                results.left_hand_landmarks,
                self.mp_holistic_conn.HAND_CONNECTIONS,
                landmark_drawing_spec=self.mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=3),
                connection_drawing_spec=self.mp_drawing.DrawingSpec(color=(0, 200, 255), thickness=2)
            )
            pts = [(int(lm.x * w), int(lm.y * h)) for lm in results.left_hand_landmarks.landmark]
            _, dedos_izq, gesto_izq, _ = analizar_dedos_mano(pts, "Left", self.es_espejo)
            cv2.putText(frame, f"Mano Izq: {dedos_izq} dedos ({gesto_izq})", (pts[0][0] - 80, pts[0][1] - 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        # 4. Dibujar Mano Derecha y contar dedos
        dedos_der = 0
        if results.right_hand_landmarks:
            self.mp_drawing.draw_landmarks(
                frame,
                results.right_hand_landmarks,
                self.mp_holistic_conn.HAND_CONNECTIONS,
                landmark_drawing_spec=self.mp_drawing.DrawingSpec(color=(255, 0, 255), thickness=2, circle_radius=3),
                connection_drawing_spec=self.mp_drawing.DrawingSpec(color=(255, 255, 0), thickness=2)
            )
            pts = [(int(lm.x * w), int(lm.y * h)) for lm in results.right_hand_landmarks.landmark]
            _, dedos_der, gesto_der, _ = analizar_dedos_mano(pts, "Right", self.es_espejo)
            cv2.putText(frame, f"Mano Der: {dedos_der} dedos ({gesto_der})", (pts[0][0] - 80, pts[0][1] - 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 2)

        # Resumen en pantalla
        total_dedos = dedos_izq + dedos_der
        if results.left_hand_landmarks or results.right_hand_landmarks:
            cv2.putText(frame, f"TOTAL DEDOS VISIBLES: {total_dedos}", (30, h - 35),
                        cv2.FONT_HERSHEY_DUPLEX, 0.8, (0, 255, 255), 2)

    # -------------------------------------------------------------------------
    # PROCESAMIENTO MODO 2: MANOS Y DEDOS PRO (DETECCIÓN Y CONTEO AVANZADO)
    # -------------------------------------------------------------------------
    def procesar_manos_dedos(self, frame, rgb_frame):
        h, w, _ = frame.shape
        results = self.hands.process(rgb_frame)

        total_dedos_pantalla = 0
        panel_y = 120

        if results.multi_hand_landmarks and results.multi_handedness:
            for hand_landmarks, handedness in zip(results.multi_hand_landmarks, results.multi_handedness):
                etiqueta_original = handedness.classification[0].label  # "Left" o "Right"
                confianza = handedness.classification[0].score

                # Obtener coordenadas absolutas en píxeles de los 21 puntos
                puntos_px = [(int(lm.x * w), int(lm.y * h)) for lm in hand_landmarks.landmark]

                # Análisis de dedos
                estados, conteo, gesto, pinch_info = analizar_dedos_mano(
                    puntos_px, etiqueta_original, self.es_espejo
                )
                total_dedos_pantalla += conteo

                # Dibujar esqueleto de la mano con estilo personalizado
                self.mp_drawing.draw_landmarks(
                    frame,
                    hand_landmarks,
                    self.mp_hands_conn.HAND_CONNECTIONS,
                    landmark_drawing_spec=self.mp_drawing.DrawingSpec(color=(0, 255, 200), thickness=2, circle_radius=3),
                    connection_drawing_spec=self.mp_drawing.DrawingSpec(color=(255, 120, 50), thickness=2)
                )

                # Resaltar las puntas de los dedos con círculos coloreados según estado
                for i, tip_id in enumerate(PUNTAS_IDS):
                    px, py = puntos_px[tip_id]
                    abierto = estados[i]
                    color_punto = (0, 255, 0) if abierto else (0, 0, 255)
                    # Círculo en la punta
                    cv2.circle(frame, (px, py), 9, color_punto, -1)
                    cv2.circle(frame, (px, py), 12, (255, 255, 255), 2)
                    # Texto con inicial del dedo
                    inicial = NOMBRES_DEDOS[i][0]
                    cv2.putText(frame, inicial, (px - 5, py + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)

                # Efecto visual de Pellizco (Pinch / Click)
                pinch_activo, dist_pinch, pinch_mid = pinch_info
                if pinch_activo:
                    p_thumb = puntos_px[4]
                    p_index = puntos_px[8]
                    cv2.line(frame, p_thumb, p_index, (0, 255, 255), 4)
                    cv2.circle(frame, pinch_mid, 18, (0, 255, 255), -1)
                    cv2.circle(frame, pinch_mid, 22, (255, 255, 255), 2)
                    cv2.putText(frame, "CLICK!", (pinch_mid[0] - 25, pinch_mid[1] - 25),
                                cv2.FONT_HERSHEY_DUPLEX, 0.7, (0, 255, 255), 2)

                # Tarjeta flotante sobre la muñeca
                p_muneca = puntos_px[0]
                tx = max(20, min(w - 220, p_muneca[0] - 100))
                ty = max(90, p_muneca[1] - 60)
                dibujar_rect_redondeado_translucido(frame, (tx, ty), (tx + 210, ty + 50), (20, 20, 30), alpha=0.7)
                cv2.putText(frame, f"Mano {etiqueta_original} ({int(confianza*100)}%)", (tx + 10, ty + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 220, 255), 1)
                cv2.putText(frame, f"{conteo} Dedos | {gesto}", (tx + 10, ty + 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 120), 2)

                # Panel lateral de diagnóstico de dedos
                if self.mostrar_hud and panel_y + 160 < h:
                    dibujar_rect_redondeado_translucido(frame, (w - 260, panel_y), (w - 15, panel_y + 155), (15, 15, 25), alpha=0.8)
                    cv2.putText(frame, f"MANO {etiqueta_original.upper()}:", (w - 245, panel_y + 24),
                                cv2.FONT_HERSHEY_DUPLEX, 0.55, (0, 255, 255), 1)
                    
                    for i, nombre in enumerate(NOMBRES_DEDOS):
                        estado_str = "ARRIBA" if estados[i] else "ABAJO"
                        col = (0, 255, 0) if estados[i] else (100, 100, 255)
                        cv2.putText(frame, f"{nombre}:", (w - 245, panel_y + 48 + i * 20),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)
                        cv2.putText(frame, estado_str, (w - 140, panel_y + 48 + i * 20),
                                    cv2.FONT_HERSHEY_DUPLEX, 0.45, col, 1)

                    panel_y += 170

        # Conteo gigante en pantalla
        cv2.putText(frame, f"DEDOS ACTIVOS: {total_dedos_pantalla}", (30, h - 35),
                    cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 255, 120), 2)

    # -------------------------------------------------------------------------
    # PROCESAMIENTO MODO 3: POSE (ESQUELETO CORPORAL Y POSTURA)
    # -------------------------------------------------------------------------
    def procesar_pose(self, frame, rgb_frame):
        h, w, _ = frame.shape
        results = self.pose.process(rgb_frame)

        if results.pose_landmarks:
            # Dibujar esqueleto
            self.mp_drawing.draw_landmarks(
                frame,
                results.pose_landmarks,
                self.mp_pose_conn.POSE_CONNECTIONS,
                landmark_drawing_spec=self.mp_drawing.DrawingSpec(color=(0, 255, 255), thickness=3, circle_radius=4),
                connection_drawing_spec=self.mp_drawing.DrawingSpec(color=(255, 80, 0), thickness=3)
            )

            lm = results.pose_landmarks.landmark
            # Calcular ángulo de codo derecho (12: hombro, 14: codo, 16: muñeca)
            codo_der_p1 = (int(lm[12].x * w), int(lm[12].y * h))
            codo_der_p2 = (int(lm[14].x * w), int(lm[14].y * h))
            codo_der_p3 = (int(lm[16].x * w), int(lm[16].y * h))
            ang_codo_der = calcular_angulo(codo_der_p1, codo_der_p2, codo_der_p3)
            cv2.putText(frame, f"{ang_codo_der} deg", (codo_der_p2[0] + 10, codo_der_p2[1]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

            # Calcular ángulo de codo izquierdo (11: hombro, 13: codo, 15: muñeca)
            codo_izq_p1 = (int(lm[11].x * w), int(lm[11].y * h))
            codo_izq_p2 = (int(lm[13].x * w), int(lm[13].y * h))
            codo_izq_p3 = (int(lm[15].x * w), int(lm[15].y * h))
            ang_codo_izq = calcular_angulo(codo_izq_p1, codo_izq_p2, codo_izq_p3)
            cv2.putText(frame, f"{ang_codo_izq} deg", (codo_izq_p2[0] - 70, codo_izq_p2[1]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

            # Tarjeta de postura
            if self.mostrar_hud:
                dibujar_rect_redondeado_translucido(frame, (20, h - 110), (320, h - 25), (20, 20, 30), alpha=0.75)
                cv2.putText(frame, "BIOMECANICA DE POSE", (35, h - 85),
                            cv2.FONT_HERSHEY_DUPLEX, 0.55, (0, 255, 255), 1)
                cv2.putText(frame, f"Codo Izq: {ang_codo_izq} deg | Codo Der: {ang_codo_der} deg", (35, h - 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(frame, "33 Puntos de articulacion detectados", (35, h - 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 120), 1)

    # -------------------------------------------------------------------------
    # PROCESAMIENTO MODO 4: MALLA FACIAL (FACE MESH 468/478 PUNTOS)
    # -------------------------------------------------------------------------
    def procesar_face_mesh(self, frame, rgb_frame):
        results = self.face_mesh.process(rgb_frame)

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                # 1. Malla general (tesselation)
                self.mp_drawing.draw_landmarks(
                    image=frame,
                    landmark_list=face_landmarks,
                    connections=self.mp_facemesh_conn.FACEMESH_TESSELATION,
                    landmark_drawing_spec=None,
                    connection_drawing_spec=self.mp_drawing_styles.get_default_face_mesh_tesselation_style()
                )
                # 2. Contorno del rostro (labios, cejas, ojos)
                self.mp_drawing.draw_landmarks(
                    image=frame,
                    landmark_list=face_landmarks,
                    connections=self.mp_facemesh_conn.FACEMESH_CONTOURS,
                    landmark_drawing_spec=None,
                    connection_drawing_spec=self.mp_drawing_styles.get_default_face_mesh_contours_style()
                )
                # 3. Iris (si está disponible)
                if hasattr(self.mp_facemesh_conn, 'FACEMESH_IRISES'):
                    self.mp_drawing.draw_landmarks(
                        image=frame,
                        landmark_list=face_landmarks,
                        connections=self.mp_facemesh_conn.FACEMESH_IRISES,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=self.mp_drawing_styles.get_default_face_mesh_iris_connections_style()
                    )

            num_rostros = len(results.multi_face_landmarks)
            cv2.putText(frame, f"ROSTROS DETECTADOS: {num_rostros} (468 puntos c/u)", (30, frame.shape[0] - 35),
                        cv2.FONT_HERSHEY_DUPLEX, 0.75, (0, 255, 255), 2)

    # -------------------------------------------------------------------------
    # PROCESAMIENTO MODO 5: DETECCIÓN FACIAL (BOUNDING BOX & CONFIDENCIA)
    # -------------------------------------------------------------------------
    def procesar_face_detection(self, frame, rgb_frame):
        h, w, _ = frame.shape
        results = self.face_detection.process(rgb_frame)

        if results.detections:
            for i, detection in enumerate(results.detections):
                score = detection.score[0]
                bbox = detection.location_data.relative_bounding_box
                x = int(bbox.xmin * w)
                y = int(bbox.ymin * h)
                bw = int(bbox.width * w)
                bh = int(bbox.height * h)

                # Dibujar bounding box estilizado
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
                # Esquinas reforzadas
                line_len = int(min(bw, bh) * 0.2)
                cv2.line(frame, (x, y), (x + line_len, y), (0, 255, 255), 4)
                cv2.line(frame, (x, y), (x, y + line_len), (0, 255, 255), 4)
                cv2.line(frame, (x + bw, y), (x + bw - line_len, y), (0, 255, 255), 4)
                cv2.line(frame, (x + bw, y), (x + bw, y + line_len), (0, 255, 255), 4)

                # Etiqueta de confianza
                tag = f"Rostro #{i+1}: {int(score * 100)}%"
                cv2.rectangle(frame, (x, max(0, y - 28)), (x + 160, y), (0, 255, 0), -1)
                cv2.putText(frame, tag, (x + 8, max(18, y - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

                # Puntos clave (Keypoints: Ojos, Nariz, Boca, Orejas)
                for kp in detection.location_data.relative_keypoints:
                    kpx = int(kp.x * w)
                    kpy = int(kp.y * h)
                    cv2.circle(frame, (kpx, kpy), 4, (0, 0, 255), -1)

    # -------------------------------------------------------------------------
    # PROCESAMIENTO MODO 6: SEGMENTACIÓN DE SELFIE (DESENFOQUE DE FONDO)
    # -------------------------------------------------------------------------
    def procesar_segmentacion(self, frame, rgb_frame):
        results = self.segmentation.process(rgb_frame)
        mask = results.segmentation_mask  # Máscara flotante [0.0, 1.0]

        # Umbral para separar persona del fondo
        condicion = mask > 0.4
        condicion_3ch = np.stack((condicion,) * 3, axis=-1)

        # Fondo desenfocado (efecto bokeh cinematográfico)
        fondo_borroso = cv2.GaussianBlur(frame, (55, 55), 0)

        # Combinar persona nítida con fondo borroso
        output = np.where(condicion_3ch, frame, fondo_borroso)
        np.copyto(frame, output)

        cv2.putText(frame, "FONDO DESENFOCADO (SELFIE SEGMENTATION)", (30, frame.shape[0] - 35),
                    cv2.FONT_HERSHEY_DUPLEX, 0.75, (0, 255, 255), 2)

    # -------------------------------------------------------------------------
    # DIBUJO DEL HUD (INTERFAZ GRAFICA SUPERIOR)
    # -------------------------------------------------------------------------
    def dibujar_hud(self, frame, fps):
        h, w, _ = frame.shape
        if not self.mostrar_hud:
            return

        # 1. Barra superior translúcida
        dibujar_rect_redondeado_translucido(frame, (10, 10), (w - 10, 75), (15, 15, 25), alpha=0.82)

        # 2. Título y Modo Activo
        cv2.putText(frame, "MEDIAPIPE MULTIMODAL SUITE", (25, 34),
                    cv2.FONT_HERSHEY_DUPLEX, 0.65, (0, 220, 255), 2)
        cv2.putText(frame, f"Modo activo: {self.MODOS[self.modo_actual]}", (25, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)

        # 3. FPS y Estado
        fps_text = f"FPS: {int(fps)}"
        cv2.putText(frame, fps_text, (w - 130, 36),
                    cv2.FONT_HERSHEY_DUPLEX, 0.65, (0, 255, 120), 2)
        espejo_text = "ESPEJO: ON" if self.es_espejo else "ESPEJO: OFF"
        cv2.putText(frame, espejo_text, (w - 145, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1)

        # 4. Barra de Ayuda / Atajos de Teclado en la parte inferior izquierda
        dibujar_rect_redondeado_translucido(frame, (10, h - 85), (580, h - 10), (10, 10, 20), alpha=0.75)
        cv2.putText(frame, "TECLAS: [1] Holistic | [2] Dedos Pro | [3] Pose | [4] Rostro | [5] Cajas | [6] Blur",
                    (20, h - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
        cv2.putText(frame, "[M] Alternar Espejo  |  [H] Ocultar HUD  |  [S] Tomar Foto  |  [Q/ESC] Salir",
                    (20, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1)

    # -------------------------------------------------------------------------
    # BUCLE PRINCIPAL DE EJECUCIÓN
    # -------------------------------------------------------------------------
    def ejecutar(self):
        cap = self.abrir_fuente_video()
        if not cap.isOpened():
            print("\n[ERROR CRITICO] No se pudo acceder a la camara web.")
            print("Verifica que ninguna otra aplicacion (Zoom, Teams, etc.) este usando la camara.")
            print("Tambien puedes probar con otro indice ejecutando: python detector_mediapipe.py --camera 1")
            return

        print("\n" + "=" * 65)
        print(" SISTEMA DE DETECCION MULTIMODAL MEDIAPIPE INICIADO")
        print(" Presiona [1] a [6] para alternar entre todas las modalidades.")
        print(" Presiona [Q] o [ESC] en la ventana de video para salir.")
        print("=" * 65 + "\n")

        prev_time = time.time()
        fps = 30.0

        cv2.namedWindow("MediaPipe Suite - Detector de Dedos y Vision", cv2.WINDOW_NORMAL)

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    print("[AVISO] No se pudo recibir frame de la camara o termino el video.")
                    break

                # Efecto Espejo si está activado
                if self.es_espejo:
                    frame = cv2.flip(frame, 1)

                # Calcular FPS
                curr_time = time.time()
                time_diff = curr_time - prev_time
                if time_diff > 0:
                    fps = 0.9 * fps + 0.1 * (1.0 / time_diff)
                prev_time = curr_time

                # Convertir BGR a RGB para MediaPipe
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb_frame.flags.writeable = False

                # Ejecutar el modo seleccionado
                if self.modo_actual == 1:
                    self.procesar_holistic(frame, rgb_frame)
                elif self.modo_actual == 2:
                    self.procesar_manos_dedos(frame, rgb_frame)
                elif self.modo_actual == 3:
                    self.procesar_pose(frame, rgb_frame)
                elif self.modo_actual == 4:
                    self.procesar_face_mesh(frame, rgb_frame)
                elif self.modo_actual == 5:
                    self.procesar_face_detection(frame, rgb_frame)
                elif self.modo_actual == 6:
                    self.procesar_segmentacion(frame, rgb_frame)

                rgb_frame.flags.writeable = True

                # Dibujar Interfaz HUD
                self.dibujar_hud(frame, fps)

                # Mostrar ventana
                cv2.imshow("MediaPipe Suite - Detector de Dedos y Vision", frame)

                # Manejo de teclas
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == ord('Q') or key == 27:  # 27 es ESC
                    print("[INFO] Saliendo del programa...")
                    break
                elif key in [ord('1'), ord('2'), ord('3'), ord('4'), ord('5'), ord('6')]:
                    nuevo_modo = int(chr(key))
                    self.modo_actual = nuevo_modo
                    print(f"[CAMBIO DE MODO] -> {self.MODOS[nuevo_modo]}")
                elif key == ord('m') or key == ord('M'):
                    self.es_espejo = not self.es_espejo
                    print(f"[CONFIG] Modo espejo: {'Activado' if self.es_espejo else 'Desactivado'}")
                elif key == ord('h') or key == ord('H'):
                    self.mostrar_hud = not self.mostrar_hud
                elif key == ord('s') or key == ord('S'):
                    nombre_foto = f"captura_mediapipe_{int(time.time())}.jpg"
                    cv2.imwrite(nombre_foto, frame)
                    print(f"[OK] Captura guardada como '{nombre_foto}'")

        except KeyboardInterrupt:
            print("\n[INFO] Interrupción por teclado detectada.")
        finally:
            cap.release()
            cv2.destroyAllWindows()
            self.holistic.close()
            self.hands.close()
            self.pose.close()
            self.face_mesh.close()
            self.face_detection.close()
            self.segmentation.close()
            print("[INFO] Recursos de camara y MediaPipe liberados correctamente.")

# =============================================================================
# PUNTO DE ENTRADA CLI
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="Detector Multimodal MediaPipe con Conteo de Dedos y Gestos")
    parser.add_argument("--camera", type=int, default=0, help="Indice de camara web (por defecto 0)")
    parser.add_argument("--video", type=str, default=None, help="Ruta a archivo de video para procesar en vez de camara")
    parser.add_argument("--width", type=int, default=1280, help="Ancho de resolucion de captura (def: 1280)")
    parser.add_argument("--height", type=int, default=720, help="Alto de resolucion de captura (def: 720)")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    app = MediaPipeMultimodalApp(
        camera_idx=args.camera,
        video_path=args.video,
        width=args.width,
        height=args.height
    )
    app.ejecutar()
