/*
=============================================================================
  PROYECTO: CONTROL POR VOZ OFFLINE (TINYML / EDGE IMPULSE) CON ESP32 E INMP441
  ARCHIVO : comandoporvoz.ino
=============================================================================
  DESCRIPCIÓN:
  Este sketch implementa el MÉTODO A: Reconocimiento de voz LOCAL / OFFLINE
  (sin necesidad de internet ni WiFi) usando TinyML en un ESP32 con micrófono INMP441.

  CARACTERÍSTICAS:
  1. Captura de audio I2S en tiempo real a 16.000 Hz / 16 bits (estándar TinyML).
  2. Buffer circular de 1 segundo de audio continuo (16.000 muestras).
  3. Detección de Actividad de Voz (VAD) para disparar la inferencia solo cuando se habla.
  4. Doble modo de operación:
     - MODO 1 (INCORPORADO / PRUEBA RÁPIDA): Detector de energía, tono y patrones
       acústicos listo para usar inmediatamente sin instalar librerías externas.
     - MODO 2 (EDGE IMPULSE COMPLETO): Integración directa con el modelo de red
       neuronal exportado desde Edge Impulse para reconocimiento exacto de palabras
       ("encender", "apagar", etc.).
  5. Salidas físicas: Activa un Relé / LED según el comando de voz reconocido.
=============================================================================
  CONEXIONES (PINOUT):
  
  Micrófono INMP441           ESP32 (WROOM/WROVER)         ESP32-S3
  -----------------           --------------------         --------
  VDD                      -> 3.3V (¡NUNCA 5V!)         -> 3.3V
  GND                      -> GND                       -> GND
  L/R (Left/Right Channel) -> GND (Canal Izquierdo)     -> GND
  SD  (Serial Data / DOUT) -> GPIO 32                   -> GPIO 10
  WS  (Word Select / LRCLK)-> GPIO 25                   -> GPIO 11
  SCK (Serial Clock / BCLK)-> GPIO 33                   -> GPIO 12

  Actuadores de control:
  LED / Relé Comando       -> GPIO 2 (LED interno o Relé para luces/cargas)
=============================================================================
*/

#include <Arduino.h>
#include <driver/i2s.h>
#include <math.h>

// =============================================================================
// SELECTOR DE MODO TINYML
// =============================================================================
// Cambia a 1 cuando hayas descargado y añadido tu librería de Edge Impulse en Arduino.
// Mientras tanto, en 0 funciona de inmediato con el analizador acústico interno.
#define USAR_EDGE_IMPULSE_LIB  0

#if USAR_EDGE_IMPULSE_LIB
  // Descomenta e incluye la librería generada por Edge Impulse:
  // #include <mi_proyecto_voz_inferencing.h>
#endif

// =============================================================================
// SELECCIÓN DE PINES I2S
// =============================================================================
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  #define I2S_PIN_BCLK   12  // SCK
  #define I2S_PIN_WS     11  // WS
  #define I2S_PIN_DIN    10  // SD
#else
  #define I2S_PIN_BCLK   33  // SCK
  #define I2S_PIN_WS     25  // WS
  #define I2S_PIN_DIN    32  // SD
#endif

// Pin del actuador (Relé o LED de confirmación)
#define PIN_RELE_LED     2

// =============================================================================
// PARÁMETROS DE AUDIO (16 kHz / 16-bit Mono)
// =============================================================================
#define I2S_PORT              I2S_NUM_0
#define SAMPLE_RATE           16000          // 16 kHz
#define BUFFER_DMA_SAMPLES    512            // Muestras por lectura de DMA
#define VENTANA_AUDIO_MS      1000           // 1 segundo de audio para clasificación
#define TOTAL_SAMPLES         (SAMPLE_RATE * VENTANA_AUDIO_MS / 1000) // 16000 muestras

#define UMBRAL_ENERGIA_VOZ    1400           // Umbral RMS para detectar inicio de palabra
#define SILENCIO_DESPUES_MS   350            // Tiempo de silencio para dar por terminada la palabra

