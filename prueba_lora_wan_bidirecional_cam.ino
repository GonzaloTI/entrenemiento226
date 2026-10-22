/*
 * ======================================================================================
 * NODO 1: ESP32-S3 CAM - RECEPTOR LORA BIDIRECCIONAL CON CONTROL DE 2 LEDS (GPIO 21 & 41)
 * ======================================================================================
 * Archivo: prueba_lora_wan_bidirecional_cam.ino
 * Placa  : ESP32-S3 CAM (AI-Thinker / Freenove / Genérico S3)
 * Módulo : RAK811-H LoRa P2P (903.9 MHz)
 * 
 * DESCRIPCIÓN:
 * Este nodo actúa como receptor y actuador inteligente:
 * 1. Escucha permanentemente paquetes LoRa P2P provenientes del ESP32-WROOM (o Monitor Serie).
 * 2. Al recibir el comando "UNO":
 *    - Enciende simultáneamente el LED 1 (GPIO 21) y el LED 2 (GPIO 41).
 *    - Se mantienen ENCENDIDOS de forma indefinida.
 *    - Envía confirmación ACK ("ACK: LEDS_ENCENDIDOS") por LoRa al emisor.
 * 3. Al recibir el comando "DOS":
 *    - Apaga simultáneamente el LED 1 (GPIO 21) y el LED 2 (GPIO 41).
 *    - Se mantienen APAGADOS.
 *    - Envía confirmación ACK ("ACK: LEDS_APAGADOS") por LoRa al emisor.
 * 4. Muestra en el Monitor Serie toda la telemetría RF (RSSI, SNR, tamaño, estado de LEDs).
 * 5. También permite ingresar comandos manualmente por el Monitor Serie para pruebas.
 * 
 * CONEXIONES FÍSICAS:
 * 
 * 1. Módulo LoRa RAK811-H <---> ESP32-S3 CAM:
 *    - RAK811 Pin 6  (TX)  <---> ESP32-S3 GPIO 18 (RX2)
 *    - RAK811 Pin 7  (RX)  <---> ESP32-S3 GPIO 17 (TX2)
 *    - RAK811 Pin 17 (BOOT0)<---> GND (Fijar modo AT/Run)
 *    - RAK811 Pin 1/28(GND)<---> GND
 *    - RAK811 Pin 11 (VCC) <---> 3.3V
 * 
 * 2. LED RGB (Ánodo Común) <---> ESP32-S3 CAM:
 *    - Pata Común (la más larga)                   <---> Pin 3.3V (3V3)
 *    - Pata R (Rojo)  (con resistencia 220-330Ω)   <---> GPIO 21
 *    - Pata G (Verde) (con resistencia 220-330Ω)   <---> GPIO 47
 *    - Pata B (Azul)  (opcional / sin conectar)
 * 
 * Monitor Serie: 115200 baudios | Configuración: "Ambos NL y CR" (Both NL & CR)
 * ======================================================================================
 */

#include <Arduino.h>

// ======================================================================================
// CONFIGURACIÓN DE PINES
// ======================================================================================
#define NOMBRE_NODO       "ESP32-S3-CAM (ACTUADOR 2 LEDS)"

// Pines de comunicación con el módem LoRa RAK811 en ESP32-S3 CAM
#define RAK_RX_PIN        18  // Conectado al TX del RAK811 (Pin 6)
#define RAK_TX_PIN        17  // Conectado al RX del RAK811 (Pin 7)
#define RAK_BAUD          115200

// Pines de los dos canales del LED RGB a controlar
#define PIN_LED1          21  // Canal R (Rojo) del LED RGB
#define PIN_LED2          47  // Canal G (Verde) del LED RGB

// ======================================================================================
// CONFIGURACIÓN DE POLARIDAD: LED RGB ÁNODO COMÚN (Pata larga a 3.3V)
// ======================================================================================
// En Ánodo Común:
// - Para ENCENDER se envía LOW  (0V -> conduce corriente hacia tierra)
// - Para APAGAR se envía HIGH   (3.3V -> 0V de diferencia de potencial)
#define LED_ON            LOW
#define LED_OFF           HIGH

// ======================================================================================
// PARÁMETROS DE RADIO LORA P2P (Deben ser EXACTAMENTE IGUALES en ambos nodos)
// Frecuencia: 903.9 MHz | SF: 7 | BW: 125 kHz (0) | CR: 4/5 (1) | Preámbulo: 8 | Pot: 5 dBm
// ======================================================================================
#define LORA_P2P_CONFIG   "903900000:7:0:1:8:5"

HardwareSerial LoRaSerial(2);

// ======================================================================================
// FUNCIONES AUXILIARES DE CONVERSIÓN HEX <-> TEXTO
// ======================================================================================

// Convierte texto legible ("UNO") a cadena HEX ("554E4F")
String stringToHex(const String& input) {
  String hexStr = "";
  for (unsigned int i = 0; i < input.length(); i++) {
    char buf[3];
    sprintf(buf, "%02X", (unsigned char)input[i]);
    hexStr += buf;
  }
  return hexStr;
}

