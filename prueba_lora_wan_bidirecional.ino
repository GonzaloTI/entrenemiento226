/*
 * =========================================================================
 * COMUNICACIÓN BIDIRECCIONAL LORA P2P (ESP32 <-> RAK811-H)
 * =========================================================================
 * Archivo: prueba_lora_wan_bidirecional.ino
 * 
 * Ambos ESP32 deben llevar este mismo código (o cambiando el NOMBRE_NODO).
 * Ambos escuchan permanentemente y cuando escribes un texto en el Monitor Serie,
 * lo transmiten por radio y vuelven a escuchar automáticamente.
 * 
 * Conexiones:
 *   ESP32 GPIO 16 (RX2) <---> RAK811 Pin 6  (USART1_TX)
 *   ESP32 GPIO 17 (TX2) <---> RAK811 Pin 7  (USART1_RX)
 *   ESP32 GND           <---> RAK811 Pin 17 (BOOT0) y Pin 1/28 (GND)
 *   ESP32 3V3           <---> RAK811 Pin 11 (VCC)
 * 
 * Monitor Serie: 115200 baudios | "Ambos NL y CR" (Both NL & CR)
 * =========================================================================
 */

#include <Arduino.h>

// =========================================================================
// SELECCIÓN DE PLACA (Descomenta la que corresponda a este ESP32)
// =========================================================================
// Opción A: ESP32 WROOM estándar (38 o 30 pines)
//#define ES_ESP32_WROOM

// Opción B: ESP32-S3 CAM (Descomenta esta línea si vas a subirlo al S3 CAM)
#define ES_ESP32_S3_CAM

#if defined(ES_ESP32_S3_CAM)
  #define NOMBRE_NODO  "NODO_S3_CAM"
  // Pines 100% seguros y libres en ESP32-S3 CAM (compatibles incluso con cámara activa)
  #define RAK_RX_PIN   18  // Al TX del RAK811 (Pin 6)
  #define RAK_TX_PIN   17  // Al RX del RAK811 (Pin 7)
#else
  #define NOMBRE_NODO  "NODO_WROOM"
  #define RAK_RX_PIN   16  // Al TX del RAK811 (Pin 6)
  #define RAK_TX_PIN   17  // Al RX del RAK811 (Pin 7)
#endif

#define RAK_BAUD     115200

// Parámetros de Radio LoRa P2P (Deben ser EXACTAMENTE IGUALES en ambos nodos)
// Frecuencia: 903.9 MHz (903900000 Hz)
// Spreading Factor: 7 | Bandwidth: 0 (125 kHz) | Coding Rate: 1 (4/5) | Preámbulo: 8 | Potencia: 5 dBm (ideal para mesa)
#define LORA_P2P_CONFIG "903900000:7:0:1:8:5"

HardwareSerial LoRaSerial(2);

// Convierte texto legible ("Hola") a cadena HEX ("486F6C61")
String stringToHex(const String& input) {
  String hexStr = "";
  for (unsigned int i = 0; i < input.length(); i++) {
    char buf[3];
    sprintf(buf, "%02X", (unsigned char)input[i]);
    hexStr += buf;
  }
  return hexStr;
}

// Convierte cadena HEX ("486F6C61") a texto legible ("Hola")
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

