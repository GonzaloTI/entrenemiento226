"""
=============================================================================
  DETECTOR Y CONTADOR DE DEDOS EN VIVO CON MEDIAPIPE (HANDS & GESTURES)
=============================================================================
Script especializado y enfocado en la detección de dedos y manos:
  - Detecta hasta 2 manos simultáneamente (Izquierda y Derecha).
  - Reconoce el estado individual de cada uno de los 5 dedos (Arriba / Abajo).
  - Muestra el conteo de dedos por mano y el total en pantalla (0 a 10).
  - Reconoce gestos naturales:
      * Paz / Victoria
      * Pulgar arriba (Like) / Pulgar abajo (Dislike)
      * Puno cerrado / Mano abierta
      * Senalando con el indice
      * Rock / Heavy metal
      * Shaka / Surfer
      * Pistola (L)
      * Pellizco / Click (Gesto para seleccionar o interactuar)
  - Muestra coordenadas en tiempo real de las puntas de los dedos.

Controles:
  [M]       : Alternar vista espejo (Mirror)
  [S]       : Guardar foto / captura de pantalla
  [Q] o ESC : Salir
=============================================================================
"""

import os
import time
import math
import numpy as np

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import cv2
# pyrefly: ignore [missing-import]
import mediapipe as mp

PUNTAS_IDS = [4, 8, 12, 16, 20]  # Pulgar, Índice, Medio, Anular, Meñique
PIP_IDS = [2, 6, 10, 14, 18]     # Articulaciones intermedias
NOMBRES_DEDOS = ["Pulgar", "Indice", "Medio", "Anular", "Menique"]

def distancia_euclidiana(p1, p2):
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

