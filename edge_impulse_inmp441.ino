/*
=============================================================================
  PROYECTO: RECONOCIMIENTO DE VOZ TINYML CON VU-METER EN TIEMPO REAL
  ARCHIVO : edge_impulse_inmp441.ino
  PLACA   : ESP32 WROOM (38 pines) + INMP441
=============================================================================
  CARACTERÍSTICAS:
  1. MONITOR VU-METER EN VIVO:
     Muestra en tiempo real la barra de audio y el nivel RMS en el Monitor Serial.
  2. DETECCIÓN AUTOMÁTICA EN CANAL DERECHO:
     Configurado para capturar el Canal Derecho (CH: DER), que es donde tu
     micrófono está activo (silencio = ~30 RMS, voz = 1000 - 2500 RMS).
  3. DISPARO INTELIGENTE:
     - Automático: Al hablar (RMS > 600), captura 1 segundo exacto.
     - Manual: Puedes enviar la letra 'C' o presionar Enter en el Monitor Serial
       para forzar una captura inmediata de 1 segundo.
  4. INFERENCIA EDGE IMPULSE (TINYML OFFLINE):
     Clasifica "uno", "dos" o "ruido".
     - "dos" -> Enciende LED en GPIO 2 (y se mantiene encendido).
     - "uno" -> Apaga LED en GPIO 2 (y se mantiene apagado).
=============================================================================
  CONEXIONES (ESP32 38 PINES):
  INMP441          ESP32 (38 pines)
  -------          ----------------
  VDD           -> 3V3 (¡NUNCA 5V!)
  GND           -> GND
  L/R           -> GND (o 3.3V)
  SD            -> D32 (GPIO 32)
  WS            -> D25 (GPIO 25)
  SCK           -> D33 (GPIO 33)
  LED / Relé    -> GPIO 2
=============================================================================
*/

#include <Arduino.h>
#include <driver/i2s.h>
#include <math.h>

// Librería descargada de Edge Impulse
#include <ernestoman-project-1_inferencing.h>

// =============================================================================
// PINES Y CONFIGURACIÓN I2S
// =============================================================================
#define I2S_PIN_BCLK          33  // SCK
#define I2S_PIN_WS            25  // WS
#define I2S_PIN_DIN           32  // SD

#define I2S_PORT              I2S_NUM_0
#define SAMPLE_RATE           16000
#define BUFFER_DMA_SAMPLES    256

#define PIN_LED_ACTUADOR      2   // LED integrado del ESP32

// En silencio el RMS está en ~30-50; tu voz llega a 1200-2200.
// Un umbral de 600 es perfecto para ignorar ruidos suaves y activar solo con voz clara.
#define UMBRAL_VOZ_RMS        600
#define UMBRAL_CONFIANZA      0.60f // 60% mínimo

// =============================================================================
// BUFFERS DE AUDIO
// =============================================================================
int32_t buffer_i2s_estereo[BUFFER_DMA_SAMPLES * 2];
int16_t buffer_audio_inferencia[EI_CLASSIFIER_RAW_SAMPLE_COUNT];

// Pre-búfer para no cortar el primer fonema ("u-")
int16_t buffer_previo[BUFFER_DMA_SAMPLES];
int muestras_previas = 0;

float filtro_dc = 0.0f;
unsigned long ultimo_reporte_vumeter = 0;

// =============================================================================
// PROCESAMIENTO DE AUDIO CON FILTRO DC
// =============================================================================
inline int16_t procesar_muestra(int32_t muestra_cruda) {
  // Desplazamiento >> 15 (escala limpia sin saturación)
  int32_t muestra_escalada = muestra_cruda >> 15;

  // Filtro pasa-altos suave para centrar en 0 y quitar zumbido DC
  filtro_dc = 0.992f * filtro_dc + 0.008f * (float)muestra_escalada;
  int32_t limpia = muestra_escalada - (int32_t)filtro_dc;

  if (limpia > 30000) limpia = 30000;
  if (limpia < -30000) limpia = -30000;

  return (int16_t)limpia;
}

// =============================================================================
// CALLBACK PARA EDGE IMPULSE
// =============================================================================
static int obtener_datos_audio(size_t offset, size_t length, float *out_ptr) {
  for (size_t i = 0; i < length; i++) {
    out_ptr[i] = (float)buffer_audio_inferencia[offset + i];
  }
  return 0;
}

// =============================================================================
// INICIALIZACIÓN I2S
// =============================================================================
void iniciar_i2s() {
  const i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT, // Modo estéreo
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
  Serial.println("[OK] Controlador I2S iniciado (16000 Hz / Mono Canal Derecho).");
}

