"""
=============================================================================
  CALIBRADOR INTERACTIVO DE LÍMITES DE MOVIMIENTO (MEDIAPIPE -> BLENDER 3D)
=============================================================================
Este script guía al usuario paso a paso para calibrar los límites EXACTOS
de su mano frente a su cámara web:

Paso 1: Mano Abierta (Extensión máxima de los 5 dedos).
Paso 2: Puño Cerrado (Flexión máxima de todos los dedos).
Paso 3: Paz y Victoria (Aislamiento de dedos índice/medio vs anular/meñique).
Paso 4: Pulgar Cerrado a la Palma (Límite de aducción del pulgar).

Guarda un archivo 'calibracion_mano.json' con los rangos mínimos y máximos
reales para que 'visor_ursina.py' mueva la mano con precisión milimétrica.
=============================================================================
"""

import os
import sys
import time
import json
import math
import cv2
# pyrefly: ignore [missing-import]
import mediapipe as mp
import numpy as np

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

try:
    from detector_dedos import abrir_dispositivo_camara, probar_camara
except ImportError:
    from .detector_dedos import abrir_dispositivo_camara, probar_camara

ARCHIVO_CALIBRACION = os.path.join(os.path.dirname(__file__), "calibracion_mano.json")

# Índices de MediaPipe para cada dedo: [MCP, PIP, DIP, TIP]
DEDOS_IDS = {
    "pulgar":  [1, 2, 3, 4],
    "indice":  [5, 6, 7, 8],
    "medio":   [9, 10, 11, 12],
    "anular":  [13, 14, 15, 16],
    "menique": [17, 18, 19, 20],
}

PASOS_CALIBRACION = [
    {
        "titulo": "PASO 1/4: MANO COMPLETAMENTE ABIERTA",
        "descripcion": "Extiende todos los dedos lo mas rectos posible",
        "duracion_cuenta": 3.0,
        "tipo": "abierta"
    },
    {
        "titulo": "PASO 2/4: PUNO COMPLETAMENTE CERRADO",
        "descripcion": "Aprieta todos los dedos formando un puno cerrado",
        "duracion_cuenta": 3.0,
        "tipo": "cerrada"
    },
    {
        "titulo": "PASO 3/4: PAZ Y VICTORIA (DOS DEDOS)",
        "descripcion": "Indice y Medio extendidos, demas cerrados",
        "duracion_cuenta": 3.0,
        "tipo": "victoria"
    },
    {
        "titulo": "PASO 4/4: PULGAR DOBLADO A LA PALMA",
        "descripcion": "Toca la base del dedo menique con la punta del pulgar",
        "duracion_cuenta": 3.0,
        "tipo": "pulgar_cerrado"
    }
]

def distancia_3d(p1, p2):
    return math.sqrt((p2.x - p1.x)**2 + (p2.y - p1.y)**2 + (p2.z - p1.z)**2)

