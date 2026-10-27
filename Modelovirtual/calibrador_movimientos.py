"""
=============================================================================
  CALIBRADOR COMPLETO DE ARTICULACIONES DE MANO (MediaPipe → Modelo 3D)
=============================================================================
Captura los ÁNGULOS REALES de flexión en cada articulación de cada dedo:

  Cada dedo tiene 3 articulaciones que se miden:
    · base  → Nudillo base    (MCP): ángulo en lm[MCP] entre muñeca y PIP
    · medio → Nudillo medio   (PIP): ángulo en lm[PIP] entre MCP y DIP
    · punta → Nudillo distal  (DIP): ángulo en lm[DIP] entre PIP y TIP

  Cadena de landmarks por dedo (MediaPipe):
    Pulgar : 0→1→2→3→4    (Muñeca→CMC→MCP→IP→TIP)
    Índice : 0→5→6→7→8    (Muñeca→MCP→PIP→DIP→TIP)
    Medio  : 0→9→10→11→12
    Anular : 0→13→14→15→16
    Meñique: 0→17→18→19→20

PASOS:
  1. Mano completamente ABIERTA  → límite mínimo de flexión (~0°)
  2. Puño completamente CERRADO  → límite máximo de flexión (~90°)
  3. Pulgar cerrado sobre palma  → límite de aducción del pulgar

Genera 'calibracion_mano.json' v2.0 con angulo_abierto/angulo_cerrado
por articulación, para que cinematica.py mapee con exactitud real.
=============================================================================
"""

import os
import sys
import time
import json
import math
import cv2
import mediapipe as mp
import numpy as np

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

try:
    from detector_dedos import abrir_dispositivo_camara, probar_camara
except ImportError:
    from .detector_dedos import abrir_dispositivo_camara, probar_camara

ARCHIVO_CALIBRACION = os.path.join(os.path.dirname(__file__), "calibracion_mano.json")

# ─────────────────────────────────────────────────────────────────────────────
# MAPA DE ARTICULACIONES
# Para cada dedo: (punto_anterior, articulacion_central, punto_siguiente)
# El angulo se mide EN la articulacion central.
# ─────────────────────────────────────────────────────────────────────────────
ARTICULACIONES = {
    "pulgar": {
        "base":  (0,  1,  2),   # Muneca -> CMC -> MCP
        "medio": (1,  2,  3),   # CMC    -> MCP -> IP
        "punta": (2,  3,  4),   # MCP    -> IP  -> TIP
    },
    "indice": {
        "base":  (0,  5,  6),   # Muneca -> MCP -> PIP
        "medio": (5,  6,  7),   # MCP    -> PIP -> DIP
        "punta": (6,  7,  8),   # PIP    -> DIP -> TIP
    },
    "medio": {
        "base":  (0,  9,  10),
        "medio": (9,  10, 11),
        "punta": (10, 11, 12),
    },
    "anular": {
        "base":  (0,  13, 14),
        "medio": (13, 14, 15),
        "punta": (14, 15, 16),
    },
    "menique": {
        "base":  (0,  17, 18),
        "medio": (17, 18, 19),
        "punta": (18, 19, 20),
    },
}