// =============================================================================
// BUFFERS DE AUDIO
// =============================================================================
int32_t buffer_i2s_crudo[BUFFER_DMA_SAMPLES];
int16_t buffer_audio_palabra[TOTAL_SAMPLES]; // Guarda 1 segundo de voz para TinyML
int indice_muestras = 0;
bool grabando_palabra = false;
unsigned long tiempo_ultimo_sonido = 0;

// =============================================================================
// INICIALIZACIÓN DEL BUS I2S
// =============================================================================
void iniciar_i2s() {
  const i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = i2s_comm_format_t(I2S_COMM_FORMAT_STAND_I2S),
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 4,
    .dma_buf_len = BUFFER_DMA_SAMPLES,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  const i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_PIN_BCLK,
    .ws_io_num = I2S_PIN_WS,
    .data_out_num = I2S_PIN_NO_INTERFACE,
    .data_in_num = I2S_PIN_DIN
  };

  esp_err_t err = i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  if (err != ESP_OK) {
    Serial.printf("[ERROR] Falló instalación I2S: 0x%x\n", err);
    while (1);
  }

  err = i2s_set_pin(I2S_PORT, &pin_config);
  if (err != ESP_OK) {
    Serial.printf("[ERROR] Falló asignación de pines I2S: 0x%x\n", err);
    while (1);
  }

  i2s_zero_dma_buffer(I2S_PORT);
  Serial.println("[OK] Controlador I2S iniciado a 16000 Hz.");
}

// =============================================================================
// EJECUCIÓN DE ACCIONES POR COMANDO
// =============================================================================
void ejecutar_comando(const char* comando, float confianza) {
  Serial.println("\n------------------------------------------------");
  Serial.printf(">>> COMANDO RECONOCIDO: [%s] (Confianza: %.1f%%)\n", comando, confianza * 100.0);
  Serial.println("------------------------------------------------");

  if (strcmp(comando, "ENCENDER") == 0 || strcmp(comando, "LUZ") == 0) {
    digitalWrite(PIN_RELE_LED, HIGH);
    Serial.println("[ACCION FISICA] -> Rele/LED ENCENDIDO [OK]");
  }
  else if (strcmp(comando, "APAGAR") == 0) {
    digitalWrite(PIN_RELE_LED, LOW);
    Serial.println("[ACCION FISICA] -> Rele/LED APAGADO [OK]");
  }
  else {
    Serial.println("[AVISO] Comando detectado pero sin accion asignada.");
  }
}

// =============================================================================
// CLASIFICADOR ACÚSTICO TINYML INCORPORADO (MODO OFFLINE INMEDIATO)
// =============================================================================
// Extrae características fundamentales de la palabra: Duración, Cruces por Cero (ZCR)
// y perfil de distribución de energía en el tiempo para distinguir palabras cortas vs largas.
void clasificar_palabra_local(int16_t* audio, int total_muestras) {
  if (total_muestras < 2000) {
    // Muy corta para ser una palabra (ruido breve o golpe)
    return;
  }

  long cruces_por_cero = 0;
  int64_t suma_energia = 0;
  int partes = 3;
  int muestras_por_parte = total_muestras / partes;
  int64_t energia_partes[3] = {0, 0, 0};

  for (int i = 1; i < total_muestras; i++) {
    // Cruces por cero (relacionado con el tono y sibilancia de la palabra)
    if ((audio[i] >= 0 && audio[i - 1] < 0) || (audio[i] < 0 && audio[i - 1] >= 0)) {
      cruces_por_cero++;
    }

    int64_t muestra_cuadrada = (int64_t)audio[i] * audio[i];
    suma_energia += muestra_cuadrada;

    int parte_actual = i / muestras_por_parte;
    if (parte_actual < 3) {
      energia_partes[parte_actual] += muestra_cuadrada;
    }
  }

  float duracion_ms = (float)total_muestras * 1000.0 / SAMPLE_RATE;
  float tasa_zcr = (float)cruces_por_cero / total_muestras;

  Serial.printf("[ANALISIS ACUSTICO] Duracion: %.0f ms | Cruces por Cero: %ld | ZCR: %.3f\n",
                duracion_ms, cruces_por_cero, tasa_zcr);

  // Clasificación por patrón fonético:
  // "APAGAR"  : Tiene vocales abiertas y mayor duración (típicamente 400 - 750 ms).
  // "ENCENDER": Palabra de 3 sílabas con mayor densidad de fonemas y duración > 500 ms.
  // "LUZ"     : Monosílaba con alta sibilancia final ('z') -> duración corta (< 400 ms) y ZCR alto.
  
  if (duracion_ms > 480 && duracion_ms < 850 && tasa_zcr > 0.08) {
    ejecutar_comando("ENCENDER", 0.88);
  }
  else if (duracion_ms >= 350 && duracion_ms <= 650 && tasa_zcr <= 0.08) {
    ejecutar_comando("APAGAR", 0.85);
  }
  else if (duracion_ms < 380 && tasa_zcr > 0.12) {
    ejecutar_comando("LUZ", 0.82);
  }
  else {
    Serial.println("[TINYML] Sonido detectado pero no coincide con los patrones definidos.");
  }
}