// Convierte cadena HEX ("554E4F") a texto legible ("UNO")
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
// COMUNICACIÓN AT CON EL MÓDEM RAK811
// ======================================================================================

// Envía un comando AT y espera respuesta "OK" o "ERROR"
bool enviarComandoAT(const String& cmd, uint32_t timeoutMs = 1500) {
  while (LoRaSerial.available()) LoRaSerial.read(); // Limpiar buffer previo
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

// Pone al RAK811 en modo Escucha permanente (transfer_mode: 1)
void activarModoRecepcion() {
  LoRaSerial.print("at+set_config=lorap2p:transfer_mode:1\r\n");
  delay(100);
  while (LoRaSerial.available()) LoRaSerial.read();
}

// Transmite un mensaje por LoRa P2P y retorna a modo escucha
void enviarMensajeLoRa(String mensaje) {
  mensaje.trim();
  if (mensaje.length() == 0) return;

  Serial.println();
  Serial.printf(">> [TRANSMITIENDO RESPUESTA LORA] \"%s\"\n", mensaje.c_str());

  // 1. Cambiar a modo Emisor (Sender Mode = 2)
  LoRaSerial.print("at+set_config=lorap2p:transfer_mode:2\r\n");
  delay(100);
  while (LoRaSerial.available()) LoRaSerial.read();

  // 2. Convertir texto a HEX y transmitir
  String payloadHex = stringToHex(mensaje);
  LoRaSerial.printf("at+send=lorap2p:%s\r\n", payloadHex.c_str());

  // 3. Esperar a que la radio termine de emitir el paquete
  delay(500);
  while (LoRaSerial.available()) LoRaSerial.read();

  // 4. Volver inmediatamente a modo Escucha permanente
  activarModoRecepcion();
  Serial.println(">> [ENVIADO] Paquete emitido al aire. Escuchando activamente...");
}

// ======================================================================================
// ACCIONES DE CONTROL DE LOS 2 LEDS
// ======================================================================================
void encenderAmbosLeds() {
  digitalWrite(PIN_LED1, LED_ON);
  digitalWrite(PIN_LED2, LED_ON);

  Serial.println("\n==================================================");
  Serial.println("  >>> ACCIÓN EJECUTADA: AMBOS LEDS ENCENDIDOS <<< ");
  Serial.println("  * Canal R (GPIO 21): [ENCENDIDO - ON]           ");
  Serial.println("  * Canal G (GPIO 41): [ENCENDIDO - ON]           ");
  Serial.println("  * Estado           : MANTENIDO ACTIVO           ");
  Serial.println("==================================================\n");

  // Responder con ACK al nodo emisor (ESP32-WROOM)
  enviarMensajeLoRa("ACK: LEDS_ENCENDIDOS");
}

void apagarAmbosLeds() {
  digitalWrite(PIN_LED1, LED_OFF);
  digitalWrite(PIN_LED2, LED_OFF);

  Serial.println("\n==================================================");
  Serial.println("  >>> ACCIÓN EJECUTADA: AMBOS LEDS APAGADOS <<<   ");
  Serial.println("  * Canal R (GPIO 21): [APAGADO - OFF]            ");
  Serial.println("  * Canal G (GPIO 41): [APAGADO - OFF]            ");
  Serial.println("  * Estado           : MANTENIDO APAGADO          ");
  Serial.println("==================================================\n");

  // Responder con ACK al nodo emisor (ESP32-WROOM)
  enviarMensajeLoRa("ACK: LEDS_APAGADOS");
}

// ======================================================================================
// PROCESAMIENTO DE TRAMAS RECIBIDAS (at+recv=<RSSI>,<SNR>,<Len>:<HEX>)
// ======================================================================================
void procesarPaqueteRecibido(String raw) {
  int dosPuntos = raw.indexOf(':');
  if (dosPuntos == -1) {
    Serial.printf("[INFO RAK811]: %s\n", raw.c_str());
    return;
  }

  // Extraer metadatos RF
  String meta = raw.substring(8, dosPuntos);
  String hexData = raw.substring(dosPuntos + 1);
  hexData.trim();

  int coma1 = meta.indexOf(',');
  int coma2 = meta.indexOf(',', coma1 + 1);
  String rssi = (coma1 != -1) ? meta.substring(0, coma1) : "?";
  String snr  = (coma1 != -1 && coma2 != -1) ? meta.substring(coma1 + 1, coma2) : "?";
  String len  = (coma2 != -1) ? meta.substring(coma2 + 1) : "?";

  // Convertir contenido HEX a texto legible
  String texto = hexToString(hexData);
  texto.trim();

  Serial.println();
  Serial.println("**************************************************");
  Serial.println("      >>> [MENSAJE RECIBIDO POR LORA] <<<         ");
  Serial.println("**************************************************");
  Serial.printf("  Comando/Texto  : \"%s\"\n", texto.c_str());
  Serial.printf("  Intensidad RSSI: %s dBm\n", rssi.c_str());
  Serial.printf("  Calidad SNR    : %s dB\n", snr.c_str());
  Serial.printf("  Tamaño         : %s bytes\n", len.c_str());
  Serial.printf("  Hexadecimal    : %s\n", hexData.c_str());
  Serial.println("**************************************************");

  // EVALUAR COMANDO RECIBIDO
  String cmdNormalizado = texto;
  cmdNormalizado.toUpperCase();

  if (cmdNormalizado.indexOf("UNO") != -1 || cmdNormalizado.indexOf("ENCENDER") != -1 || cmdNormalizado == "1") {
    encenderAmbosLeds();
  } 
  else if (cmdNormalizado.indexOf("DOS") != -1 || cmdNormalizado.indexOf("APAGAR") != -1 || cmdNormalizado == "2") {
    apagarAmbosLeds();
  } 
  else {
    Serial.printf("[INFO] Mensaje no es comando de control de leds: \"%s\"\n\n", texto.c_str());
  }
}

// ======================================================================================
// SETUP
// ======================================================================================
void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 2000);

  Serial.println("\n========================================================");
  Serial.printf("   SISTEMA LORA P2P - [%s]\n", NOMBRE_NODO);
  Serial.println("   Receptor y Controlador de 2 LEDs (GPIO 21 y 41)");
  Serial.println("========================================================");

  // Configuración de los pines de salida para los LEDs (Ánodo Común: pata larga en 3.3V)
  pinMode(PIN_LED1, OUTPUT);
  pinMode(PIN_LED2, OUTPUT);
  digitalWrite(PIN_LED1, LED_OFF); // Inicialmente apagados
  digitalWrite(PIN_LED2, LED_OFF);

  // Test visual de inicio: Alumbran un instante y se apagan para verificar que funcionan
  Serial.println("[TEST HARDWARE] Probando LED RGB (Ánodo Común - Pata larga en 3.3V)...");
  Serial.println("  -> Encendiendo Canal R (GPIO 21) y Canal G (GPIO 41)...");
  digitalWrite(PIN_LED1, LED_ON);
  digitalWrite(PIN_LED2, LED_ON);
  delay(1000);  // Se mantienen alumbrando 1 segundo para verificar su funcionamiento

  Serial.println("  -> Apagando ambos canales...");
  digitalWrite(PIN_LED1, LED_OFF);
  digitalWrite(PIN_LED2, LED_OFF);
  delay(300);
  Serial.println("[TEST HARDWARE] LED RGB verificado correctamente y apagado.\n");

  // Inicializar puerto serie de comunicación con el RAK811
  LoRaSerial.begin(RAK_BAUD, SERIAL_8N1, RAK_RX_PIN, RAK_TX_PIN);
  delay(500);

  // 1. Fijar modo LoRa P2P
  Serial.print("[CONFIG] Fijando modo LoRa P2P... ");
  if (enviarComandoAT("at+set_config=lora:work_mode:1")) {
    Serial.println("OK");
  } else {
    Serial.println("ERROR");
  }

  // 2. Aplicar parámetros de radiofrecuencia (903.9 MHz, SF7, 125 kHz)
  Serial.print("[CONFIG] Aplicando frecuencia (903.9 MHz) y SF7... ");
  String cmdParams = "at+set_config=lorap2p:" + String(LORA_P2P_CONFIG);
  if (enviarComandoAT(cmdParams)) {
    Serial.println("OK");
  } else {
    Serial.println("ERROR");
  }

  // 3. Activar receptor permanente
  Serial.print("[CONFIG] Activando receptor continuo... ");
  activarModoRecepcion();
  Serial.println("LISTO");

  Serial.println("\n--------------------------------------------------------");
  Serial.println(" ESP32-S3 CAM LISTO Y ESCUCHANDO COMANDOS LORA:");
  Serial.println("  * Al recibir 'UNO' -> Encenderá ambos LEDs (21 y 41)");
  Serial.println("  * Al recibir 'DOS' -> Apagará ambos LEDs (21 y 41)");
  Serial.println(" También puedes escribir 'uno' o 'dos' aquí en la consola.");
  Serial.println("--------------------------------------------------------\n");
}

// ======================================================================================
// LOOP PRINCIPAL
// ======================================================================================
void loop() {
  // 1. RECEPCIÓN LORA: Verificar si el módem RAK811 recibió datos del aire
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

  // 2. ENTRADA SERIAL: Permite probar comandos directamente desde la PC
  if (Serial.available()) {
    String entrada = Serial.readStringUntil('\n');
    entrada.trim();
    if (entrada.length() > 0) {
      if (entrada.equalsIgnoreCase("uno") || entrada == "1") {
        Serial.println(">> [MANUAL SERIAL] Forzando encendido de LEDs...");
        encenderAmbosLeds();
      } 
      else if (entrada.equalsIgnoreCase("dos") || entrada == "2") {
        Serial.println(">> [MANUAL SERIAL] Forzando apagado de LEDs...");
        apagarAmbosLeds();
      } 
      else if (entrada.startsWith("at+") || entrada.startsWith("AT+")) {
        // Enviar comando AT directo al módem
        LoRaSerial.printf("%s\r\n", entrada.c_str());
      } 
      else {
        // Enviar texto libre por LoRa
        enviarMensajeLoRa(entrada);
      }
    }
  }
}
