/*
 * ======================================================================================
 * NODO 2: ESP32-WROOM - CONTROL POR VOZ (INMP441 + TINYML) Y TRANSMISOR LORA P2P
 * ======================================================================================
 * Archivo: prueba_lora_wan_bidirecional_wroom.ino
 * Placa  : ESP32 WROOM (38 pines o 30 pines)
 * Audio  : Micrófono I2S INMP441 (16 kHz / Canal Derecho calibrado)
 * Módulo : RAK811-H LoRa P2P (903.9 MHz)
 * 
 * DESCRIPCIÓN:
 * Este nodo realiza reconocimiento de voz local (TinyML / Edge Impulse) y transmite
 * los comandos por radio LoRa al nodo receptor (ESP32-S3 CAM):
 * 
 * 1. Monitorea continuamente el nivel de audio con un VU-Meter gráfico en el Monitor Serie.
 * 2. Al hablar frente al micrófono INMP441 (RMS > 600) o al pulsar 'C' en el monitor:
 *    - Captura exactamente 1 segundo de audio.
 *    - Ejecuta el clasificador TinyML (Edge Impulse: "uno", "dos", "ruido").
 * 3. Al reconocer el comando "uno":
 *    - Enciende el LED de estado local (GPIO 2).
 *    - Envía por LoRa el paquete: "UNO" al ESP32-S3 CAM para prender los 2 LEDs (21 y 41).
 * 4. Al reconocer el comando "dos":
 *    - Apaga el LED de estado local (GPIO 2).
 *    - Envía por LoRa el paquete: "DOS" al ESP32-S3 CAM para apagar los 2 LEDs.
 * 5. Recibe y muestra en pantalla los ACKs de confirmación enviados de vuelta por el S3 CAM.
 * 
 * CONEXIONES FÍSICAS:
 * 
 * 1. Micrófono INMP441 <---> ESP32 WROOM:
 *    - VDD                 <---> 3.3V (¡NUNCA 5V!)
 *    - GND                 <---> GND
 *    - L/R                 <---> GND (o 3.3V)
 *    - SD  (Serial Data)   <---> GPIO 32
 *    - WS  (Word Select)   <---> GPIO 25
 *    - SCK (Serial Clock)  <---> GPIO 33
 * 
 * 2. Módulo LoRa RAK811-H <---> ESP32 WROOM:
 *    - RAK811 Pin 6  (TX)  <---> ESP32 GPIO 16 (RX2)
 *    - RAK811 Pin 7  (RX)  <---> ESP32 GPIO 17 (TX2)
 *    - RAK811 Pin 17 (BOOT0)<---> GND
 *    - RAK811 Pin 1/28(GND)<---> GND
 *    - RAK811 Pin 11 (VCC) <---> 3.3V
 * 
 * 3. Actuador Local:
 *    - LED Integrado       <---> GPIO 2
 * 
 * Monitor Serie: 115200 baudios | Configuración: "Ambos NL y CR" (Both NL & CR)
 * ======================================================================================
 */

#include <Arduino.h>
#include <driver/i2s.h>
#include <math.h>

// ======================================================================================
// SELECTOR DE MODO DE INFERENCIA
// ======================================================================================
// 1 = Usa la librería de Edge Impulse (ernestoman-project-1_inferencing.h)
// 0 = Modo de prueba con analizador acústico interno (sin requerir librerías externas)
#define USAR_EDGE_IMPULSE      1

#if USAR_EDGE_IMPULSE
  // Librería exportada de Edge Impulse (entrenada para "uno", "dos", "ruido")
  #include <ernestoman-project-1_inferencing.h>
#else
  #define EI_CLASSIFIER_RAW_SAMPLE_COUNT  16000
#endif

// ======================================================================================
// CONFIGURACIÓN DE PINES
// ======================================================================================
#define NOMBRE_NODO           "ESP32-WROOM (VOZ INMP441 -> LORA)"

// Pines de comunicación con el módem LoRa RAK811 en ESP32 WROOM
#define RAK_RX_PIN            16  // Al TX del RAK811 (Pin 6)
#define RAK_TX_PIN            17  // Al RX del RAK811 (Pin 7)
#define RAK_BAUD              115200

