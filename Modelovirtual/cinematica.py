"""
=============================================================================
  CINEMÁTICA Y CÁLCULO DE ÁNGULOS 3D PARA MANO VIRTUAL
=============================================================================
Convierte los 21 puntos cartesianos 3D de MediaPipe (X, Y, Z) en:
1. Orientación de la palma (Pitch, Yaw, Roll)
2. Ángulos de flexión individuales de cada articulación (0° recto a 90° cerrado)
=============================================================================
"""

import math
import numpy as np

def vector(p1, p2):
    """Calcula el vector 3D de p1 hacia p2."""
    return np.array([p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]], dtype=float)

def angulo_entre_vectores(v1, v2):
    """Calcula el ángulo en grados entre dos vectores 3D."""
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    cos_theta = np.dot(v1, v2) / (norm1 * norm2)
    cos_theta = np.clip(cos_theta, -1.0, 1.0)
    return math.degrees(math.acos(cos_theta))

def calcular_flexion_3puntos(a, b, c):
    """
    Calcula el ángulo de flexión articular con centro en 'b'.
    Retorna 0° si el dedo está completamente extendido / recto.
    Retorna ~90° si está completamente doblado en escuadra.
    """
    v_in = vector(b, a)
    v_out = vector(b, c)
    ang = angulo_entre_vectores(v_in, v_out)
    flexion = 180.0 - ang
    return float(np.clip(flexion, 0.0, 105.0))

def orientacion_palma(lm):
    """
    Calcula la orientación global de la palma (Pitch, Yaw, Roll) en grados
    usando la muñeca (0), la base del índice (5) y la base del meñique (17).
    """
    p_wrist = np.array([lm[0].x, -lm[0].y, -lm[0].z])
    p_index = np.array([lm[5].x, -lm[5].y, -lm[5].z])
    p_pinky = np.array([lm[17].x, -lm[17].y, -lm[17].z])

    # Vector adelante (muñeca hacia centro de la palma)
    p_mid = np.array([lm[9].x, -lm[9].y, -lm[9].z])
    v_forward = p_mid - p_wrist
    norm_f = np.linalg.norm(v_forward)
    if norm_f > 0:
        v_forward /= norm_f

    # Vector lateral (de meñique a índice)
    v_right = p_index - p_pinky
    norm_r = np.linalg.norm(v_right)
    if norm_r > 0:
        v_right /= norm_r

    # Vector normal de la palma (hacia afuera)
    v_normal = np.cross(v_forward, v_right)
    norm_n = np.linalg.norm(v_normal)
    if norm_n > 0:
        v_normal /= norm_n

    # Pitch (cabeceo hacia arriba/abajo)
    pitch = math.degrees(math.asin(np.clip(-v_forward[1], -1.0, 1.0)))

    # Yaw (giro izquierda/derecha)
    yaw = math.degrees(math.atan2(v_forward[0], v_forward[2]))

    # Roll (inclinación lateral de la muñeca)
    roll = math.degrees(math.atan2(v_right[1], v_normal[1]))

    return {
        "pitch": float(pitch),
        "yaw": float(yaw),
        "roll": float(roll)
    }

def procesar_landmarks_a_angulos(landmarks_list):
    """
    Recibe la lista de 21 landmarks de MediaPipe y entrega el diccionario
    completo de ángulos para el modelo 3D.
    """
    pts = [[lm.x, lm.y, lm.z] for lm in landmarks_list]

    angulos = {
        "palma": orientacion_palma(landmarks_list),
        "dedos": {
            # Pulgar: CMC(1), MCP(2), IP(3), TIP(4)
            "pulgar": {
                "base": calcular_flexion_3puntos(pts[0], pts[1], pts[2]),
                "medio": calcular_flexion_3puntos(pts[1], pts[2], pts[3]),
                "punta": calcular_flexion_3puntos(pts[2], pts[3], pts[4]),
            },
            # Índice: MCP(5), PIP(6), DIP(7), TIP(8)
            "indice": {
                "base": calcular_flexion_3puntos(pts[0], pts[5], pts[6]),
                "medio": calcular_flexion_3puntos(pts[5], pts[6], pts[7]),
                "punta": calcular_flexion_3puntos(pts[6], pts[7], pts[8]),
            },
            # Medio: MCP(9), PIP(10), DIP(11), TIP(12)
            "medio": {
                "base": calcular_flexion_3puntos(pts[0], pts[9], pts[10]),
                "medio": calcular_flexion_3puntos(pts[9], pts[10], pts[11]),
                "punta": calcular_flexion_3puntos(pts[10], pts[11], pts[12]),
            },
            # Anular: MCP(13), PIP(14), DIP(15), TIP(16)
            "anular": {
                "base": calcular_flexion_3puntos(pts[0], pts[13], pts[14]),
                "medio": calcular_flexion_3puntos(pts[13], pts[14], pts[15]),
                "punta": calcular_flexion_3puntos(pts[14], pts[15], pts[16]),
            },
            # Meñique: MCP(17), PIP(18), DIP(19), TIP(20)
            "menique": {
                "base": calcular_flexion_3puntos(pts[0], pts[17], pts[18]),
                "medio": calcular_flexion_3puntos(pts[17], pts[18], pts[19]),
                "punta": calcular_flexion_3puntos(pts[18], pts[19], pts[20]),
            }
        }
    }

    return angulos
