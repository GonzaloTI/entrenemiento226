"""
=============================================================================
  CINEMATICA Y CALCULO DE ANGULOS 3D (CON SOPORTE DE CALIBRACION v2.0)
=============================================================================
- v2.0: calibracion_mano.json tiene angulo_abierto/cerrado POR ARTICULACION.
  Cada segmento (base/MCP, medio/PIP, punta/DIP) se mapea de forma
  totalmente independiente con su rango real medido.
- v1.0 (retrocompatibilidad): si el JSON tiene formato antiguo (dist_abierto),
  usa el modo simplificado de distancia MCP-TIP.
- Sin calibracion: calculo geometrico estandar de angulos 3D.
=============================================================================
"""

import os
import json
import math
import numpy as np

RUTA_CALIBRACION = os.path.join(os.path.dirname(__file__), "calibracion_mano.json")

def cargar_calibracion():
    """Carga la calibracion del JSON. Retorna (datos_dedos, version) o (None, None)."""
    if os.path.exists(RUTA_CALIBRACION):
        try:
            with open(RUTA_CALIBRACION, "r", encoding="utf-8") as f:
                datos = json.load(f)
            version = datos.get("version", "1.0")
            return datos.get("dedos", None), version
        except Exception:
            return None, None
    return None, None

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
    """
    Angulo de flexion en la articulacion B entre segmentos A->B y B->C.
      0deg  = dedo completamente extendido (recto)
      ~90deg = dedo completamente doblado (puno)
    Formula: angulo entre los dos vectores consecutivos del hueso.
    """
    v_in  = vector(a, b)   # vector segmento entrante
    v_out = vector(b, c)   # vector segmento saliente
    ang = angulo_entre_vectores(v_in, v_out)
    # ang=0   -> vectores paralelos -> dedo recto    -> flexion=0  (correcto)
    # ang=90  -> vectores perpendic -> doblado 90deg -> flexion=90 (correcto)
    return float(np.clip(ang, 0.0, 95.0))

def orientacion_palma(lm):
    """Calcula la orientacion global de la palma (Pitch, Yaw, Roll)."""
    p_wrist = np.array([lm[0].x, -lm[0].y, -lm[0].z])
    p_index = np.array([lm[5].x, -lm[5].y, -lm[5].z])
    p_pinky = np.array([lm[17].x, -lm[17].y, -lm[17].z])
    p_mid   = np.array([lm[9].x,  -lm[9].y,  -lm[9].z])

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
    yaw   = math.degrees(math.atan2(v_forward[0], v_forward[2]))
    roll  = math.degrees(math.atan2(v_right[1], v_normal[1]))

    return {"pitch": float(pitch), "yaw": float(yaw), "roll": float(roll)}


def _normalizar_angulo(ang_raw, ang_open, ang_close):
    """
    Mapea ang_raw al rango [0.0, 1.0]:
      0.0 = articulacion completamente abierta
      1.0 = articulacion completamente cerrada
    """
    rango = ang_close - ang_open
    if rango < 2.0:
        rango = 30.0   # Evita division por cero si el rango es muy pequeno
    k = (ang_raw - ang_open) / rango
    return float(np.clip(k, 0.0, 1.0))