// Pines del micrófono digital I2S INMP441
#define I2S_PIN_BCLK          33  // SCK (Reloj de bits)
#define I2S_PIN_WS            25  // WS  (Reloj de palabra)
#define I2S_PIN_DIN           32  // SD  (Datos serie)

// Indicador LED local (LED azul onboard)
#define PIN_LED_ACTUADOR      2

// ======================================================================================
// PARÁMETROS DE AUDIO Y CLASIFICACIÓN
// ======================================================================================
#define I2S_PORT              I2S_NUM_0
#define SAMPLE_RATE           16000
#define BUFFER_DMA_SAMPLES    256

// En silencio el RMS ronda ~30-50; la voz clara se sitúa en 800 - 2500
#define UMBRAL_VOZ_RMS        600
#define UMBRAL_CONFIANZA      0.60f  // Mínimo 60% de certeza en la red neuronal

// ======================================================================================
// PARÁMETROS DE RADIO LORA P2P (Deben ser EXACTAMENTE IGUALES al ESP32-S3 CAM)
// ======================================================================================
#define LORA_P2P_CONFIG       "903900000:7:0:1:8:5"

HardwareSerial LoRaSerial(2);

// Buffers de audio
int32_t buffer_i2s_estereo[BUFFER_DMA_SAMPLES * 2];
int16_t buffer_audio_inferencia[EI_CLASSIFIER_RAW_SAMPLE_COUNT];

// Pre-búfer para no perder el primer fonema de la palabra ("u-")
int16_t buffer_previo[BUFFER_DMA_SAMPLES];
int muestras_previas = 0;

float filtro_dc = 0.0f;
unsigned long ultimo_reporte_vumeter = 0;

// ======================================================================================
// FUNCIONES AUXILIARES DE CONVERSIÓN HEX <-> TEXTO
// ======================================================================================
String stringToHex(const String& input) {
  String hexStr = "";
  for (unsigned int i = 0; i < input.length(); i++) {
    char buf[3];
    sprintf(buf, "%02X", (unsigned char)input[i]);
    hexStr += buf;
  }
  return hexStr;
}

String hexToString(const String& hex) {
  String text = "";
  for (unsigned int i = 0; i < hex.length(); i += 2) {
    if (i + 1 < hex.length()) {
      char byteChars[3] = { hex[i], hex[i + 1], '\0' };
      char c = (char)strtol(byteChars, NULL, 16);
      text += c;
    }
  }
  return text;
}

// ======================================================================================
// COMUNICACIÓN CON EL MÓDEM LORA RAK811
// ======================================================================================
bool enviarComandoAT(const String& cmd, uint32_t timeoutMs = 1500) {
  while (LoRaSerial.available()) LoRaSerial.read();
  LoRaSerial.printf("%s\r\n", cmd.c_str());

  unsigned long start = millis();
  String resp = "";
  while (millis() - start < timeoutMs) {
    while (LoRaSerial.available()) {
      resp += (char)LoRaSerial.read();
    }
    if (resp.indexOf("OK") != -1) return true;
    if (resp.indexOf("ERROR") != -1) return false;
    delay(10);
  }
  return false;
}

void activarModoRecepcion() {
  LoRaSerial.print("at+set_config=lorap2p:transfer_mode:1\r\n");
  delay(100);
  while (LoRaSerial.available()) LoRaSerial.read();
}

void enviarMensajeLoRa(String mensaje) {
  mensaje.trim();
  if (mensaje.length() == 0) return;

  Serial.println();
  Serial.printf(">> [TRANSMITIENDO POR LORA] \"%s\"\n", mensaje.c_str());

  // 1. Cambiar a modo Transmisor (Sender Mode = 2)
  LoRaSerial.print("at+set_config=lorap2p:transfer_mode:2\r\n");
  delay(100);
  while (LoRaSerial.available()) LoRaSerial.read();

  // 2. Convertir texto a HEX y transmitir por radio
  String payloadHex = stringToHex(mensaje);
  LoRaSerial.printf("at+send=lorap2p:%s\r\n", payloadHex.c_str());

  // 3. Esperar que la radio emita el paquete
  delay(500);
  while (LoRaSerial.available()) LoRaSerial.read();

  // 4. Volver a modo Receptor para escuchar respuestas o ACKs
  activarModoRecepcion();
  Serial.println(">> [ENVIADO] Paquete transmitido al aire. Esperando confirmación (ACK)...");

  // Limpiar buffer DMA de audio para reiniciar escucha acústica limpia
  i2s_zero_dma_buffer(I2S_PORT);
}