def clasificar_dedos(puntos_px, mano_label, es_espejo=True):
    """
    Analiza los 21 landmarks de una mano para determinar qué dedos están extendidos.
    """
    estados = [0, 0, 0, 0, 0]

    # Dedos: Índice, Medio, Anular, Meñique (eje vertical Y)
    for i in range(1, 5):
        tip_y = puntos_px[PUNTAS_IDS[i]][1]
        pip_y = puntos_px[PIP_IDS[i]][1]
        if tip_y < pip_y:
            estados[i] = 1

    # --- 2. Detección precisa del Pulgar ---
    # Un pulgar levantado/extendido debe estar separado de la mano y no doblado hacia la palma o pegado al índice.
    p_tip_thumb = puntos_px[4]
    p_ip_thumb = puntos_px[3]
    p_mcp_thumb = puntos_px[2]
    p_wrist = puntos_px[0]
    p_index_mcp = puntos_px[5]
    p_index_pip = puntos_px[6]
    p_pinky_base = puntos_px[17]

    # Escala de referencia de la palma (muñeca a base de dedo medio)
    ref_escala = distancia_euclidiana(p_wrist, puntos_px[9])
    
    dist_tip_index_mcp = distancia_euclidiana(p_tip_thumb, p_index_mcp)
    dist_tip_index_pip = distancia_euclidiana(p_tip_thumb, p_index_pip)
    dist_tip_pinky = distancia_euclidiana(p_tip_thumb, p_pinky_base)
    dist_ip_pinky = distancia_euclidiana(p_ip_thumb, p_pinky_base)
    dist_tip_mcp = distancia_euclidiana(p_tip_thumb, p_mcp_thumb)
    dist_ip_mcp = distancia_euclidiana(p_ip_thumb, p_mcp_thumb)
    dist_tip_wrist = distancia_euclidiana(p_tip_thumb, p_wrist)
    dist_mcp_wrist = distancia_euclidiana(p_mcp_thumb, p_wrist)

    # 1. Si el pulgar está cerca de la mano (pegado al índice o al borde de la palma) -> ABAJO
    cerca_de_la_mano = (dist_tip_index_mcp < ref_escala * 0.44) or (dist_tip_index_pip < ref_escala * 0.35)

    # 2. Si el pulgar está doblado hacia la palma / meñique -> ABAJO
    doblado_hacia_palma = dist_tip_pinky < (dist_ip_pinky * 1.05)

    # 3. Si la punta está encogida respecto al nudillo MCP -> ABAJO
    encogido = dist_tip_mcp < (dist_ip_mcp * 1.15)

    pulgar_abierto = False
    if not cerca_de_la_mano and not encogido:
        # Caso A: Pulgar Arriba (Like) claramente vertical hacia arriba
        es_pulgar_arriba = (p_tip_thumb[1] < p_ip_thumb[1] < p_mcp_thumb[1]) and (dist_tip_wrist > dist_mcp_wrist * 1.2)

        # Caso B: Extensión lateral hacia afuera de la mano
        mano_rel = mano_label if es_espejo else ("Left" if mano_label == "Right" else "Right")
        if mano_rel == "Right":
            es_lateral = (p_tip_thumb[0] < p_ip_thumb[0]) and (p_tip_thumb[0] < p_mcp_thumb[0])
        else:
            es_lateral = (p_tip_thumb[0] > p_ip_thumb[0]) and (p_tip_thumb[0] > p_mcp_thumb[0])

        if es_pulgar_arriba:
            pulgar_abierto = True
        elif es_lateral and not doblado_hacia_palma:
            pulgar_abierto = True

    if pulgar_abierto:
        estados[0] = 1
    else:
        estados[0] = 0

    conteo = sum(estados)

    # Detección de Pellizco (Click)
    dist_pinch = distancia_euclidiana(puntos_px[4], puntos_px[8])
    ref_escala = distancia_euclidiana(puntos_px[0], puntos_px[9])
    pinch_activo = dist_pinch < max(24, int(ref_escala * 0.28))

    # Identificación de Gesto
    if pinch_activo:
        gesto = "Click / Pellizco"
    elif conteo == 0:
        gesto = "Puno cerrado"
    elif conteo == 5:
        gesto = "Mano abierta (5)"
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
        if p_tip_thumb[1] < p_wrist[1]:
            gesto = "Pulgar Arriba (Like)"
        else:
            gesto = "Pulgar Abajo (Dislike)"
    elif estados in ([0, 1, 0, 0, 1], [1, 1, 0, 0, 1]):
        gesto = "Rock / Heavy Metal"
    elif estados == [1, 0, 0, 0, 1]:
        gesto = "Shaka / Surfer"
    elif estados == [0, 0, 1, 0, 0]:
        gesto = "Dedo Medio"
    else:
        gesto = f"{conteo} dedos"

    return estados, conteo, gesto, pinch_activo, dist_pinch

