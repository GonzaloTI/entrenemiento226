/*
=============================================================================
  PROYECTO: TEST DEFINITIVO Y DIAGNÓSTICO DEL MICRÓFONO I2S INMP441
  ARCHIVO : prueba_inmp441.ino
  PLACA   : ESP32 (WROOM, WROVER 38 PINES) / ESP32-S3
=============================================================================
  MEJORAS IMPLEMENTADAS:
  1. CANAL DUAL INTELIGENTE (Auto-detección L/R):
     Lee en modo estéreo y selecciona automáticamente el canal con señal de audio.
     ¡Funciona tanto si L/R está en GND como si está en 3.3V o invertido por el driver!
  2. GRABACIÓN EN RAM BUFFERIZADA (CERO CORTES):
     Graba los 5 segundos directamente en memoria SRAM y luego los transmite a la PC.
     Esto elimina las caídas de paquetes, el audio robótico y los saltos.
  3. FILTRO DE BLOQUEO DC (High-Pass):
     Elimina el zumbido de continua característico de los micrófonos I2S.
  4. DIAGNÓSTICO EN TIEMPO REAL:
     Indica en pantalla qué canal (Izquierdo o Derecho) está recibiendo el sonido.
=============================================================================
  CONEXIONES OBLIGATORIAS:
  INMP441          ESP32 WROOM (38 pines)
  -------          ----------------------
  VDD           -> 3V3 (¡NUNCA A 5V / VIN!)
  GND           -> GND
  L/R           -> GND (Recomendado, aunque el código detecta ambos)
  SD            -> D32 (GPIO 32)
  WS            -> D25 (GPIO 25)
  SCK           -> D33 (GPIO 33)
=============================================================================
*/

#include <Arduino.h>
#include <driver/i2s.h>
#include <math.h>

// Pines para ESP32 estándar

#define I2S_PIN_BCLK   33  // SCK
#define I2S_PIN_WS     25  // WS
#define I2S_PIN_DIN    32  // SD


#define I2S_PORT              I2S_NUM_0
#define SAMPLE_RATE           16000     // 16 kHz
#define BUFFER_DMA_SAMPLES    256       // 256 pares estéreo = 512 palabras de 32 bits
#define SEGUNDOS_GRABACION    5
#define MUESTRAS_GRABACION    (SAMPLE_RATE * SEGUNDOS_GRABACION) // 80000 muestras

// Modos de salida serial
enum ModoSalida {
  MODO_MONITOR_VU = 0,
  MODO_PLOTTER    = 1
};

ModoSalida modo_actual = MODO_MONITOR_VU;

// Buffer DMA estéreo (pares [L, R])
int32_t buffer_i2s_estereo[BUFFER_DMA_SAMPLES * 2];

// Variables de diagnósticoa
unsigned long bloques_en_cero = 0;
unsigned long total_bloques = 0;
unsigned long ultimo_reporte_ms = 0;
float filtro_dc = 0.0f;

// =============================================================================
// INICIALIZACIÓN DEL CONTROLADOR I2S EN MODO DUAL
// =============================================================================
void iniciar_i2s() {
  const i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    // Modo estéreo: captura ambos canales simultáneamente
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
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
    .data_out_num = -1, // Sin salida
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
  Serial.println("[OK] Controlador I2S iniciado (Modo Auto-Canal L/R a 16000 Hz).");
}

// =============================================================================
// CONVERSIÓN CON FILTRO DC Y SELECCIÓN AUTOMÁTICA DE CANAL ACTIVO
// =============================================================================
inline int16_t procesar_par_muestras(int32_t canal_l, int32_t canal_r) {
  // El INMP441 transmite en un solo canal y el otro queda en silencio (cero o ruido eléctrico muy bajo).
  // Seleccionamos automáticamente el canal con mayor magnitud:
  int32_t muestra_cruda = (abs(canal_l) >= abs(canal_r)) ? canal_l : canal_r;

  // Desplazamiento de bits: el INMP441 entrega 24 bits alineados a MSB en 32 bits
  int32_t muestra_escalada = muestra_cruda >> 14;

  // Filtro pasa-altos para eliminar el offset DC (desplazamiento de continua)
  filtro_dc = 0.995f * filtro_dc + 0.005f * (float)muestra_escalada;
  int32_t muestra_limpia = muestra_escalada - (int32_t)filtro_dc;

  // Limitador de seguridad (anti-clipping)
  if (muestra_limpia > 32767) muestra_limpia = 32767;
  if (muestra_limpia < -32768) muestra_limpia = -32768;

  return (int16_t)muestra_limpia;
}

