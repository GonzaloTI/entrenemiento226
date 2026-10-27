"""
=============================================================================
  VISOR 3D INDEPENDIENTE EN TIEMPO REAL (URSINA + BLENDER RIG + MEDIAPIPE)
=============================================================================
- Compatible con Cámara Integrada (Laptop) y Cámara Externa USB.
- Detección automática y cambio en caliente con la tecla [C].
- Flexión profunda y completa de todo el dedo (Nudillo base, medio y punta).
- Carga el modelo 3D realista exportado de Blender ('assets/mano_robotica.glb').
- Conecta cada una de las 15 articulaciones óseas con la cinemática de MediaPipe.
- Render 3D a 60+ FPS sin retrasos gracias al hilo de captura independiente.

Uso:
  python visor_ursina.py          -> Detecta la mejor cámara automáticamente
  python visor_ursina.py 0        -> Fuerza Cámara Integrada (Laptop)
  python visor_ursina.py 1        -> Fuerza Cámara Externa (USB)
=============================================================================
"""

import os
import sys
import math
import argparse
import numpy as np

# Configuración de Panda3D para soporte GLTF/GLB antes de iniciar Ursina
from panda3d.core import Filename, loadPrcFileData, Vec3 as P3Vec3, AmbientLight, DirectionalLight
loadPrcFileData('', 'load-file-type gltf panda3d-gltf')
loadPrcFileData('', 'load-file-type glb panda3d-gltf')
loadPrcFileData('', 'sync-video 1')

from direct.actor.Actor import Actor

try:
    from ursina import (
        Ursina, Entity, camera, color, window, Vec3, Text,
        EditorCamera, application, destroy
    )
except ImportError:
    print("\n" + "=" * 65)
    print(" [ERROR] Se requiere la librería 'ursina' instalada.")
    print(" Ejecuta: pip install ursina")
    print("=" * 65 + "\n")
    sys.exit(1)

from detector_dedos import DetectorManoThread

# --- PROCESAR ARGUMENTOS DE LÍNEA DE COMANDOS PARA CÁMARA ---
parser = argparse.ArgumentParser(description="Visor 3D de Mano MediaPipe")
parser.add_argument("cam_pos", nargs="?", type=int, default=None, help="Índice de cámara (0=Laptop, 1=USB)")
parser.add_argument("-c", "--cam", type=int, default=None, help="Índice de cámara")
args, _ = parser.parse_known_args()
cam_solicitada = args.cam_pos if args.cam_pos is not None else args.cam

# --- CONFIGURACIÓN DE LA VENTANA URSINA ---
app = Ursina(title="Visor 3D Independiente - Clon de Mano (MediaPipe + Blender)")
window.borderless = False
window.fullscreen = False
window.size = (1280, 720)
window.color = color.rgb(18, 20, 26)

# Luces de estudio 3D
alight = AmbientLight('alight')
alight.setColor((0.45, 0.45, 0.5, 1))
alnp = app.render.attachNewNode(alight)
app.render.setLight(alnp)

dlight = DirectionalLight('dlight')
dlight.setColor((0.85, 0.85, 0.8, 1))
dlnp = app.render.attachNewNode(dlight)
dlnp.setHpr(-45, -60, 0)
app.render.setLight(dlnp)

# Cámara orbital interactiva
editor_cam = EditorCamera()
editor_cam.position = (0, 0, -9.5)
editor_cam.rotation = (10, 0, 0)

RUTA_GLB = os.path.join(os.path.dirname(__file__), "assets", "mano_robotica.glb")