PASOS = [
    {
        "id":         "abierta",
        "titulo":     "PASO 1/3 -- MANO TOTALMENTE ABIERTA",
        "instruccion":"Extiende todos los dedos lo mas rectos posible",
        "color":      (0, 255, 180),
        "duracion":   3.5,
        "muestras":   30,
    },
    {
        "id":         "cerrada",
        "titulo":     "PASO 2/3 -- PUNO COMPLETAMENTE CERRADO",
        "instruccion":"Aprieta todos los dedos formando un puno firme",
        "color":      (0, 180, 255),
        "duracion":   3.5,
        "muestras":   30,
    },
    {
        "id":         "pulgar_cerrado",
        "titulo":     "PASO 3/3 -- PULGAR CERRADO SOBRE PALMA",
        "instruccion":"Toca la base del menique con la punta del pulgar",
        "color":      (255, 200, 0),
        "duracion":   3.5,
        "muestras":   30,
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# GEOMETRIA
# ─────────────────────────────────────────────────────────────────────────────
def lm_a_np(lm, idx):
    return np.array([lm[idx].x, lm[idx].y, lm[idx].z], dtype=float)


def angulo_articulacion(lm, a_idx, b_idx, c_idx):
    """
    Flexion en la articulacion B entre los segmentos A->B y B->C.
    0° = extendido recto, ~90° = completamente doblado.
    """
    a = lm_a_np(lm, a_idx)
    b = lm_a_np(lm, b_idx)
    c = lm_a_np(lm, c_idx)

    v_in  = b - a
    v_out = c - b

    n_in  = np.linalg.norm(v_in)
    n_out = np.linalg.norm(v_out)
    if n_in < 1e-9 or n_out < 1e-9:
        return 0.0

    cos_t = float(np.clip(np.dot(v_in, v_out) / (n_in * n_out), -1.0, 1.0))
    ang_grados = math.degrees(math.acos(cos_t))
    flexion = 180.0 - ang_grados
    return float(np.clip(flexion, 0.0, 120.0))


def medir_muestra(lm):
    """Devuelve dict {dedo: {seg: angulo_flexion}}."""
    muestra = {}
    for dedo, segs in ARTICULACIONES.items():
        muestra[dedo] = {}
        for seg, (a, b, c) in segs.items():
            muestra[dedo][seg] = angulo_articulacion(lm, a, b, c)
    return muestra


def promedio_muestras(lista):
    if not lista:
        return {}
    res = {}
    for dedo in ARTICULACIONES:
        res[dedo] = {}
        for seg in ARTICULACIONES[dedo]:
            vals = [m[dedo][seg] for m in lista]
            res[dedo][seg] = float(np.mean(vals))
    return res


# ─────────────────────────────────────────────────────────────────────────────
# DIBUJO DE INTERFAZ
# ─────────────────────────────────────────────────────────────────────────────
FUENTE   = cv2.FONT_HERSHEY_DUPLEX
FUENTE_M = cv2.FONT_HERSHEY_SIMPLEX


def dibujar_barra_progreso(frame, pct, y, color, w):
    bw = w - 60
    cv2.rectangle(frame, (30, y), (30 + bw, y + 18), (30, 35, 45), -1)
    fill = int(bw * min(max(pct, 0.0), 1.0))
    cv2.rectangle(frame, (30, y), (30 + fill, y + 18), color, -1)
    cv2.rectangle(frame, (30, y), (30 + bw, y + 18), (80, 90, 100), 1)


def dibujar_tabla_angulos(frame, muestras, h, w):
    """Tabla de angulos en tiempo real en la parte inferior del frame."""
    if not muestras:
        return
    ultima = muestras[-1]
    x0 = 20
    y0 = h - 185

    cv2.rectangle(frame, (x0 - 5, y0 - 22), (x0 + 390, y0 + 145), (12, 15, 22), -1)
    cv2.rectangle(frame, (x0 - 5, y0 - 22), (x0 + 390, y0 + 145), (55, 65, 78), 1)
    cv2.putText(frame, "  DEDO      BASE    MEDIO    PUNTA   (angulos flexion °)",
                (x0 + 5, y0 - 6), FUENTE_M, 0.37, (130, 140, 160), 1)

    dedos_orden = ["indice", "medio", "anular", "menique", "pulgar"]
    etiquetas   = ["INDICE", "MEDIO ", "ANULAR", "MENIQUE", "PULGAR"]

    for row, (dedo, etiq) in enumerate(zip(dedos_orden, etiquetas)):
        vals = ultima.get(dedo, {})
        b  = vals.get("base",  0.0)
        me = vals.get("medio", 0.0)
        p  = vals.get("punta", 0.0)

        def ang_col(v):
            g = int(min(v * 2.5, 255))
            r = int(min(v * 1.8, 255))
            return (0, g, 255 - r)

        y_row = y0 + 14 + row * 26
        cv2.putText(frame, etiq, (x0 + 8, y_row), FUENTE_M, 0.42, (195, 205, 220), 1)
        cv2.putText(frame, f"{b:6.1f}", (x0 + 90,  y_row), FUENTE_M, 0.44, ang_col(b),  1)
        cv2.putText(frame, f"{me:6.1f}", (x0 + 165, y_row), FUENTE_M, 0.44, ang_col(me), 1)
        cv2.putText(frame, f"{p:6.1f}", (x0 + 240, y_row), FUENTE_M, 0.44, ang_col(p),  1)

        # Mini barras verticales
        for xi_off, ang in [(310, b), (335, me), (360, p)]:
            xi = x0 + xi_off
            fill_h = int(min(ang / 110.0, 1.0) * 18)
            cv2.rectangle(frame, (xi, y_row - 14), (xi + 18, y_row + 4), (28, 32, 42), -1)
            cv2.rectangle(frame, (xi, y_row + 4 - fill_h), (xi + 18, y_row + 4),
                          (0, 200, 120), -1)
            cv2.rectangle(frame, (xi, y_row - 14), (xi + 18, y_row + 4), (55, 65, 78), 1)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "=" * 65)
    print("   CALIBRADOR COMPLETO DE ARTICULACIONES  v2.0")
    print("=" * 65)
    print(" Mide angulos reales de flexion en cada nudillo de tu mano.")
    print(" Controles: [C] Cambiar camara  [M] Espejo  [Q] Salir")
    print("=" * 65 + "\n")

    cam_idx = 1 if probar_camara(1) else 0
    cap = abrir_dispositivo_camara(cam_idx)
    if cap is None:
        print("[ERROR] No se pudo abrir camara 0 ni 1.")
        return

    mp_hands   = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.60,
        min_tracking_confidence=0.55,
    )

    es_espejo    = True
    paso_actual  = 0
    datos_crudos = {}
    muestras_paso = []
    inicio_cuenta = None
    mano_label    = "Desconocida"

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        if es_espejo:
            frame = cv2.flip(frame, 1)

        h, w, _ = frame.shape

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = hands.process(rgb)
        rgb.flags.writeable = True

        mano_ok  = False
        hand_lms = None
        if results.multi_hand_landmarks and results.multi_handedness:
            mano_ok    = True
            hand_lms   = results.multi_hand_landmarks[0]
            mano_label = results.multi_handedness[0].classification[0].label
            mp_drawing.draw_landmarks(
                frame, hand_lms, mp_hands.HAND_CONNECTIONS,
                landmark_drawing_spec=mp_drawing.DrawingSpec(
                    color=(0, 255, 255), thickness=2, circle_radius=4),
                connection_drawing_spec=mp_drawing.DrawingSpec(
                    color=(0, 255, 140), thickness=2),
            )

        paso = PASOS[paso_actual]
        col  = paso["color"]

        # Encabezado
        cv2.rectangle(frame, (10, 10), (w - 10, 122), (13, 16, 24), -1)
        cv2.rectangle(frame, (10, 10), (w - 10, 122), col, 2)
        cv2.putText(frame, paso["titulo"],     (25, 46),  FUENTE,   0.70, col, 2)
        cv2.putText(frame, paso["instruccion"],(25, 78),  FUENTE_M, 0.54, (230, 235, 245), 1)
        cv2.putText(frame,
                    f"Cam {cam_idx} {'(Espejo)' if es_espejo else ''} | "
                    "[C] Cam  [M] Espejo  [Q] Salir",
                    (25, 110), FUENTE_M, 0.38, (120, 130, 148), 1)

        t_ahora = time.time()

        if not mano_ok:
            inicio_cuenta = None
            muestras_paso.clear()
            cv2.putText(frame, ">>> Pon tu mano frente a la camara <<<",
                        (w // 2 - 220, h // 2),
                        FUENTE_M, 0.72, (80, 100, 255), 2)
        else:
            if inicio_cuenta is None:
                inicio_cuenta = t_ahora

            elapsed  = t_ahora - inicio_cuenta
            restante = max(0.0, paso["duracion"] - elapsed)

            if restante > 0:
                pct = 1.0 - restante / paso["duracion"]
                dibujar_barra_progreso(frame, pct, 132, col, w)
                cv2.putText(frame,
                            f"Mantente quieto... {restante:.1f}s",
                            (38, 148), FUENTE_M, 0.50, (215, 220, 232), 1)
            else:
                muestra = medir_muestra(hand_lms.landmark)
                muestras_paso.append(muestra)

                pct_capt = len(muestras_paso) / paso["muestras"]
                dibujar_barra_progreso(frame, pct_capt, 132, (0, 255, 100), w)
                cv2.putText(frame,
                            f"[CAPTURANDO] {len(muestras_paso)}/{paso['muestras']} muestras",
                            (38, 148), FUENTE, 0.55, (0, 255, 120), 1)

                if len(muestras_paso) >= paso["muestras"]:
                    datos_crudos[paso["id"]] = list(muestras_paso)
                    print(f"[OK] '{paso['titulo']}' capturado ({paso['muestras']} muestras).")
                    paso_actual   += 1
                    inicio_cuenta  = None
                    muestras_paso.clear()

                    if paso_actual >= len(PASOS):
                        print("\n=== CALIBRACION COMPLETA ===")
                        break

            dibujar_tabla_angulos(frame, muestras_paso, h, w)

        cv2.imshow("Calibrador de Articulaciones v2.0 - MediaPipe", frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord('q'), ord('Q')):
            print("[CANCELADO] Calibracion cancelada por el usuario.")
            cap.release(); cv2.destroyAllWindows(); hands.close()
            return
        elif key in (ord('c'), ord('C')):
            sig = 0 if cam_idx == 1 else 1
            test = abrir_dispositivo_camara(sig)
            if test is not None:
                cap.release(); cap = test; cam_idx = sig
                print(f"[CAMBIO] Camara activa: {sig}")
        elif key in (ord('m'), ord('M')):
            es_espejo = not es_espejo

    cap.release()
    cv2.destroyAllWindows()
    hands.close()

    # ── Calcular promedios y guardar ─────────────────────────────────────────
    print("\nCalculando promedios de articulaciones...")

    avg_abierta     = promedio_muestras(datos_crudos.get("abierta", []))
    avg_cerrada     = promedio_muestras(datos_crudos.get("cerrada", []))
    avg_pulgar_cerr = promedio_muestras(datos_crudos.get("pulgar_cerrado", []))

    calibracion_final = {
        "fecha":          time.strftime("%Y-%m-%d %H:%M:%S"),
        "version":        "2.0",
        "mano_detectada": mano_label,
        "camara_index":   cam_idx,
        "dedos":          {}
    }

    dedos_orden = ["indice", "medio", "anular", "menique", "pulgar"]
    for dedo in dedos_orden:
        calibracion_final["dedos"][dedo] = {}
        for seg in ["base", "medio", "punta"]:
            ang_open  = avg_abierta.get(dedo, {}).get(seg, 4.0)
            # Para el pulgar usamos el paso especifico de pulgar cerrado
            if dedo == "pulgar":
                ang_close = avg_pulgar_cerr.get("pulgar", {}).get(seg, 55.0)
            else:
                ang_close = avg_cerrada.get(dedo, {}).get(seg, 80.0)

            # Garantizar que ang_close > ang_open + margen minimo
            if ang_close <= ang_open + 5.0:
                ang_close = ang_open + 30.0

            calibracion_final["dedos"][dedo][seg] = {
                "angulo_abierto": round(ang_open,  2),
                "angulo_cerrado": round(ang_close, 2),
            }

    with open(ARCHIVO_CALIBRACION, "w", encoding="utf-8") as f:
        json.dump(calibracion_final, f, indent=4, ensure_ascii=False)

    # ── Resumen en consola ───────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f" [OK] Calibracion v2.0 guardada en:")
    print(f"   {ARCHIVO_CALIBRACION}")
    print("=" * 65)
    print(f" {'DEDO':<10} {'SEG':<7} {'ABIERTO':>9}  {'CERRADO':>9}  {'RANGO':>8}")
    print("-" * 65)
    for dedo in dedos_orden:
        for seg in ["base", "medio", "punta"]:
            d     = calibracion_final["dedos"][dedo][seg]
            rango = d["angulo_cerrado"] - d["angulo_abierto"]
            print(f" {dedo:<10} {seg:<7} {d['angulo_abierto']:>8.2f}°  "
                  f"{d['angulo_cerrado']:>8.2f}°  {rango:>7.2f}°")
    print("=" * 65)
    print(" Ahora visor_ursina.py usara angulos exactos por articulacion.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