// ======================================================================================
// PROCESAMIENTO DE TRAMAS RECIBIDAS (ACKs del ESP32-S3 CAM)
// ======================================================================================
void procesarPaqueteRecibido(String raw) {
  int dosPuntos = raw.indexOf(':');
  if (dosPuntos == -1) {
    Serial.printf("[INFO RAK811]: %s\n", raw.c_str());
    return;
  }

  String meta = raw.substring(8, dosPuntos);
  String hexData = raw.substring(dosPuntos + 1);
  hexData.trim();

  int coma1 = meta.indexOf(',');
  int coma2 = meta.indexOf(',', coma1 + 1);
  String rssi = (coma1 != -1) ? meta.substring(0, coma1) : "?";
  String snr  = (coma1 != -1 && coma2 != -1) ? meta.substring(coma1 + 1, coma2) : "?";
  String len  = (coma2 != -1) ? meta.substring(coma2 + 1) : "?";

  String texto = hexToString(hexData);

  Serial.println("\n**************************************************");
  Serial.println("   >>> [CONFIRMACIÓN RECIBIDA DESDE S3 CAM] <<<   ");
  Serial.println("**************************************************");
  Serial.printf("  Respuesta/ACK  : %s\n", texto.c_str());
  Serial.printf("  Intensidad RSSI: %s dBm\n", rssi.c_str());
  Serial.printf("  Calidad SNR    : %s dB\n", snr.c_str());
  Serial.println("**************************************************\n");
}

// ======================================================================================
// FILTRO DC Y NORMALIZACIÓN DE MUESTRAS DE AUDIO
// ======================================================================================
inline int16_t procesar_muestra(int32_t muestra_cruda) {
  int32_t muestra_escalada = muestra_cruda >> 15;

  // Filtro pasa-altos suave para centrar la señal en 0
  filtro_dc = 0.992f * filtro_dc + 0.008f * (float)muestra_escalada;
  int32_t limpia = muestra_escalada - (int32_t)filtro_dc;

  if (limpia > 30000) limpia = 30000;
  if (limpia < -30000) limpia = -30000;

  return (int16_t)limpia;
}

#if USAR_EDGE_IMPULSE
// Callback para que la librería Edge Impulse lea el búfer de audio
static int obtener_datos_audio(size_t offset, size_t length, float *out_ptr) {
  for (size_t i = 0; i < length; i++) {
    out_ptr[i] = (float)buffer_audio_inferencia[offset + i];
  }
  return 0;
}
#endif

// ======================================================================================
// INICIALIZACIÓN I2S PARA MICRÓFONO INMP441
// ======================================================================================
void iniciar_i2s() {
  const i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT, // Modo estéreo para capturar canal activo
    .communication_format = i2s_comm_format_t(I2S_COMM_FORMAT_STAND_I2S),
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 6,
    .dma_buf_len = BUFFER_DMA_SAMPLES,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  const i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_PIN_BCLK,
    .ws_io_num = I2S_PIN_WS,
    .data_out_num = -1,
    .data_in_num = I2S_PIN_DIN
  };

  esp_err_t err = i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  if (err != ESP_OK) {
    Serial.printf("[ERROR] Falló i2s_driver_install: 0x%x\n", err);
    while (1) delay(1000);
  }

  err = i2s_set_pin(I2S_PORT, &pin_config);
  if (err != ESP_OK) {
    Serial.printf("[ERROR] Falló i2s_set_pin: 0x%x\n", err);
    while (1) delay(1000);
  }

  i2s_zero_dma_buffer(I2S_PORT);
  Serial.println("[OK] Controlador I2S iniciado (16000 Hz / INMP441 Canal Derecho).");
}