def main():
    print("\n" + "=" * 65)
    print("   CALIBRADOR DE MOVIMIENTOS Y RANGOS REALES DE MEDIAPIPE")
    print("=" * 65)
    print(" Este asistente calibrara los limites de tu mano en 4 pasos.")
    print(" Controles:")
    print("   [C] : Cambiar camara (Laptop <-> USB)")
    print("   [M] : Alternar modo espejo")
    print("   [Q] : Cancelar y salir")
    print("=" * 65 + "\n")

    cam_idx = 1 if probar_camara(1) else 0
    cap = abrir_dispositivo_camara(cam_idx)
    if cap is None:
        print("[ERROR] No se pudo abrir camara 0 ni 1.")
        return

    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.5
    )

    es_espejo = True
    paso_actual = 0
    num_pasos = len(PASOS_CALIBRACION)

    # Estado del temporizador por paso
    inicio_cuenta = None
    tiempo_cuenta = 3.0
    muestras_paso = []
    num_muestras_requeridas = 25  # ~0.8 segundos de muestras promediadas

    datos_calibracion_crudos = {
        "abierta": [],
        "cerrada": [],
        "victoria": [],
        "pulgar_cerrado": []
    }

    mano_etiqueta_detectada = "Desconocida"

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if es_espejo:
            frame = cv2.flip(frame, 1)

        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = hands.process(rgb)
        rgb.flags.writeable = True

        mano_presente = False
        hand_lms = None

        if results.multi_hand_landmarks and results.multi_handedness:
            mano_presente = True
            hand_lms = results.multi_hand_landmarks[0]
            handedness = results.multi_handedness[0]
            mano_etiqueta_detectada = handedness.classification[0].label

            mp_drawing.draw_landmarks(
                frame,
                hand_lms,
                mp_hands.HAND_CONNECTIONS,
                landmark_drawing_spec=mp_drawing.DrawingSpec(color=(0, 255, 255), thickness=2, circle_radius=3),
                connection_drawing_spec=mp_drawing.DrawingSpec(color=(0, 255, 120), thickness=2)
            )

        # Encabezado visual
        cv2.rectangle(frame, (10, 10), (w - 10, 110), (20, 24, 32), -1)
        cv2.rectangle(frame, (10, 10), (w - 10, 110), (0, 255, 200), 1)

        info_paso = PASOS_CALIBRACION[paso_actual]
        cv2.putText(frame, info_paso["titulo"], (25, 42),
                    cv2.FONT_HERSHEY_DUPLEX, 0.75, (0, 255, 200), 2)
        cv2.putText(frame, info_paso["descripcion"], (25, 72),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.putText(frame, f"Cam {cam_idx} [C] | Espejo [M] | Salir [Q]", (w - 380, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 190, 200), 1)

        # Lógica del temporizador y muestreo
        t_ahora = time.time()
        tipo_actual = info_paso["tipo"]

        if not mano_presente:
            inicio_cuenta = None
            muestras_paso.clear()
            cv2.putText(frame, "COLOCA TU MANO FRENTE A LA CAMARA PARA COMENZAR",
                        (25, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (120, 140, 255), 1)
        else:
            if inicio_cuenta is None:
                inicio_cuenta = t_ahora

            tiempo_transcurrido = t_ahora - inicio_cuenta
            tiempo_restante = max(0.0, tiempo_cuenta - tiempo_transcurrido)

            if tiempo_restante > 0:
                # Barra de progreso de cuenta regresiva
                pct = 1.0 - (tiempo_restante / tiempo_cuenta)
                cv2.rectangle(frame, (25, 88), (w - 25, 102), (40, 45, 55), -1)
                cv2.rectangle(frame, (25, 88), (25 + int((w - 50) * pct), 102), (0, 255, 150), -1)
                cv2.putText(frame, f"Mantente quieto... Registrando en {tiempo_restante:.1f}s",
                            (25 + int((w - 50) * pct) + 10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 200), 1)
            else:
                # Tomar muestras del esqueleto
                lm = hand_lms.landmark
                ref_palma = distancia_3d(lm[0], lm[9])
                if ref_palma == 0:
                    ref_palma = 1.0

                # Registrar distancias normalizadas por escala de la palma
                sample = {
                    "ref_palma": ref_palma,
                    "indice_mcp_tip": distancia_3d(lm[5], lm[8]) / ref_palma,
                    "medio_mcp_tip":  distancia_3d(lm[9], lm[12]) / ref_palma,
                    "anular_mcp_tip": distancia_3d(lm[13], lm[16]) / ref_palma,
                    "menique_mcp_tip":distancia_3d(lm[17], lm[20]) / ref_palma,
                    "pulgar_wrist_tip":distancia_3d(lm[0], lm[4]) / ref_palma,
                    "pulgar_mcp_tip": distancia_3d(lm[2], lm[4]) / ref_palma,
                    "pulgar_pinky":   distancia_3d(lm[4], lm[17]) / ref_palma,
                }
                muestras_paso.append(sample)

                # Efecto visual de captura
                cv2.putText(frame, f"[CAPTURANDO DATOS... {len(muestras_paso)}/{num_muestras_requeridas}]",
                            (25, 102), cv2.FONT_HERSHEY_DUPLEX, 0.55, (0, 255, 100), 1)

                if len(muestras_paso) >= num_muestras_requeridas:
                    datos_calibracion_crudos[tipo_actual] = list(muestras_paso)
                    print(f"[OK] {info_paso['titulo']} capturado con éxito.")
                    paso_actual += 1
                    inicio_cuenta = None
                    muestras_paso.clear()

                    if paso_actual >= num_pasos:
                        print("\n=== CALIBRACIÓN COMPLETADA CON ÉXITO ===")
                        break

        cv2.imshow("Calibrador de Movimientos - MediaPipe", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27 or key == ord('q'):
            print("[CANCELADO] Calibración cancelada por el usuario.")
            cap.release()
            cv2.destroyAllWindows()
            hands.close()
            return
        elif key == ord('c') or key == ord('C'):
            siguiente = 0 if cam_idx == 1 else 1
            print(f"[CAMBIO] Cambiando a Cámara {siguiente}...")
            test_cap = abrir_dispositivo_camara(siguiente)
            if test_cap is not None:
                cap.release()
                cap = test_cap
                cam_idx = siguiente
        elif key == ord('m') or key == ord('M'):
            es_espejo = not es_espejo

    cap.release()
    cv2.destroyAllWindows()
    hands.close()

    # Procesar y calcular los límites exactos
    print("\nProcesando límites de movimiento para tu mano...")
    abiertas = datos_calibracion_crudos["abierta"]
    cerradas = datos_calibracion_crudos["cerrada"]
    pulgar_c = datos_calibracion_crudos["pulgar_cerrado"]

    def promedio(lista, clave):
        vals = [s[clave] for s in lista]
        return float(np.mean(vals)) if vals else 1.0

    calibracion_final = {
        "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mano_detectada": mano_etiqueta_detectada,
        "camara_index": cam_idx,
        "dedos": {
            "indice": {
                "dist_abierto": round(promedio(abiertas, "indice_mcp_tip"), 4),
                "dist_cerrado": round(promedio(cerradas, "indice_mcp_tip"), 4),
            },
            "medio": {
                "dist_abierto": round(promedio(abiertas, "medio_mcp_tip"), 4),
                "dist_cerrado": round(promedio(cerradas, "medio_mcp_tip"), 4),
            },
            "anular": {
                "dist_abierto": round(promedio(abiertas, "anular_mcp_tip"), 4),
                "dist_cerrado": round(promedio(cerradas, "anular_mcp_tip"), 4),
            },
            "menique": {
                "dist_abierto": round(promedio(abiertas, "menique_mcp_tip"), 4),
                "dist_cerrado": round(promedio(cerradas, "menique_mcp_tip"), 4),
            },
            "pulgar": {
                "dist_abierto": round(promedio(abiertas, "pulgar_pinky"), 4),
                "dist_cerrado": round(promedio(pulgar_c, "pulgar_pinky"), 4),
            }
        }
    }

    # Guardar en archivo JSON
    with open(ARCHIVO_CALIBRACION, "w", encoding="utf-8") as f:
        json.dump(calibracion_final, f, indent=4)

    print("\n" + "=" * 65)
    print(f" [LISTO] Calibración guardada exitosamente en:")
    print(f"   {ARCHIVO_CALIBRACION}")
    print("=" * 65)
    print(" Límites registrados:")
    for d, info in calibracion_final["dedos"].items():
        print(f"   - {d.capitalize():<8}: Abierto={info['dist_abierto']:.3f} | Cerrado={info['dist_cerrado']:.3f}")
    print("=" * 65)
    print(" Ahora 'visor_ursina.py' se ajustará exactamente a estos límites.")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    main()
