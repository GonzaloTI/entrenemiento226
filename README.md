# Suite de Detección con MediaPipe y OpenCV

Este proyecto contiene scripts en Python listos para usar que implementan **la detección de dedos, conteo y gestos**, así como **todas las soluciones de visión artificial que ofrece MediaPipe**.

---

## 📁 Scripts Incluidos

| Archivo | Descripción |
| :--- | :--- |
| **[`detector_mediapipe.py`](file:///c:/Users/Usuario/Documents/python/2026/detector_mediapipe.py)** | **Suite Multimodal Completa (Todo en Uno)**. Permite alternar en tiempo real entre: Holistic (cuerpo + manos + rostro simultáneos), Manos & Dedos Pro, Esqueleto Corporal (Pose con cálculo de ángulos), Malla Facial de 468 puntos, Cajas de Rostros y Fondo Desenfocado (Blur). |
| **[`detector_dedos.py`](file:///c:/Users/Usuario/Documents/python/2026/detector_dedos.py)** | **Detector Dedicado de Manos y Dedos**. Enfocado 100% en el conteo de dedos (0 a 10), estado individual de cada dedo (Pulgar, Índice, Medio, Anular, Meñique), reconocimiento de gestos y efecto de click/pellizco. |

---

## 🚀 Cómo Ejecutar

Abre una terminal en esta carpeta y ejecuta cualquiera de los scripts:

### 1. Suite Multimodal Completa:
```bash
python detector_mediapipe.py
```

*Argumentos opcionales:*
- Cambiar índice de cámara: `python detector_mediapipe.py --camera 1`
- Procesar un video grabado: `python detector_mediapipe.py --video mi_video.mp4`
- Cambiar resolución: `python detector_mediapipe.py --width 1920 --height 1080`

### 2. Detector Especializado de Dedos y Gestos:
```bash
python detector_dedos.py
```

---

## 🎮 Controles de Teclado en Vivo

Dentro de la ventana de la cámara puedes presionar:

| Tecla | Acción |
| :---: | :--- |
| **`1`** | **Modo Holistic**: Rostro (468 pts) + Cuerpo (33 pts) + Manos (21 pts c/u) simultáneamente. |
| **`2`** | **Modo Manos & Dedos Pro**: Conteo exacto, gestos, estado de cada dedo y coordenadas. |
| **`3`** | **Modo Pose**: Esqueleto de 33 articulaciones corporales y cálculo de ángulos en grados. |
| **`4`** | **Modo Malla Facial**: Visualización 3D de alta densidad (468 puntos) con labios y ojos. |
| **`5`** | **Modo Detección Facial**: Cuadro delimitador rápido (bounding box) con porcentaje de certeza. |
| **`6`** | **Modo Segmentación**: Desenfoque cinemático de fondo en tiempo real (Virtual Background Blur). |
| **`M`** | Alternar efecto espejo (flip horizontal). |
| **`H`** | Ocultar / Mostrar la interfaz HUD en pantalla. |
| **`S`** | Guardar una foto / captura de pantalla con marca de tiempo. |
| **`Q`** o **`ESC`** | Salir del programa limpiamente. |

---

## 🖐️ Detección de Dedos y Gestos Reconocidos

El algoritmo analiza los 21 puntos anatómicos (`landmarks`) de cada mano:

- **Pulgar**: Detección relativa según mano izquierda o derecha y distancia a la base del meñique.
- **Índice, Medio, Anular y Meñique**: Comparación geométrica vertical entre la punta (`TIP`) y la articulación intermedia (`PIP`).
- **Conteo**: Suma de dedos extendidos en pantalla (0 a 5 por mano, hasta 10 dedos en total).

### Gestos Automáticos:
- ✌️ **Paz / Victoria**: Índice y medio levantados.
- 👍 **Pulgar Arriba (Like)**: Solo pulgar extendido apuntando hacia arriba.
- 👎 **Pulgar Abajo (Dislike)**: Solo pulgar extendido apuntando hacia abajo.
- ☝️ **Señalando**: Solo el dedo índice extendido.
- 🖐️ **Mano Abierta**: Los 5 dedos extendidos.
- ✊ **Puño Cerrado**: 0 dedos extendidos.
- 🤟 **Rock / Heavy Metal**: Pulgar, índice y meñique levantados.
- 🤙 **Shaka / Surfer**: Pulgar y meñique levantados.
- 🤏 **Pellizco / Click**: Cuando la punta del pulgar toca la punta del índice (distancia euclidiana mínima), ideal para control gestual.
