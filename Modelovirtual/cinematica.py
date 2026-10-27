"""
=============================================================================
  CINEMÁTICA Y CÁLCULO DE ÁNGULOS 3D PARA MANO VIRTUAL (FLEXIÓN COMPLETA)
=============================================================================
Convierte los puntos de MediaPipe en ángulos de flexión completos para
los 3 segmentos de cada dedo (Nudillo Base, Articulación Media y Punta),
evitando que solo se doblen las puntas y garantizando que el dedo entero
se cierre en un puño realista.
=============================================================================
"""

import math
import numpy as np

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

def calcular_curl_dedo(pts, id_mcp, id_pip, id_dip, id_tip):
    """
    Calcula el factor de flexión anatómica integral (0.0 = extendido, 1.0 = puño cerrado).
    Mueve TODO el dedo desde el nudillo base hasta la punta armónicamente.
    """
    p_mcp = np.array(pts[id_mcp])
    p_pip = np.array(pts[id_pip])
    p_dip = np.array(pts[id_dip])
    p_tip = np.array(pts[id_tip])

    # 1. Longitud real extendida del dedo
    L_seg1 = np.linalg.norm(p_pip - p_mcp)
    L_seg2 = np.linalg.norm(p_dip - p_pip)
    L_seg3 = np.linalg.norm(p_tip - p_dip)
    L_total = L_seg1 + L_seg2 + L_seg3

    if L_total == 0:
        return {"base": 0.0, "medio": 0.0, "punta": 0.0, "curl": 0.0}

    # 2. Distancia euclidiana directa del nudillo a la punta
    D_directa = np.linalg.norm(p_tip - p_mcp)

    # 3. Factor de contracción de la falange (cuando se dobla, la distancia se reduce a un 35%)
    # D_directa va de L_total (dedo recto) a ~0.35 * L_total (dedo cerrado)
    rango_compresion = L_total * 0.65
    curl = (L_total - D_directa) / rango_compresion
    curl = float(np.clip(curl, 0.0, 1.0))

    # 4. Refuerzo angular complementario para detectar inicio temprano de flexión
    v_prox = vector(p_mcp, p_pip)
    v_mid  = vector(p_pip, p_dip)
    ang_mid_deg = 180.0 - angulo_entre_vectores(v_prox, v_mid)
    factor_ang = float(np.clip(ang_mid_deg / 80.0, 0.0, 1.0))

    # Fusión ponderada: la distancia da estabilidad y el ángulo da respuesta inmediata
    k = max(curl, factor_ang * 0.9)

    # Curva ergonómica: el nudillo base (MCP) y articulación media (PIP)
    # deben doblarse con decisión profunda (hasta 85°-90°)
    ang_base  = float(np.clip(k * 85.0, 0.0, 88.0))
    ang_medio = float(np.clip(k * 90.0, 0.0, 95.0))
    ang_punta = float(np.clip(k * 75.0, 0.0, 80.0))

    return {
        "base": ang_base,
        "medio": ang_medio,
        "punta": ang_punta,
        "curl": k
    }

def calcular_curl_pulgar(pts):
    """Calcula la flexión y aducción anatómica del pulgar hacia la palma."""
    p_wrist = np.array(pts[0])
    p_cmc   = np.array(pts[1])
    p_mcp   = np.array(pts[2])
    p_ip    = np.array(pts[3])
    p_tip   = np.array(pts[4])
    p_index_mcp = np.array(pts[5])
    p_pinky_base = np.array(pts[17])

    ref_palma = np.linalg.norm(p_wrist - np.array(pts[9]))
    if ref_palma == 0:
        ref_palma = 1.0

    dist_tip_pinky = np.linalg.norm(p_tip - p_pinky_base)
    dist_tip_index = np.linalg.norm(p_tip - p_index_mcp)

    # El pulgar está cerrado cuando la punta se acerca a la base del índice o del meñique
    cierre_pinky = 1.0 - np.clip(dist_tip_pinky / (ref_palma * 1.3), 0.0, 1.0)
    cierre_index = 1.0 - np.clip(dist_tip_index / (ref_palma * 0.7), 0.0, 1.0)

    # Ángulo en articulación IP del pulgar
    v_mcp_ip = vector(p_mcp, p_ip)
    v_ip_tip = vector(p_ip, p_tip)
    ang_ip = 180.0 - angulo_entre_vectores(v_mcp_ip, v_ip_tip)
    factor_ang = float(np.clip(ang_ip / 70.0, 0.0, 1.0))

    k = max(cierre_pinky, cierre_index, factor_ang)
    k = float(np.clip(k, 0.0, 1.0))

    return {
        "base":  float(k * 50.0),
        "medio": float(k * 65.0),
        "punta": float(k * 55.0),
        "curl":  k
    }

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
    """Calcula ángulos completos y profundos de flexión para todo el esqueleto."""
    pts = [[lm.x, lm.y, lm.z] for lm in landmarks_list]

    angulos = {
        "palma": orientacion_palma(landmarks_list),
        "dedos": {
            "pulgar":  calcular_curl_pulgar(pts),
            "indice":  calcular_curl_dedo(pts, 5, 6, 7, 8),
            "medio":   calcular_curl_dedo(pts, 9, 10, 11, 12),
            "anular":  calcular_curl_dedo(pts, 13, 14, 15, 16),
            "menique": calcular_curl_dedo(pts, 17, 18, 19, 20),
        }
    }

    return angulos
