/*
 * =========================================================================
 * DIAGNÓSTICO COMPLETO Y PUENTE INTERACTIVO
 * ESP32 WROOM <-> LORA RAK811-H (Firmware V3.x)
 * =========================================================================
 * Conexiones:
 *   ESP32 GPIO 16 (RX2) <---> RAK811 Pin 6  (USART1_TX)
 *   ESP32 GPIO 17 (TX2) <---> RAK811 Pin 7  (USART1_RX)
 *   ESP32 GND           <---> RAK811 Pin 17 (BOOT0) y Pin 1/28 (GND)
 *   ESP32 3V3           <---> RAK811 Pin 11 (VCC)
 * 
 * Monitor Serie: 115200 baudios | Ambos NL y CR
 * =========================================================================
 */

#include <Arduino.h>

#define RAK_RX_PIN 16  // Al TX del RAK811 (Pin 6)
#define RAK_TX_PIN 17  // Al RX del RAK811 (Pin 7)
#define RAK_BAUD   115200

HardwareSerial LoRaSerial(2);

// Función para enviar comando AT y esperar la respuesta completa
void ejecutarComando(const char* titulo, const char* comando, uint32_t timeoutMs = 2000) {
  Serial.println();
  Serial.println("==================================================");
  Serial.printf(">> %s\n", titulo);
  Serial.printf("   Comando: %s\n", comando);
  Serial.println("--------------------------------------------------");

  // Limpiar buffer residual
  while (LoRaSerial.available()) {
    LoRaSerial.read();
  }

  // Enviar el comando con salto de línea CRLF
  LoRaSerial.printf("%s\r\n", comando);

  unsigned long inicio = millis();
  String respuesta = "";
  
  while (millis() - inicio < timeoutMs) {
    while (LoRaSerial.available()) {
      char c = LoRaSerial.read();
      respuesta += c;
    }
    // Si ya devolvió OK o ERROR, terminamos de esperar
    if (respuesta.indexOf("OK") != -1 || respuesta.indexOf("ERROR") != -1) {
      delay(50); // Pequeña pausa para capturar bytes finales
      while (LoRaSerial.available()) {
        respuesta += (char)LoRaSerial.read();
      }
      break;
    }
    delay(10);
  }

  if (respuesta.length() > 0) {
    Serial.print(respuesta);
  } else {
    Serial.println("[SIN RESPUESTA]");
  }
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 2000);

  Serial.println("\n**************************************************");
  Serial.println("   DIAGNOSTICO INICIAL RAK811-H (LORA / LORAWAN)   ");
  Serial.println("**************************************************");

  // Iniciar UART directamente a 115200 baudios
  LoRaSerial.begin(RAK_BAUD, SERIAL_8N1, RAK_RX_PIN, RAK_TX_PIN);
  delay(500);

  // 1. Version de Firmware
  ejecutarComando("1. VERSION DE FIRMWARE", "at+version", 1500);

  // 2. Estado del Hardware / Dispositivo
  ejecutarComando("2. ESTADO DEL DISPOSITIVO (HARDWARE)", "at+get_config=device:status", 2000);

  // 3. Parametros LoRa / LoRaWAN (DevEUI, AppEUI, Region, Modo, Clase)
  ejecutarComando("3. CONFIGURACION LORAWAN (DevEUI, Keys, Region)", "at+get_config=lora:status", 2500);

  // 4. Canales de Frecuencia activos
  ejecutarComando("4. CANALES Y FRECUENCIAS DE RADIO", "at+get_config=lora:channel", 2000);

  Serial.println();
  Serial.println("==================================================");
  Serial.println("   DIAGNOSTICO FINALIZADO - MODO PUENTE ACTIVO    ");
  Serial.println("==================================================");
  Serial.println("Puedes enviar cualquier comando AT desde el monitor.");
  Serial.println("Ejemplos útiles:");
  Serial.println("  at+help");
  Serial.println("  at+get_config=lora:status");
  Serial.println("  at+set_config=device:restart");
  Serial.println("--------------------------------------------------\n");
}

void loop() {
  // Puente interactivo:
  // Del RAK811 hacia la PC
  if (LoRaSerial.available()) {
    Serial.write(LoRaSerial.read());
  }

  // De la PC hacia el RAK811
  if (Serial.available()) {
    LoRaSerial.write(Serial.read());
  }
}