def main():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("[ERROR] No se pudo abrir la camara web.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils

    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.5
    )

    es_espejo = True
    prev_time = time.time()
    fps = 30.0

    print("\n" + "=" * 55)
    print(" DETECTOR DE DEDOS Y GESTOS EN TIEMPO REAL INICIADO")
    print(" Presiona [M] para alternar espejo, [S] para guardar foto")
    print(" Presiona [Q] o [ESC] para salir")
    print("=" * 55 + "\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if es_espejo:
            frame = cv2.flip(frame, 1)

        h, w, _ = frame.shape

        # Medición de FPS
        t_actual = time.time()
        dt = t_actual - prev_time
        if dt > 0:
            fps = 0.9 * fps + 0.1 * (1.0 / dt)
        prev_time = t_actual

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        results = hands.process(rgb_frame)
        rgb_frame.flags.writeable = True

        total_dedos = 0

        # Encabezado
        cv2.rectangle(frame, (10, 10), (w - 10, 70), (20, 20, 30), -1)
        cv2.rectangle(frame, (10, 10), (w - 10, 70), (0, 255, 200), 1)
        cv2.putText(frame, "DETECTOR DE DEDOS Y GESTOS - MEDIAPIPE", (25, 38),
                    cv2.FONT_HERSHEY_DUPLEX, 0.65, (0, 255, 200), 2)
        cv2.putText(frame, f"FPS: {int(fps)} | Espejo: {'ON' if es_espejo else 'OFF'}", (w - 220, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

        panel_y = 90
        if results.multi_hand_landmarks and results.multi_handedness:
            for hand_landmarks, handedness in zip(results.multi_hand_landmarks, results.multi_handedness):
                etiqueta = handedness.classification[0].label
                puntos_px = [(int(lm.x * w), int(lm.y * h)) for lm in hand_landmarks.landmark]

                estados, conteo, gesto, pinch_activo, dist_pinch = clasificar_dedos(
                    puntos_px, etiqueta, es_espejo
                )
                total_dedos += conteo

                # Dibujar esqueleto de la mano
                mp_drawing.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS,
                    landmark_drawing_spec=mp_drawing.DrawingSpec(color=(0, 255, 255), thickness=2, circle_radius=3),
                    connection_drawing_spec=mp_drawing.DrawingSpec(color=(255, 140, 0), thickness=2)
                )

                # Resaltar puntas de los dedos
                for i, tip_id in enumerate(PUNTAS_IDS):
                    px, py = puntos_px[tip_id]
                    color_punto = (0, 255, 0) if estados[i] else (0, 0, 255)
                    cv2.circle(frame, (px, py), 9, color_punto, -1)
                    cv2.circle(frame, (px, py), 12, (255, 255, 255), 2)
                    cv2.putText(frame, str(estados[i]), (px - 4, py + 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)

                # Efecto de click/pellizco
                if pinch_activo:
                    mid = ((puntos_px[4][0] + puntos_px[8][0]) // 2, (puntos_px[4][1] + puntos_px[8][1]) // 2)
                    cv2.line(frame, puntos_px[4], puntos_px[8], (0, 255, 255), 3)
                    cv2.circle(frame, mid, 16, (0, 255, 255), -1)
                    cv2.putText(frame, "CLICK!", (mid[0] - 25, mid[1] - 20),
                                cv2.FONT_HERSHEY_DUPLEX, 0.65, (0, 255, 255), 2)

                # Tarjeta lateral de la mano
                cv2.rectangle(frame, (w - 280, panel_y), (w - 15, panel_y + 160), (25, 25, 35), -1)
                cv2.rectangle(frame, (w - 280, panel_y), (w - 15, panel_y + 160), (0, 255, 200), 1)
                cv2.putText(frame, f"MANO {etiqueta.upper()}: {conteo} Dedos", (w - 265, panel_y + 25),
                            cv2.FONT_HERSHEY_DUPLEX, 0.55, (0, 255, 200), 1)
                cv2.putText(frame, f"Gesto: {gesto}", (w - 265, panel_y + 48),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 100), 1)

                for i, nombre in enumerate(NOMBRES_DEDOS):
                    estado_str = "ARRIBA [1]" if estados[i] else "ABAJO [0]"
                    col = (0, 255, 0) if estados[i] else (120, 120, 255)
                    cv2.putText(frame, f"{nombre}: {estado_str}", (w - 265, panel_y + 72 + i * 17),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1)

                panel_y += 175

        # Barra inferior con total de dedos
        cv2.rectangle(frame, (10, h - 60), (450, h - 10), (20, 20, 30), -1)
        cv2.rectangle(frame, (10, h - 60), (450, h - 10), (0, 255, 200), 1)
        cv2.putText(frame, f"TOTAL DEDOS LEVANTADOS: {total_dedos}", (25, h - 25),
                    cv2.FONT_HERSHEY_DUPLEX, 0.7, (0, 255, 200), 2)

        cv2.imshow("Detector de Dedos - MediaPipe", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == ord('Q') or key == 27:
            break
        elif key == ord('m') or key == ord('M'):
            es_espejo = not es_espejo
        elif key == ord('s') or key == ord('S'):
            nombre = f"captura_dedos_{int(time.time())}.jpg"
            cv2.imwrite(nombre, frame)
            print(f"[OK] Captura guardada como '{nombre}'")

    cap.release()
    cv2.destroyAllWindows()
    hands.close()

if __name__ == "__main__":
    main()