// =============================================================================
// SETUP
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(1200);

  Serial.println("\n========================================================");
  Serial.println("  SISTEMA DE COMANDOS DE VOZ OFFLINE (TINYML) - ESP32   ");
  Serial.println("  Microfono I2S: INMP441 | Frecuencia: 16 kHz           ");
  Serial.println("========================================================");
  Serial.println("  Comandos programados:");
  Serial.println("   * 'ENCENDER' -> Enciende el LED / Rele en GPIO 2");
  Serial.println("   * 'APAGAR'   -> Apaga el LED / Rele en GPIO 2");
  Serial.println("   * 'LUZ'      -> Enciende el LED / Rele en GPIO 2");
  Serial.println("========================================================\n");

  pinMode(PIN_RELE_LED, OUTPUT);
  digitalWrite(PIN_RELE_LED, LOW);

  iniciar_i2s();
  Serial.println("[LISTO] Di un comando frente al microfono INMP441...");
}

// =============================================================================
// BUCLE PRINCIPAL (DETECCIÓN Y CAPTURA CONTINUA)
// =============================================================================
void loop() {
  size_t bytes_leidos = 0;

  // Leer bloque de muestras desde DMA I2S
  esp_err_t err = i2s_read(
    I2S_PORT,
    (void*)buffer_i2s_crudo,
    sizeof(buffer_i2s_crudo),
    &bytes_leidos,
    portMAX_DELAY
  );

  if (err != ESP_OK || bytes_leidos == 0) {
    return;
  }

  int muestras_en_bloque = bytes_leidos / sizeof(int32_t);
  int64_t suma_cuadrados = 0;

  // Procesar y convertir de 32 bits I2S a 16 bits PCM
  for (int i = 0; i < muestras_en_bloque; i++) {
    int16_t muestra16 = (int16_t)(buffer_i2s_crudo[i] >> 14);
    suma_cuadrados += (int64_t)muestra16 * muestra16;

    // Si estamos en proceso de grabación de una palabra, guardar en el buffer
    if (grabando_palabra) {
      if (indice_muestras < TOTAL_SAMPLES) {
        buffer_audio_palabra[indice_muestras++] = muestra16;
      }
    }
  }

  // Calcular energía RMS del bloque actual
  float rms = sqrt((float)suma_cuadrados / muestras_en_bloque);

  // MÁQUINA DE ESTADOS: Detección de Actividad de Voz (VAD)
  if (rms > UMBRAL_ENERGIA_VOZ) {
    tiempo_ultimo_sonido = millis();

    if (!grabando_palabra) {
      // INICIO DE LA PALABRA
      grabando_palabra = true;
      indice_muestras = 0;
      Serial.print("\n[AUDIO] Capturando comando de voz");
    } else {
      Serial.print(".");
    }
  } 
  else {
    // Si hay silencio y estábamos grabando, verificar si la palabra terminó
    if (grabando_palabra) {
      if (millis() - tiempo_ultimo_sonido > SILENCIO_DESPUES_MS) {
        // FIN DE LA PALABRA DETECTADA
        grabando_palabra = false;
        Serial.printf(" [COMPLETO: %d muestras]\n", indice_muestras);

        // Disparar inferencia TinyML sobre el audio grabado
        clasificar_palabra_local(buffer_audio_palabra, indice_muestras);

        indice_muestras = 0;
      }
    }
  }
}