// ======================================================================================
// CLASIFICACIÓN DE AUDIO Y DISPARO DE COMANDOS LORA
// ======================================================================================
void clasificar_audio() {
#if USAR_EDGE_IMPULSE
  signal_t signal;
  signal.total_length = EI_CLASSIFIER_RAW_SAMPLE_COUNT;
  signal.get_data = &obtener_datos_audio;

  ei_impulse_result_t result = { 0 };

  Serial.println("\n------------------------------------------------");
  Serial.println("  [TINYML] Ejecutando clasificador neuronal...  ");
  Serial.println("------------------------------------------------");

  EI_IMPULSE_ERROR r = run_classifier(&signal, &result, false);
  if (r != EI_IMPULSE_OK) {
    Serial.printf("[ERROR] Inferencia fallida (código %d)\n", r);
    return;
  }

  Serial.printf("Tiempo inferencia: %d ms (DSP: %d ms, Red: %d ms)\n",
                result.timing.dsp + result.timing.classification,
                result.timing.dsp, result.timing.classification);
  Serial.println("Probabilidades:");

  int clase_ganadora = -1;
  float mayor_prob = 0.0f;

  for (size_t ix = 0; ix < EI_CLASSIFIER_LABEL_COUNT; ix++) {
    float prob = result.classification[ix].value;
    Serial.printf("  * [%-8s] : %5.1f%%\n", result.classification[ix].label, prob * 100.0f);
    if (prob > mayor_prob) {
      mayor_prob = prob;
      clase_ganadora = ix;
    }
  }

  Serial.println("------------------------------------------------");

  if (mayor_prob >= UMBRAL_CONFIANZA && clase_ganadora >= 0) {
    const char* etiqueta = result.classification[clase_ganadora].label;
    Serial.printf(">>> DETECTADO: [%s] (Confianza: %.1f%%)\n", etiqueta, mayor_prob * 100.0f);

    // =========================================================================
    // COMANDO "UNO" -> ENCIENDE LOS 2 LEDS EN ESP32-S3 CAM
    // =========================================================================
    if (strcmp(etiqueta, "uno") == 0) {
      digitalWrite(PIN_LED_ACTUADOR, HIGH);
      Serial.println("\n>>> [ACCIÓN] Comando 'UNO' detectado:");
      Serial.println("    1. LED local (GPIO 2): ENCENDIDO [ON]");
      Serial.println("    2. Enviando comando 'UNO' por LoRa al ESP32-S3 CAM...");
      enviarMensajeLoRa("UNO");
    } 
    // =========================================================================
    // COMANDO "DOS" -> APAGA LOS 2 LEDS EN ESP32-S3 CAM
    // =========================================================================
    else if (strcmp(etiqueta, "dos") == 0) {
      digitalWrite(PIN_LED_ACTUADOR, LOW);
      Serial.println("\n>>> [ACCIÓN] Comando 'DOS' detectado:");
      Serial.println("    1. LED local (GPIO 2): APAGADO [OFF]");
      Serial.println("    2. Enviando comando 'DOS' por LoRa al ESP32-S3 CAM...");
      enviarMensajeLoRa("DOS");
    } 
    else if (strcmp(etiqueta, "ruido") == 0) {
      Serial.println("[FILTRO] -> Ruido ambiental ignorado.");
    }
  } else {
    Serial.println("[AVISO] Sonido no concluyente (<60% confianza).");
  }

#else
  // Clasificador acústico básico (modo de respaldo si no hay librería instalada)
  Serial.println("[MODO MANUAL / ACÚSTICO] Captura realizada.");
#endif

  Serial.println("------------------------------------------------\n");
  i2s_zero_dma_buffer(I2S_PORT);
  ultimo_reporte_vumeter = millis() + 500; // Pausa para visualización clara
}

