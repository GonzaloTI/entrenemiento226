# GUÍA DE FORMATO Y EXPORTACIÓN DEL MODELO 3D DESDE BLENDER

Para que el modelo 3D sea controlado en tiempo real por `visor_ursina.py` y `detector_dedos.py`, debe cumplir las siguientes pautas en Blender:

---

### 1. Formato requerido
* **Formato:** **`.glb` (glTF 2.0 Binary)**
* **Nombre de archivo sugerido:** `mano_robotica.glb` (colocado dentro de esta carpeta `assets/`).
* **¿Por qué `.glb`?** Porque empaqueta en un solo archivo binario la geometría, jerarquía padre-hijo, colores, materiales PBR y texturas.

---

### 2. Estructura de Objetos y Nombres (Jerarquía de piezas)

Recomendamos el método de **piezas modulares / robóticas jerarquizadas**:

```text
palma (Objeto Raíz)
├── pulgar_01
│   └── pulgar_02
│       └── pulgar_03
├── indice_01
│   └── indice_02
│       └── indice_03
├── medio_01
│   └── medio_02
│       └── medio_03
├── anular_01
│   └── anular_02
│       └── anular_03
└── menique_01
    └── menique_02
        └── menique_03
```

> **Regla de oro:** Cada falange es hija (`Parent`) de la falange anterior. De este modo, al doblar la base `indice_01`, las partes `indice_02` e `indice_03` la siguen de forma natural.

---

### 3. Puntos de Pivote (Origen del Objeto) ¡Muy Importante!

* En Blender, cada pieza de falange debe tener su **Punto de Origen** colocado **justo en el eje donde dobla el nudillo/articulación**, NO en el centro de la pieza.
* En Blender:
  1. Entra a Modo Edición (`Tab`).
  2. Selecciona los vértices de la articulación y presiona `Shift + S` -> **Cursor to Selected**.
  3. Sal a Modo Objeto (`Tab`).
  4. Clic derecho en la pieza -> **Set Origin** -> **Origin to 3D Cursor**.

---

### 4. Aplicar Transformaciones (Evita deformaciones raras)

Antes de exportar:
1. Selecciona todas las piezas con `A`.
2. Presiona `Ctrl + A` y elige **Apply All Transforms** (Location, Rotation, Scale).
3. Todas las rotaciones deben quedar en `(0, 0, 0)` con la mano en reposo (abierta y extendida) y la escala en `(1, 1, 1)`.

---

### 5. Opciones al Exportar en Blender

1. Menú: `File` -> `Export` -> `glTF 2.0 (.glb)`.
2. En el panel de la derecha:
   * **Format:** `glTF Binary (.glb)`
   * **Include:** `Selected Objects` (opcional si seleccionaste la mano)
   * **Transform:** `+Y Up` activado (estándar de glTF)
3. Guarda el archivo como `assets/mano_robotica.glb`.