class ManoVirtualBlender:
    """Gestiona el modelo esquelético realista de Blender en Ursina."""
    def __init__(self, ruta_glb):
        self.raiz = Entity(position=(0, -2.4, 0), scale=5.5)
        self.actor = None
        self.joints = {}
        self.rest_hpr = {}
        self.rot_suavizada_palma = Vec3(0, 0, 0)
        self.angulos_suavizados = {
            "indice":  [0.0, 0.0, 0.0],
            "medio":   [0.0, 0.0, 0.0],
            "anular":  [0.0, 0.0, 0.0],
            "menique": [0.0, 0.0, 0.0],
            "pulgar":  [0.0, 0.0, 0.0],
        }

        self.huesos_map = {
            "indice":  ["Bone", "Bone.001", "Bone.002"],
            "medio":   ["Bone.004", "Bone.005", "Bone.006"],
            "anular":  ["Bone.008", "Bone.009", "Bone.010"],
            "menique": ["Bone.012", "Bone.013", "Bone.014"],
            "pulgar":  ["Bone.016", "Bone.017", "Bone.018"],
        }

        self._cargar_modelo(ruta_glb)

    def _cargar_modelo(self, ruta_glb):
        fn = Filename.from_os_specific(ruta_glb)
        try:
            model = app.loader.loadModel(fn)
            self.actor = Actor(model)
            self.actor.reparent_to(self.raiz)

            for dedo, lista_huesos in self.huesos_map.items():
                self.joints[dedo] = []
                self.rest_hpr[dedo] = []
                for bname in lista_huesos:
                    j = self.actor.controlJoint(None, 'modelRoot', bname)
                    self.joints[dedo].append(j)
                    self.rest_hpr[dedo].append(j.getHpr())

            print("[OK] Modelo de Blender con Armature cargado exitosamente.")
        except Exception as e:
            print(f"[ERROR] No se pudo cargar el Actor de Blender: {e}")

    def actualizar(self, angulos, factor_suavizado=0.35):
        if not angulos or not self.actor:
            return

        # 1. Rotación de muñeca / palma
        p_obj = angulos["palma"]
        t_rot = Vec3(p_obj["pitch"] * 0.45, -p_obj["yaw"] * 0.55, p_obj["roll"] * 0.4)
        self.rot_suavizada_palma += (t_rot - self.rot_suavizada_palma) * factor_suavizado
        self.raiz.rotation = self.rot_suavizada_palma

        # 2. Flexión profunda de todo el dedo (Nudillo base, articulación media y distal)
        dedos_data = angulos["dedos"]
        for dedo in ["indice", "medio", "anular", "menique"]:
            if dedo not in dedos_data or dedo not in self.joints:
                continue

            target_base = dedos_data[dedo]["base"]
            target_mid = dedos_data[dedo]["medio"]
            target_tip = dedos_data[dedo]["punta"]
            targets = [target_base, target_mid, target_tip]

            for i in range(3):
                curr = self.angulos_suavizados[dedo][i]
                nuevo = curr + (targets[i] - curr) * factor_suavizado
                self.angulos_suavizados[dedo][i] = nuevo

                j = self.joints[dedo][i]
                base_hpr = self.rest_hpr[dedo][i]
                # Aplicar flexión completa con ganancia 1.0 para que se cierre el puño por completo
                j.setHpr(base_hpr[0], base_hpr[1] + nuevo * 1.0, base_hpr[2])

        # 3. Flexión anatómica del pulgar (Base hacia la palma y punta doblada)
        if "pulgar" in dedos_data and "pulgar" in self.joints:
            p_data = dedos_data["pulgar"]
            p_targets = [p_data["base"], p_data["medio"], p_data["punta"]]
            for i in range(3):
                curr = self.angulos_suavizados["pulgar"][i]
                nuevo = curr + (p_targets[i] - curr) * factor_suavizado
                self.angulos_suavizados["pulgar"][i] = nuevo

                j = self.joints["pulgar"][i]
                base_hpr = self.rest_hpr["pulgar"][i]
                j.setHpr(base_hpr[0], base_hpr[1] + nuevo * 0.85, base_hpr[2] - nuevo * 0.45)

# --- INICIAR MODELO Y DETECTOR ---
mano_3d = ManoVirtualBlender(RUTA_GLB)
detector = DetectorManoThread(camera_index=cam_solicitada, mostrar_ventana_cam=True)
detector.start()