def procesar_landmarks_a_angulos(landmarks_list):
    """
    Calcula los angulos articulares para las 15 articulaciones de la mano.

    Modos (en orden de prioridad):
      1. Calibrado v2.0  -- angulos medidos reales por articulacion.
      2. Calibrado v1.0  -- distancia MCP-TIP (compatibilidad retroactiva).
      3. Estandar        -- calculo geometrico puro sin calibracion.
    """
    pts = [[lm.x, lm.y, lm.z] for lm in landmarks_list]
    calib, version = cargar_calibracion()

    # Angulos geometricos crudos para los 5 dedos x 3 segmentos.
    # Cadena cinemica correcta: punto_anterior -> articulacion -> punto_siguiente
    ang_raw = {
        "pulgar": {
            "base":  calcular_flexion_3puntos(pts[0],  pts[1],  pts[2]),  # Muneca->CMC->MCP
            "medio": calcular_flexion_3puntos(pts[1],  pts[2],  pts[3]),  # CMC->MCP->IP
            "punta": calcular_flexion_3puntos(pts[2],  pts[3],  pts[4]),  # MCP->IP->TIP
        },
        "indice": {
            "base":  calcular_flexion_3puntos(pts[0],  pts[5],  pts[6]),  # Muneca->MCP->PIP
            "medio": calcular_flexion_3puntos(pts[5],  pts[6],  pts[7]),  # MCP->PIP->DIP
            "punta": calcular_flexion_3puntos(pts[6],  pts[7],  pts[8]),  # PIP->DIP->TIP
        },
        "medio": {
            "base":  calcular_flexion_3puntos(pts[0],  pts[9],  pts[10]),
            "medio": calcular_flexion_3puntos(pts[9],  pts[10], pts[11]),
            "punta": calcular_flexion_3puntos(pts[10], pts[11], pts[12]),
        },
        "anular": {
            "base":  calcular_flexion_3puntos(pts[0],  pts[13], pts[14]),
            "medio": calcular_flexion_3puntos(pts[13], pts[14], pts[15]),
            "punta": calcular_flexion_3puntos(pts[14], pts[15], pts[16]),
        },
        "menique": {
            "base":  calcular_flexion_3puntos(pts[0],  pts[17], pts[18]),
            "medio": calcular_flexion_3puntos(pts[17], pts[18], pts[19]),
            "punta": calcular_flexion_3puntos(pts[18], pts[19], pts[20]),
        },
    }

    palma = orientacion_palma(landmarks_list)

    # ── MODO CALIBRADO v2.0 ──────────────────────────────────────────────────
    if calib and version == "2.0":
        dedos_out = {}
        for dedo in ["indice", "medio", "anular", "menique", "pulgar"]:
            dedos_out[dedo] = {}
            for seg in ["base", "medio", "punta"]:
                raw  = ang_raw[dedo][seg]
                info = calib.get(dedo, {}).get(seg, {})
                a_op = info.get("angulo_abierto",  4.0)
                a_cl = info.get("angulo_cerrado", 80.0)
                k    = _normalizar_angulo(raw, a_op, a_cl)

                # Factor de rotacion para el modelo 3D en grados.
                # base (MCP) y medio (PIP) doblan mas que la punta (DIP).
                if seg == "base":
                    grados_modelo = k * 82.0
                elif seg == "medio":
                    grados_modelo = k * 88.0
                else:
                    grados_modelo = k * 72.0

                dedos_out[dedo][seg]  = grados_modelo
            dedos_out[dedo]["curl"] = _normalizar_angulo(
                ang_raw[dedo]["medio"],
                calib.get(dedo, {}).get("medio", {}).get("angulo_abierto",  4.0),
                calib.get(dedo, {}).get("medio", {}).get("angulo_cerrado", 80.0),
            )

        return {"palma": palma, "dedos": dedos_out, "calibrado": True, "version": "2.0"}

    # ── MODO CALIBRADO v1.0 (retrocompatibilidad) ────────────────────────────
    if calib and version == "1.0":
        p_wrist   = np.array(pts[0])
        p_ref_mid = np.array(pts[9])
        ref_palma = np.linalg.norm(p_wrist - p_ref_mid)
        if ref_palma == 0:
            ref_palma = 1.0

        mapping = {
            "indice":  (5, 8),
            "medio":   (9, 12),
            "anular":  (13, 16),
            "menique": (17, 20),
        }
        dedos_out = {}
        for nom, (id_mcp, id_tip) in mapping.items():
            dist_norm = np.linalg.norm(np.array(pts[id_tip]) - np.array(pts[id_mcp])) / ref_palma
            lim  = calib.get(nom, {"dist_abierto": 1.4, "dist_cerrado": 0.5})
            d_op = lim["dist_abierto"]
            d_cl = lim["dist_cerrado"]
            denom = d_op - d_cl if (d_op - d_cl) > 0.05 else 0.5
            k = float(np.clip((d_op - dist_norm) / denom, 0.0, 1.0))
            dedos_out[nom] = {
                "base": k * 80.0, "medio": k * 85.0, "punta": k * 70.0, "curl": k,
            }

        lim_p    = calib.get("pulgar", {"dist_abierto": 1.3, "dist_cerrado": 0.5})
        dist_p   = np.linalg.norm(np.array(pts[4]) - np.array(pts[17])) / ref_palma
        denom_p  = max(lim_p["dist_abierto"] - lim_p["dist_cerrado"], 0.05)
        kp       = float(np.clip((lim_p["dist_abierto"] - dist_p) / denom_p, 0.0, 1.0))
        dedos_out["pulgar"] = {
            "base": kp * 45.0, "medio": kp * 60.0, "punta": kp * 50.0, "curl": kp,
        }

        return {"palma": palma, "dedos": dedos_out, "calibrado": True, "version": "1.0"}

    # ── MODO ESTANDAR (sin calibracion) ─────────────────────────────────────
    dedos_std = {}
    for dedo, segs in ang_raw.items():
        dedos_std[dedo] = {
            "base":  segs["base"],
            "medio": segs["medio"],
            "punta": segs["punta"],
            "curl":  float(np.clip(segs["medio"] / 90.0, 0.0, 1.0)),
        }

    return {"palma": palma, "dedos": dedos_std, "calibrado": False, "version": "none"}