// =============================================================================
// CABECERA WAV ESTÁNDAR (44 BYTES)
// =============================================================================
void enviar_cabecera_wav(uint32_t total_samples, uint32_t sample_rate) {
  uint32_t data_size = total_samples * sizeof(int16_t);
  uint32_t file_size = data_size + 36;
  uint16_t num_channels = 1;
  uint16_t bits_per_sample = 16;
  uint32_t byte_rate = sample_rate * num_channels * (bits_per_sample / 8);
  uint16_t block_align = num_channels * (bits_per_sample / 8);

  uint8_t header[44];
  header[0] = 'R'; header[1] = 'I'; header[2] = 'F'; header[3] = 'F';
  header[4] = (uint8_t)(file_size & 0xFF);
  header[5] = (uint8_t)((file_size >> 8) & 0xFF);
  header[6] = (uint8_t)((file_size >> 16) & 0xFF);
  header[7] = (uint8_t)((file_size >> 24) & 0xFF);
  header[8] = 'W'; header[9] = 'A'; header[10] = 'V'; header[11] = 'E';

  header[12] = 'f'; header[13] = 'm'; header[14] = 't'; header[15] = ' ';
  header[16] = 16; header[17] = 0; header[18] = 0; header[19] = 0;
  header[20] = 1; header[21] = 0;
  header[22] = (uint8_t)(num_channels & 0xFF);
  header[23] = (uint8_t)((num_channels >> 8) & 0xFF);
  header[24] = (uint8_t)(sample_rate & 0xFF);
  header[25] = (uint8_t)((sample_rate >> 8) & 0xFF);
  header[26] = (uint8_t)((sample_rate >> 16) & 0xFF);
  header[27] = (uint8_t)((sample_rate >> 24) & 0xFF);
  header[28] = (uint8_t)(byte_rate & 0xFF);
  header[29] = (uint8_t)((byte_rate >> 8) & 0xFF);
  header[30] = (uint8_t)((byte_rate >> 16) & 0xFF);
  header[31] = (uint8_t)((byte_rate >> 24) & 0xFF);
  header[32] = (uint8_t)(block_align & 0xFF);
  header[33] = (uint8_t)((block_align >> 8) & 0xFF);
  header[34] = (uint8_t)(bits_per_sample & 0xFF);
  header[35] = (uint8_t)((bits_per_sample >> 8) & 0xFF);

  header[36] = 'd'; header[37] = 'a'; header[38] = 't'; header[39] = 'a';
  header[40] = (uint8_t)(data_size & 0xFF);
  header[41] = (uint8_t)((data_size >> 8) & 0xFF);
  header[42] = (uint8_t)((data_size >> 16) & 0xFF);
  header[43] = (uint8_t)((data_size >> 24) & 0xFF);

  Serial.write(header, 44);
}

// =============================================================================
// GRABACIÓN EN RAM Y ENVÍO LIMPIO (SIN PÉRDIDAS NI AUDIO ROBÓTICO)
// =============================================================================
void ejecutar_grabacion_wav() {
  Serial.println("\n[GRABACION] Asignando memoria interna para 5 segundos...");

  // Dividimos los 160 KB en 10 bloques de 16 KB para evitar fragmentación
  const int NUM_BLOQUES = 10;
  const int MUESTRAS_POR_BLOQUE = MUESTRAS_GRABACION / NUM_BLOQUES; // 8000 muestras
  int16_t* bloques[NUM_BLOQUES];
  bool memoria_ok = true;

  for (int b = 0; b < NUM_BLOQUES; b++) {
    bloques[b] = (int16_t*)malloc(MUESTRAS_POR_BLOQUE * sizeof(int16_t));
    if (bloques[b] == NULL) {
      memoria_ok = false;
      Serial.printf("[ERROR] No se pudo asignar bloque %d\n", b);
    }
  }

  if (!memoria_ok) {
    Serial.println("[ERROR] Memoria insuficiente para buffer en RAM.");
    for (int b = 0; b < NUM_BLOQUES; b++) {
      if (bloques[b]) free(bloques[b]);
    }
    return;
  }

  Serial.println("[GRABACION] >> ¡GRABANDO AHORA! Habla al micrófono durante 5 segundos...");
  unsigned long tiempo_inicio = millis();

  // FASE 1: Grabar en RAM a 16 kHz puro sin tocar el puerto serie (cero caídas)
  for (int b = 0; b < NUM_BLOQUES; b++) {
    int muestras_en_bloque = 0;
    while (muestras_en_bloque < MUESTRAS_POR_BLOQUE) {
      size_t bytes_leidos = 0;
      esp_err_t err = i2s_read(
        I2S_PORT,
        (void*)buffer_i2s_estereo,
        sizeof(buffer_i2s_estereo),
        &bytes_leidos,
        portMAX_DELAY
      );

      if (err == ESP_OK && bytes_leidos > 0) {
        int pares = bytes_leidos / (sizeof(int32_t) * 2);
        for (int i = 0; i < pares && muestras_en_bloque < MUESTRAS_POR_BLOQUE; i++) {
          int32_t l = buffer_i2s_estereo[i * 2];
          int32_t r = buffer_i2s_estereo[i * 2 + 1];
          bloques[b][muestras_en_bloque++] = procesar_par_muestras(l, r);
        }
      }
    }
  }

  unsigned long duracion_real = millis() - tiempo_inicio;
  Serial.printf("[GRABACION] Grabacion finalizada en %lu ms. Transmitiendo a la PC...\n", duracion_real);

  // FASE 2: Transmitir el audio perfecto por Serial al script Python
  Serial.println("===START_WAV===");
  enviar_cabecera_wav(MUESTRAS_GRABACION, SAMPLE_RATE);

  for (int b = 0; b < NUM_BLOQUES; b++) {
    Serial.write((const uint8_t*)bloques[b], MUESTRAS_POR_BLOQUE * sizeof(int16_t));
    free(bloques[b]); // Liberar memoria de inmediato
  }

  Serial.flush();
  Serial.println("\n===END_WAV===");
  Serial.println("[GRABACION] ¡Transmision completada con exito!");
}