// ======================================================================================
// CAPTURA DE VENTANA DE 1 SEGUNDO DE AUDIO
// ======================================================================================
void capturar_y_clasificar(int16_t* bloque_inicial, int cant_inicial) {
  int muestras_grabadas = 0;

  // 1. Añadir pre-búfer para no recortar la primera sílaba
  for (int i = 0; i < muestras_previas && muestras_grabadas < EI_CLASSIFIER_RAW_SAMPLE_COUNT; i++) {
    buffer_audio_inferencia[muestras_grabadas++] = buffer_previo[i];
  }

  // 2. Añadir el bloque que superó el umbral
  for (int i = 0; i < cant_inicial && muestras_grabadas < EI_CLASSIFIER_RAW_SAMPLE_COUNT; i++) {
    buffer_audio_inferencia[muestras_grabadas++] = bloque_inicial[i];
  }

  // 3. Completar el resto de la ventana de 1 segundo (16000 muestras)
  while (muestras_grabadas < EI_CLASSIFIER_RAW_SAMPLE_COUNT) {
    size_t b_leidos = 0;
    esp_err_t r_err = i2s_read(
      I2S_PORT,
      (void*)buffer_i2s_estereo,
      sizeof(buffer_i2s_estereo),
      &b_leidos,
      portMAX_DELAY
    );

    if (r_err == ESP_OK && b_leidos > 0) {
      int pares = b_leidos / (sizeof(int32_t) * 2);
      for (int i = 0; i < pares && muestras_grabadas < EI_CLASSIFIER_RAW_SAMPLE_COUNT; i++) {
        // En este hardware, el micrófono emite por el Canal Derecho (muestra impar)
        int32_t muestra_raw = buffer_i2s_estereo[i * 2 + 1];
        buffer_audio_inferencia[muestras_grabadas++] = procesar_muestra(muestra_raw);
      }
    }
  }

  Serial.println("[OK] 1 segundo de audio capturado con éxito.");
  clasificar_audio();
  muestras_previas = 0;
}

// ======================================================================================
// SETUP
// ======================================================================================
void setup() {
  Serial.begin(115200);
  delay(1200);

  Serial.println("\n========================================================");
  Serial.printf("   SISTEMA LORA P2P - [%s]\n", NOMBRE_NODO);
  Serial.println("   Control por Voz (INMP441) con Transmisión LoRa");
  Serial.println("========================================================");
  Serial.println("  * Di 'UNO' frente al micro -> Envía 'UNO' por LoRa");
  Serial.println("                               (Enciende LEDs en S3 CAM)");
  Serial.println("  * Di 'DOS' frente al micro -> Envía 'DOS' por LoRa");
  Serial.println("                               (Apaga LEDs en S3 CAM)");
  Serial.println("  * Disparo manual por Serie : Escribe 'uno', 'dos' o 'C'");
  Serial.println("========================================================\n");

  pinMode(PIN_LED_ACTUADOR, OUTPUT);
  digitalWrite(PIN_LED_ACTUADOR, LOW);

  // Inicializar comunicación LoRa con el RAK811
  LoRaSerial.begin(RAK_BAUD, SERIAL_8N1, RAK_RX_PIN, RAK_TX_PIN);
  delay(500);

  Serial.print("[CONFIG] Fijando modo LoRa P2P... ");
  if (enviarComandoAT("at+set_config=lora:work_mode:1")) {
    Serial.println("OK");
  } else {
    Serial.println("ERROR");
  }

  Serial.print("[CONFIG] Aplicando frecuencia (903.9 MHz) y SF7... ");
  String cmdParams = "at+set_config=lorap2p:" + String(LORA_P2P_CONFIG);
  if (enviarComandoAT(cmdParams)) {
    Serial.println("OK");
  } else {
    Serial.println("ERROR");
  }

  Serial.print("[CONFIG] Activando receptor continuo... ");
  activarModoRecepcion();
  Serial.println("LISTO");

  // Iniciar micrófono INMP441
  iniciar_i2s();
  Serial.println("[SISTEMA] Iniciando monitor acústico en tiempo real...\n");
}

