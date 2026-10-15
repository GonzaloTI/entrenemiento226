# Guía Completa: Control por Voz Offline con ESP32 + Micrófono INMP441 (TinyML)

Esta guía explica cómo ejecutar **reconocimiento de comandos de voz 100% local (sin internet)** en tu ESP32 utilizando el micrófono digital MEMS **INMP441**.

---

## 📌 1. Conexiones Físicas (Pinout)

El micrófono **INMP441** utiliza el protocolo digital de audio **I2S**. Conéctalo a tu placa siguiendo esta tabla:

| Pin INMP441 | Función | ESP32 Clásico (WROOM / NodeMCU) | ESP32-S3 |
| :--- | :--- | :---: | :---: |
| **VDD** | Alimentación | **3.3V** *(¡Nunca 5V!)* | **3.3V** |
| **GND** | Tierra común | **GND** | **GND** |
| **L/R** | Canal Izquierdo/Derecho | **GND** *(Canal Izquierdo)* | **GND** |
| **SD** | Serial Data (Datos I2S) | **GPIO 32** | **GPIO 10** |
| **WS** | Word Select (Clock de palabra) | **GPIO 25** | **GPIO 11** |
| **SCK** | Bit Clock (Clock de bits) | **GPIO 33** | **GPIO 12** |

> [!WARNING]
> Conecta **VDD siempre a 3.3V**. Conectarlo a 5V quemará permanentemente el chip del micrófono INMP441.

---

## ⚡ 2. Probar el Sketch Inmediatamente

El archivo [`comandoporvoz.ino`](file:///c:/Users/Usuario/Documents/python/2026/comandoporvoz.ino) ya cuenta con un **analizador acústico y detector de actividad de voz (VAD)** incorporado que funciona de inmediato:

1. Abre el archivo [`comandoporvoz.ino`](file:///c:/Users/Usuario/Documents/python/2026/comandoporvoz.ino) en el **Arduino IDE**.
2. Conecta tu ESP32 por USB y selecciona la placa y puerto COM correcto.
3. Sube el sketch a la placa.
4. Abre el **Monitor Serie** a **115200 baudios**.
5. Di frente al micrófono palabras como:
   - **`ENCENDER`** -> Activará el LED / Relé en GPIO 2.
   - **`APAGAR`** -> Apagará el LED / Relé en GPIO 2.
   - **`LUZ`** -> Encenderá el LED / Relé.

---

## 🧠 3. Entrenar tu propia Red Neuronal en Edge Impulse (Recomendado para 98%+ de Precisión)

Si deseas que el ESP32 aprenda tu voz exacta o palabras personalizadas (como *"abre sésamo"*, *"clima"*, *"alarma"*), puedes usar **Edge Impulse** (es gratuito):

### Paso 1: Crear el proyecto
1. Ve a [edgeimpulse.com](https://www.edgeimpulse.com/) y regístrate gratis.
2. Crea un nuevo proyecto llamado `esp32_control_voz`.

### Paso 2: Recolectar datos de voz (Data Acquisition)
1. En **Data Acquisition**, puedes usar el micrófono de tu propia computadora o teléfono móvil.
2. Graba unas 25 a 30 repeticiones de cada comando que quieras:
   - Etiqueta `encender`: 30 grabaciones de 1 segundo diciendo "encender".
   - Etiqueta `apagar`: 30 grabaciones diciendo "apagar".
   - Etiqueta `ruido`: 30 grabaciones de silencio y sonido ambiente.

### Paso 3: Diseñar el impulso (Create Impulse)
1. Ve a **Impulse Design** -> **Create Impulse**.
2. Añade un bloque de procesamiento: **Audio (MFCC)** *(calcula los coeficientes mel-frequency cepstral, ideal para voz humana)*.
3. Añade un bloque de aprendizaje: **Classification (Keras)**.
4. Haz clic en **Save Impulse**.

### Paso 4: Entrenar el modelo
1. Ve a **MFCC** y pulsa en **Save parameters** -> **Generate features**.
2. Ve a **Classifier** y haz clic en **Start training**. En 2 minutos tendrás una red neuronal lista con su porcentaje de precisión.

### Paso 5: Descargar la librería para Arduino
1. Ve al menú lateral **Deployment**.
2. Selecciona **Arduino library**.
3. En la parte inferior pulsa **Build**. Se descargará un archivo `.ZIP`.

### Paso 6: Integrar en Arduino IDE
1. En Arduino IDE: ve a **Programa** -> **Incluir Librería** -> **Añadir biblioteca .ZIP...** y selecciona el archivo descargado.
2. En [`comandoporvoz.ino`](file:///c:/Users/Usuario/Documents/python/2026/comandoporvoz.ino), cambia la línea:
   ```cpp
   #define USAR_EDGE_IMPULSE_LIB 1
   ```
3. ¡Listo! Tu ESP32 ejecutará tu red neuronal personalizada de forma offline a más de 15 inferencias por segundo.
