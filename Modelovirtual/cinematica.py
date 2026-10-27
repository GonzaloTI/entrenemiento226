"""
=============================================================================
  CINEMÁTICA Y CÁLCULO DE ÁNGULOS 3D (CON SOPORTE DE CALIBRACIÓN)
=============================================================================
- Si existe 'calibracion_mano.json', utiliza los límites medidos personalmente
  del usuario (distancia abierto/cerrado por dedo) para mapear el 0% a 100%
  de flexión con máxima precisión.
- Si no existe, utiliza el cálculo estándar basado en ángulos articulares.
=============================================================================
"""

import os
import json
import math
import numpy as np

RUTA_CALIBRACION = os.path.join(os.path.dirname(__file__), "calibracion_mano.json")

def cargar_calibracion():
    """Carga los límites calibrados si el archivo JSON existe."""
    if os.path.exists(RUTA_CALIBRACION):
        try:
            with open(RUTA_CALIBRACION, "r", encoding="utf-8") as f:
                datos = json.load(f)
                return datos.get("dedos", None)
        except Exception:
            return None
    return None

def vector(p1, p2):
    return np.array([p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]], dtype=float)

def angulo_entre_vectores(v1, v2):
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    cos_theta = np.dot(v1, v2) / (norm1 * norm2)
    cos_theta = np.clip(cos_theta, -1.0, 1.0)
    return math.degrees(math.acos(cos_theta))

def calcular_flexion_3puntos(a, b, c):
    v_in = vector(b, a)
    v_out = vector(b, c)
    ang = angulo_entre_vectores(v_in, v_out)
    flexion = 180.0 - ang
    return float(np.clip(flexion, 0.0, 105.0))

def orientacion_palma(lm):
    """Calcula la orientación global de la palma (Pitch, Yaw, Roll)."""
    p_wrist = np.array([lm[0].x, -lm[0].y, -lm[0].z])
    p_index = np.array([lm[5].x, -lm[5].y, -lm[5].z])
    p_pinky = np.array([lm[17].x, -lm[17].y, -lm[17].z])
    p_mid   = np.array([lm[9].x, -lm[9].y, -lm[9].z])

    v_forward = p_mid - p_wrist
    norm_f = np.linalg.norm(v_forward)
    if norm_f > 0:
        v_forward /= norm_f

    v_right = p_index - p_pinky
    norm_r = np.linalg.norm(v_right)
    if norm_r > 0:
        v_right /= norm_r

    v_normal = np.cross(v_forward, v_right)
    norm_n = np.linalg.norm(v_normal)
    if norm_n > 0:
        v_normal /= norm_n

    pitch = math.degrees(math.asin(np.clip(-v_forward[1], -1.0, 1.0)))
    yaw = math.degrees(math.atan2(v_forward[0], v_forward[2]))
    roll = math.degrees(math.atan2(v_right[1], v_normal[1]))

    return {
        "pitch": float(pitch),
        "yaw": float(yaw),
        "roll": float(roll)
    }

def procesar_landmarks_a_angulos(landmarks_list):
    """Calcula los ángulos combinando calibración personalizada (si existe) y cinemática."""
    pts = [[lm.x, lm.y, lm.z] for lm in landmarks_list]
    calib = cargar_calibracion()

    p_wrist = np.array(pts[0])
    p_ref_mid = np.array(pts[9])
    ref_palma = np.linalg.norm(p_wrist - p_ref_mid)
    if ref_palma == 0:
        ref_palma = 1.0

    if calib:
        # --- MODO CALIBRADO (Límites personalizados del usuario) ---
        angulos_dedos = {}

        mapping_dedos = {
            "indice":  (5, 8),
            "medio":   (9, 12),
            "anular":  (13, 16),
            "menique": (17, 20),
        }

        for nom, (id_mcp, id_tip) in mapping_dedos.items():
            dist_norm = np.linalg.norm(np.array(pts[id_tip]) - np.array(pts[id_mcp])) / ref_palma
            limites = calib.get(nom, {"dist_abierto": 1.4, "dist_cerrado": 0.5})
            d_open = limites["dist_abierto"]
            d_close = limites["dist_cerrado"]

            # Factor de 0.0 (abierto) a 1.0 (cerrado)
            denom = d_open - d_close if (d_open - d_close) > 0.05 else 0.5
            k = float(np.clip((d_open - dist_norm) / denom, 0.0, 1.0))

            angulos_dedos[nom] = {
                "base":  k * 80.0,
                "medio": k * 85.0,
                "punta": k * 70.0,
                "curl":  k
            }

        # Pulgar calibrado
        lim_pulgar = calib.get("pulgar", {"dist_abierto": 1.3, "dist_cerrado": 0.5})
        d_p_open = lim_pulgar["dist_abierto"]
        d_p_close = lim_pulgar["dist_cerrado"]
        dist_pulgar_pinky = np.linalg.norm(np.array(pts[4]) - np.array(pts[17])) / ref_palma
        denom_p = d_p_open - d_p_close if (d_p_open - d_p_close) > 0.05 else 0.5
        kp = float(np.clip((d_p_open - dist_pulgar_pinky) / denom_p, 0.0, 1.0))

        angulos_dedos["pulgar"] = {
            "base":  kp * 45.0,
            "medio": kp * 60.0,
            "punta": kp * 50.0,
            "curl":  kp
        }

        return {
            "palma": orientacion_palma(landmarks_list),
            "dedos": angulos_dedos,
            "calibrado": True
        }

    else:
        # --- MODO ESTÁNDAR POR ÁNGULOS (Sin calibración previa) ---
        return {
            "palma": orientacion_palma(landmarks_list),
            "dedos": {
                "pulgar": {
                    "base": calcular_flexion_3puntos(pts[0], pts[1], pts[2]),
                    "medio": calcular_flexion_3puntos(pts[1], pts[2], pts[3]),
                    "punta": calcular_flexion_3puntos(pts[2], pts[3], pts[4]),
                },
                "indice": {
                    "base": calcular_flexion_3puntos(pts[0], pts[5], pts[6]),
                    "medio": calcular_flexion_3puntos(pts[5], pts[6], pts[7]),
                    "punta": calcular_flexion_3puntos(pts[6], pts[7], pts[8]),
                },
                "medio": {
                    "base": calcular_flexion_3puntos(pts[0], pts[9], pts[10]),
                    "medio": calcular_flexion_3puntos(pts[9], pts[10], pts[11]),
                    "punta": calcular_flexion_3puntos(pts[10], pts[11], pts[12]),
                },
                "anular": {
                    "base": calcular_flexion_3puntos(pts[0], pts[13], pts[14]),
                    "medio": calcular_flexion_3puntos(pts[13], pts[14], pts[15]),
                    "punta": calcular_flexion_3puntos(pts[14], pts[15], pts[16]),
                },
                "menique": {
                    "base": calcular_flexion_3puntos(pts[0], pts[17], pts[18]),
                    "medio": calcular_flexion_3puntos(pts[17], pts[18], pts[19]),
                    "punta": calcular_flexion_3puntos(pts[18], pts[19], pts[20]),
                }
            },
            "calibrado": False
        }