// ======================================================================================
// LOOP PRINCIPAL (VU-METER, CAPTURA DE VOZ Y COMANDOS SERIAL/LORA)
// ======================================================================================
void loop() {
  // 1. RECEPCIÓN LORA: Comprobar respuestas (ACKs) o mensajes desde el S3 CAM
  if (LoRaSerial.available()) {
    String linea = LoRaSerial.readStringUntil('\n');
    linea.trim();
    if (linea.length() > 0) {
      if (linea.startsWith("at+recv=")) {
        procesarPaqueteRecibido(linea);
      } else if (linea != "OK") {
        Serial.printf("[MODEM RAK811]: %s\n", linea.c_str());
      }
    }
  }

  // 2. ENTRADA MANUAL POR MONITOR SERIAL: Permite probar sin hablar
  if (Serial.available()) {
    String entrada = Serial.readStringUntil('\n');
    entrada.trim();
    if (entrada.length() > 0) {
      if (entrada.equalsIgnoreCase("uno") || entrada == "1") {
        Serial.println("\n>> [MANUAL] Disparando comando 'UNO' por LoRa...");
        digitalWrite(PIN_LED_ACTUADOR, HIGH);
        enviarMensajeLoRa("UNO");
        return;
      } 
      else if (entrada.equalsIgnoreCase("dos") || entrada == "2") {
        Serial.println("\n>> [MANUAL] Disparando comando 'DOS' por LoRa...");
        digitalWrite(PIN_LED_ACTUADOR, LOW);
        enviarMensajeLoRa("DOS");
        return;
      } 
      else if (entrada.equalsIgnoreCase("C")) {
        Serial.println("\n>>> [DISPARO MANUAL] Forzando captura de 1 segundo...");
        capturar_y_clasificar(NULL, 0);
        return;
      } 
      else if (entrada.startsWith("at+") || entrada.startsWith("AT+")) {
        LoRaSerial.printf("%s\r\n", entrada.c_str());
        return;
      } 
      else {
        enviarMensajeLoRa(entrada);
        return;
      }
    }
  }

  // 3. CAPTURA Y MONITOREO CONTINUO DEL MICRÓFONO INMP441
  size_t bytes_leidos = 0;
  esp_err_t err = i2s_read(
    I2S_PORT,
    (void*)buffer_i2s_estereo,
    sizeof(buffer_i2s_estereo),
    &bytes_leidos,
    portMAX_DELAY
  );

  if (err != ESP_OK || bytes_leidos == 0) return;

  int total_pares = bytes_leidos / (sizeof(int32_t) * 2);
  int64_t suma_cuadrados = 0;
  int16_t valor_max = -32768;
  int16_t valor_min = 32767;
  int16_t bloque_actual[BUFFER_DMA_SAMPLES];

  for (int i = 0; i < total_pares && i < BUFFER_DMA_SAMPLES; i++) {
    // Canal Derecho (muestra impar)
    int32_t muestra_raw = buffer_i2s_estereo[i * 2 + 1];
    bloque_actual[i] = procesar_muestra(muestra_raw);

    if (bloque_actual[i] > valor_max) valor_max = bloque_actual[i];
    if (bloque_actual[i] < valor_min) valor_min = bloque_actual[i];

    suma_cuadrados += (int64_t)bloque_actual[i] * bloque_actual[i];
  }

  float rms = sqrt((float)suma_cuadrados / total_pares);
  int16_t vpp = valor_max - valor_min;

  // VU-Meter en vivo cada 100 ms
  unsigned long ahora = millis();
  if (ahora - ultimo_reporte_vumeter >= 100) {
    ultimo_reporte_vumeter = ahora;

    int barras = (int)(rms / 120.0f);
    if (barras > 20) barras = 20;

    char barra_grafica[25];
    for (int b = 0; b < 20; b++) {
      barra_grafica[b] = (b < barras) ? '=' : ' ';
    }
    barra_grafica[20] = '\0';

    const char* estado = (rms > 1400) ? "Voz Fuerte" : 
                         (rms > 600)  ? "Voz Normal" : 
                         (rms > 200)  ? "Susurro" : "Silencio";

    Serial.printf("[%s] RMS:%5.0f | Vpp:%5d | CH: DER | %s\n", 
                  barra_grafica, rms, vpp, estado);
  }

  // DISPARO AUTOMÁTICO AL DETECTAR VOZ
  if (rms >= UMBRAL_VOZ_RMS) {
    Serial.printf("\n>>> [¡VOZ DETECTADA! RMS: %.0f] Iniciando captura de 1 segundo...\n", rms);
    capturar_y_clasificar(bloque_actual, total_pares);
  } else {
    // Guardar en el pre-búfer para no recortar la primera sílaba
    for (int i = 0; i < total_pares && i < BUFFER_DMA_SAMPLES; i++) {
      buffer_previo[i] = bloque_actual[i];
    }
    muestras_previas = (total_pares < BUFFER_DMA_SAMPLES) ? total_pares : BUFFER_DMA_SAMPLES;
  }
}