// =============================================================================
// MENÚ DE AYUDA
// =============================================================================
void imprimir_menu() {
  Serial.println("\n========================================================");
  Serial.println("      TEST AUTO-CANAL Y DIAGNÓSTICO INMP441 (ESP32)      ");
  Serial.println("========================================================");
  Serial.println("  Comandos en el Monitor Serial:");
  Serial.println("   [M] -> Modo MONITOR SERIAL con VU-Meter");
  Serial.println("   [P] -> Modo SERIAL PLOTTER (Forma de onda en vivo)");
  Serial.println("   [G] -> GRABAR 5 segundos en RAM y enviar WAV a la PC");
  Serial.println("   [H] -> Ver este menú");
  Serial.println("========================================================\n");
}

// =============================================================================
// SETUP
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(1200);

  imprimir_menu();
  iniciar_i2s();
  Serial.println("[SISTEMA] Listo. Habla, sopla o aplaude frente al microfono...\n");
}

// =============================================================================
// LOOP PRINCIPAL
// =============================================================================
void loop() {
  if (Serial.available()) {
    char cmd = (char)Serial.read();
    if (cmd == 'M' || cmd == 'm') {
      modo_actual = MODO_MONITOR_VU;
      Serial.println("\n>> MODO MONITOR SERIAL (VU-Meter y Diagnostico)");
    } else if (cmd == 'P' || cmd == 'p') {
      modo_actual = MODO_PLOTTER;
      Serial.println("\n>> MODO SERIAL PLOTTER. Abre: Herramientas -> Serial Plotter");
    } else if (cmd == 'G' || cmd == 'g') {
      ejecutar_grabacion_wav();
    } else if (cmd == 'H' || cmd == 'h') {
      imprimir_menu();
    }
  }

  // Leer bloque estéreo desde I2S
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
  int16_t valor_maximo = -32768;
  int16_t valor_minimo = 32767;
  bool todas_en_cero = true;
  long energia_l = 0;
  long energia_r = 0;

  for (int i = 0; i < total_pares; i++) {
    int32_t l = buffer_i2s_estereo[i * 2];
    int32_t r = buffer_i2s_estereo[i * 2 + 1];

    energia_l += abs(l >> 16);
    energia_r += abs(r >> 16);

    int16_t muestra = procesar_par_muestras(l, r);

    if (muestra != 0) todas_en_cero = false;
    if (muestra > valor_maximo) valor_maximo = muestra;
    if (muestra < valor_minimo) valor_minimo = muestra;

    suma_cuadrados += (int64_t)muestra * muestra;

    if (modo_actual == MODO_PLOTTER && (i % 4 == 0)) {
      Serial.printf("Audio:%d,Max_Escala:3000,Min_Escala:-3000\n", muestra);
    }
  }

  total_bloques++;
  if (todas_en_cero) bloques_en_cero++;

  if (modo_actual == MODO_MONITOR_VU) {
    unsigned long ahora = millis();
    if (ahora - ultimo_reporte_ms >= 120) {
      ultimo_reporte_ms = ahora;

      float rms = sqrt((float)suma_cuadrados / total_pares);
      int16_t pico_a_pico = valor_maximo - valor_minimo;

      int barras = (int)(rms / 150.0f);
      if (barras > 20) barras = 20;

      char barra_grafica[25];
      for (int b = 0; b < 20; b++) {
        barra_grafica[b] = (b < barras) ? '=' : ' ';
      }
      barra_grafica[20] = '\0';

      const char* canal_activo = (energia_l >= energia_r) ? "CH: IZQ (L)" : "CH: DER (R)";
      const char* estado = (rms > 2000) ? "Voz Fuerte/Grito" : 
                           (rms > 700)  ? "Voz Normal" : 
                           (rms > 250)  ? "Susurro" : "Silencio";

      Serial.printf("[%s] RMS:%5.0f | Vpp:%5d | %s | %s\n", 
                    barra_grafica, rms, pico_a_pico, canal_activo, estado);

      if (total_bloques >= 15 && (bloques_en_cero * 100 / total_bloques) > 85) {
        Serial.println("  >>> [AVISO]: Leyendo 0s continuos. Revisa cable SD en D32 y SCK en D33.");
        bloques_en_cero = 0;
        total_bloques = 0;
      }
    }
  }
}