// Enviar comando AT esperando confirmación OK
bool enviarComandoAT(const String& cmd, uint32_t timeoutMs = 1500) {
  while (LoRaSerial.available()) LoRaSerial.read(); // Limpiar buffer
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

// Pone al RAK811 en modo Escucha permanente (Receiver Mode = 1)
void activarModoRecepcion() {
  LoRaSerial.print("at+set_config=lorap2p:transfer_mode:1\r\n");
  delay(100);
  while (LoRaSerial.available()) LoRaSerial.read();
}

// Transmite un mensaje por LoRa P2P y vuelve a modo Escucha
void enviarMensajeLoRa(String mensaje) {
  mensaje.trim();
  if (mensaje.length() == 0) return;

  Serial.println();
  Serial.printf(">> [TRANSMITIENDO] \"%s\"\n", mensaje.c_str());

  // 1. Cambiar a modo Emisor (Sender Mode = 2)
  LoRaSerial.print("at+set_config=lorap2p:transfer_mode:2\r\n");
  delay(100);
  while (LoRaSerial.available()) LoRaSerial.read();

  // 2. Convertir texto a HEX y transmitir por radio
  String payloadHex = stringToHex(mensaje);
  LoRaSerial.printf("at+send=lorap2p:%s\r\n", payloadHex.c_str());

  // 3. Esperar 500 ms a que la radio termine de emitir todo el paquete
  delay(500);
  while (LoRaSerial.available()) LoRaSerial.read();

  // 4. Volver inmediatamente a modo Escucha (Receiver Mode = 1)
  activarModoRecepcion();

  Serial.println(">> [ENVIADO] Paquete emitido al aire. Escuchando respuestas...");
}

// Procesa una trama recibida tipo: at+recv=<RSSI>,<SNR>,<Len>:<HEX>
void procesarPaqueteRecibido(String raw) {
  int dosPuntos = raw.indexOf(':');
  if (dosPuntos == -1) {
    Serial.printf("[INFO RAK811]: %s\n", raw.c_str());
    return;
  }

  // Extraer metadatos (RSSI, SNR, Len)
  String meta = raw.substring(8, dosPuntos);
  String hexData = raw.substring(dosPuntos + 1);
  hexData.trim();

  int coma1 = meta.indexOf(',');
  int coma2 = meta.indexOf(',', coma1 + 1);
  String rssi = (coma1 != -1) ? meta.substring(0, coma1) : "?";
  String snr  = (coma1 != -1 && coma2 != -1) ? meta.substring(coma1 + 1, coma2) : "?";
  String len  = (coma2 != -1) ? meta.substring(coma2 + 1) : "?";

  // Convertir contenido HEX a texto
  String texto = hexToString(hexData);

  Serial.println();
  Serial.println("**************************************************");
  Serial.println("       >>> [MENSAJE RECIBIDO POR LORA] <<<        ");
  Serial.println("**************************************************");
  Serial.printf("  Texto Recibido : %s\n", texto.c_str());
  Serial.printf("  Intensidad RSSI: %s dBm\n", rssi.c_str());
  Serial.printf("  Calidad SNR    : %s dB\n", snr.c_str());
  Serial.printf("  Tamaño         : %s bytes\n", len.c_str());
  Serial.printf("  Hexadecimal    : %s\n", hexData.c_str());
  Serial.println("**************************************************\n");
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 2000);

  Serial.println("\n==================================================");
  Serial.printf("   SISTEMA LORA P2P BIDIRECCIONAL - [%s]\n", NOMBRE_NODO);
  Serial.println("==================================================");

  LoRaSerial.begin(RAK_BAUD, SERIAL_8N1, RAK_RX_PIN, RAK_TX_PIN);
  delay(500);

  // 1. Asegurar modo P2P (work_mode:1)
  Serial.print("[CONFIG] Fijando modo LoRa P2P... ");
  if (enviarComandoAT("at+set_config=lora:work_mode:1")) {
    Serial.println("OK");
  } else {
    Serial.println("ERROR");
  }

  // 2. Configurar frecuencias y parámetros RF
  Serial.print("[CONFIG] Aplicando frecuencia (903.9 MHz) y SF7... ");
  String cmdParams = "at+set_config=lorap2p:" + String(LORA_P2P_CONFIG);
  if (enviarComandoAT(cmdParams)) {
    Serial.println("OK");
  } else {
    Serial.println("ERROR");
  }

  // 3. Activar modo receptor por defecto
  Serial.print("[CONFIG] Activando receptor permanente... ");
  activarModoRecepcion();
  Serial.println("LISTO");

  Serial.println("\n--------------------------------------------------");
  Serial.println(" ¡DISPOSITIVO LISTO Y ESCUCHANDO POR RADIO!       ");
  Serial.println(" Escribe cualquier texto aqui abajo y presiona    ");
  Serial.println(" [Enter] para enviarlo al otro ESP32.             ");
  Serial.println("--------------------------------------------------\n");
}

void loop() {
  // 1. RECEPCIÓN: Revisar si el RAK811 nos envió datos recibidos por radio
  if (LoRaSerial.available()) {
    String linea = LoRaSerial.readStringUntil('\n');
    linea.trim();
    if (linea.length() > 0) {
      if (linea.startsWith("at+recv=")) {
        procesarPaqueteRecibido(linea);
      } else if (linea != "OK") {
        // Mensajes de estado del módem
        Serial.printf("[MODEM]: %s\n", linea.c_str());
      }
    }
  }

  // 2. TRANSMISIÓN: Revisar si escribiste algo en la PC para enviarlo
  if (Serial.available()) {
    String entrada = Serial.readStringUntil('\n');
    entrada.trim();
    if (entrada.length() > 0) {
      // Si el usuario escribe un comando AT directo (ej: at+version), lo pasa directo
      if (entrada.startsWith("at+") || entrada.startsWith("AT+")) {
        LoRaSerial.printf("%s\r\n", entrada.c_str());
      } else {
        // Si escribe un texto normal, lo enviamos por LoRa P2P
        enviarMensajeLoRa(entrada);
      }
    }
  }
}