// =============================================================================
// CLASIFICACIÓN CON EDGE IMPULSE
// =============================================================================
void clasificar_audio() {
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

    if (strcmp(etiqueta, "dos") == 0) {
      digitalWrite(PIN_LED_ACTUADOR, HIGH);
      Serial.println("\n>>> [ACCIÓN] Comando 'DOS' -> LED ENCENDIDO [ON] (Se mantendrá así)");
    } 
    else if (strcmp(etiqueta, "uno") == 0) {
      digitalWrite(PIN_LED_ACTUADOR, LOW);
      Serial.println("\n>>> [ACCIÓN] Comando 'UNO' -> LED APAGADO [OFF]");
    } 
    else if (strcmp(etiqueta, "ruido") == 0) {
      Serial.println("[FILTRO] -> Ruido ambiental ignorado.");
    }
  } else {
    Serial.println("[AVISO] Sonido no concluyente (<60% confianza).");
  }

  Serial.println("------------------------------------------------\n");
  i2s_zero_dma_buffer(I2S_PORT);
  ultimo_reporte_vumeter = millis() + 500; // Pausa para que el usuario lea el resultado
}

// =============================================================================
// CAPTURA DE VENTANA DE 1 SEGUNDO (16000 MUESTRAS)
// =============================================================================
void capturar_y_clasificar(int16_t* bloque_inicial, int cant_inicial) {
  int muestras_grabadas = 0;

  // 1. Guardar pre-búfer anterior (para capturar la primera sílaba "u-")
  for (int i = 0; i < muestras_previas && muestras_grabadas < EI_CLASSIFIER_RAW_SAMPLE_COUNT; i++) {
    buffer_audio_inferencia[muestras_grabadas++] = buffer_previo[i];
  }

  // 2. Guardar bloque actual que superó el umbral
  for (int i = 0; i < cant_inicial && muestras_grabadas < EI_CLASSIFIER_RAW_SAMPLE_COUNT; i++) {
    buffer_audio_inferencia[muestras_grabadas++] = bloque_inicial[i];
  }

  // 3. Completar el resto de la ventana de 1 segundo
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
        // En tu hardware, el micrófono emite por el Canal Derecho (índice impar)
        int32_t muestra_raw = buffer_i2s_estereo[i * 2 + 1];
        buffer_audio_inferencia[muestras_grabadas++] = procesar_muestra(muestra_raw);
      }
    }
  }

  Serial.println("[OK] 1 segundo de audio capturado con éxito.");
  clasificar_audio();
  muestras_previas = 0;
}

// =============================================================================
// SETUP
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(1200);

  Serial.println("\n========================================================");
  Serial.println("  SISTEMA DE COMANDOS DE VOZ TINYML CON VU-METER EN VIVO");
  Serial.println("========================================================");
  Serial.println("  * Clases soportadas: 'uno', 'dos', 'ruido'");
  Serial.println("  * Umbral de disparo : RMS > 600");
  Serial.println("  * Disparo manual   : Envía 'C' por Serial para capturar");
  Serial.println("========================================================\n");

  pinMode(PIN_LED_ACTUADOR, OUTPUT);
  digitalWrite(PIN_LED_ACTUADOR, LOW);

  iniciar_i2s();
  Serial.println("[SISTEMA] Iniciando monitor acústico en tiempo real...\n");
}

// =============================================================================
// LOOP PRINCIPAL (VU-METER EN VIVO Y CAPTURA)
// =============================================================================
void loop() {
  // Comprobación de disparo manual por Serial (escribe 'C' o presiona Enter)
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'C' || c == 'c' || c == '\n') {
      Serial.println("\n>>> [DISPARO MANUAL] Capturando 1 segundo...");
      capturar_y_clasificar(NULL, 0);
      return;
    }
  }

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
    // Canal Derecho (donde está activo tu micrófono INMP441)
    int32_t muestra_raw = buffer_i2s_estereo[i * 2 + 1];
    bloque_actual[i] = procesar_muestra(muestra_raw);

    if (bloque_actual[i] > valor_max) valor_max = bloque_actual[i];
    if (bloque_actual[i] < valor_min) valor_min = bloque_actual[i];

    suma_cuadrados += (int64_t)bloque_actual[i] * bloque_actual[i];
  }

  float rms = sqrt((float)suma_cuadrados / total_pares);
  int16_t vpp = valor_max - valor_min;

  // Imprimir VU-meter en vivo cada 100 ms (igual que en prueba_inmp441.ino)
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

  // DISPARO AUTOMÁTICO: Si el RMS supera el umbral de voz
  if (rms >= UMBRAL_VOZ_RMS) {
    Serial.printf("\n>>> [¡VOZ DETECTADA! RMS: %.0f] Iniciando captura de 1 segundo...\n", rms);
    capturar_y_clasificar(bloque_actual, total_pares);
  } else {
    // Guardar bloque actual como bloque previo (para no perder el inicio de la palabra)
    for (int i = 0; i < total_pares && i < BUFFER_DMA_SAMPLES; i++) {
      buffer_previo[i] = bloque_actual[i];
    }
    muestras_previas = (total_pares < BUFFER_DMA_SAMPLES) ? total_pares : BUFFER_DMA_SAMPLES;
  }
}