# --- INTERFAZ GRÁFICA HUD EN PANTALLA ---
panel_header = Entity(parent=camera.ui, model='quad', scale=(1.8, 0.08), position=(0, 0.45), color=color.rgb(25, 28, 36))
txt_titulo = Text(
    text="CLON VIRTUAL 3D EN TIEMPO REAL - MEDIAPIPE & BLENDER",
    position=(-0.85, 0.465),
    scale=1.0,
    color=color.rgb(0, 255, 200)
)
txt_sub = Text(
    text="[Mouse Der]: Orbitar | [Rueda]: Zoom | [ESPACIO]: Centrar | [C]: Cambiar Cam (USB/Laptop) | [M]: Espejo | [ESC]: Salir",
    position=(-0.85, 0.435),
    scale=0.72,
    color=color.rgb(160, 170, 185)
)

# Tarjeta lateral de estado
panel_gesto = Entity(parent=camera.ui, model='quad', scale=(0.46, 0.42), position=(0.66, 0.20), color=color.rgb(24, 27, 35))
txt_cam_activa = Text(text="CAM: INICIANDO...", position=(0.45, 0.38), scale=0.85, color=color.rgb(0, 220, 255))
txt_mano_label = Text(text="MANO: ESPERANDO...", position=(0.45, 0.33), scale=0.95, color=color.rgb(255, 200, 50))
txt_gesto = Text(text="GESTO: BUSCANDO", position=(0.45, 0.28), scale=0.90, color=color.rgb(0, 255, 220))
txt_fps = Text(text="FPS Cam: -- | 3D: 60", position=(0.45, 0.23), scale=0.75, color=color.rgb(180, 190, 200))

# Indicadores de los 5 dedos
nombres_dedos = ["Pulgar", "Indice", "Medio", "Anular", "Menique"]
txt_dedos = []
for idx, nom in enumerate(nombres_dedos):
    t = Text(text=f"  {nom}: [ - ]", position=(0.45, 0.17 - idx * 0.035), scale=0.78, color=color.rgb(150, 160, 175))
    txt_dedos.append(t)

# --- BUCLE PRINCIPAL URSINA (60+ FPS) ---
def update():
    datos = detector.obtener_datos()
    txt_cam_activa.text = f"{datos['cam_nombre'].upper()}"

    if datos["detectada"] and datos["angulos"]:
        mano_3d.actualizar(datos["angulos"])

        mano_str = "DERECHA" if datos["etiqueta"] == "Right" else "IZQUIERDA"
        txt_mano_label.text = f"MANO {mano_str} DETECTADA"
        txt_mano_label.color = color.rgb(0, 255, 160)

        txt_gesto.text = f"GESTO: {datos['gesto'].upper()}"
        txt_gesto.color = color.rgb(0, 255, 230)

        txt_fps.text = f"FPS Cam: {int(datos['fps'])} | 3D: 60 FPS"

        estados = datos["estados"]
        for idx in range(5):
            nom = nombres_dedos[idx]
            if estados[idx]:
                txt_dedos[idx].text = f"  {nom}: [ ARRIBA ]"
                txt_dedos[idx].color = color.rgb(0, 255, 120)
            else:
                txt_dedos[idx].text = f"  {nom}: [ ABAJO  ]"
                txt_dedos[idx].color = color.rgb(130, 140, 160)
    else:
        txt_mano_label.text = "BUSCANDO MANO..."
        txt_mano_label.color = color.rgb(255, 180, 60)
        txt_gesto.text = "GESTO: NINGUNO"
        txt_gesto.color = color.rgb(160, 170, 185)
        txt_fps.text = f"FPS Cam: {int(datos['fps'])} | 3D: 60 FPS"

def input(key):
    if key == 'escape' or key == 'q':
        detector.stop()
        application.quit()
    elif key == 'space':
        editor_cam.position = (0, 0, -9.5)
        editor_cam.rotation = (10, 0, 0)
    elif key == 'c':
        detector.cambiar_camara()
    elif key == 'm':
        detector.alternar_espejo()

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print(" [INICIANDO] VISOR 3D INDEPENDIENTE (CLON VIRTUAL DE MANO)")
    print(" Presiona [C] para alternar entre Cámara USB y Laptop.")
    print(" Presiona [M] para alternar vista espejo.")
    print("=" * 65 + "\n")
    try:
        app.run()
    finally:
        detector.stop()
