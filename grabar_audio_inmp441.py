"""
=============================================================================
PROYECTO: GRABADOR Y EVALUADOR DE CALIDAD PARA MICRÓFONO INMP441 (ESP32)
ARCHIVO : grabar_audio_inmp441.py
=============================================================================
DESCRIPCIÓN:
Este script se conecta por el puerto Serial (USB) a tu ESP32 con el sketch
'prueba_inmp441.ino', solicita una grabación de 5 segundos, la guarda
en un archivo '.wav' estándar, calcula métricas de calidad acústica (SNR,
ruido base, saturación) y reproduce el audio inmediatamente en tu PC.
=============================================================================
"""

import os
import sys
import time
import math
import wave
import struct
import serial
import serial.tools.list_ports

BAUD_RATE = 115200
NOMBRE_ARCHIVO_SALIDA = "grabacion_inmp441.wav"
BYTES_TOTALES_ESPERADOS = 160044  # 44 bytes de cabecera WAV + (16000 muestras/s * 2 bytes * 5 s)


def listar_y_seleccionar_puerto():
    """Detecta los puertos COM disponibles y permite seleccionar el del ESP32."""
    if len(sys.argv) > 1 and sys.argv[1].upper().startswith("COM"):
        puerto_arg = sys.argv[1].upper()
        print(f">> Puerto especificado por argumento: {puerto_arg}")
        return puerto_arg

    puertos = list(serial.tools.list_ports.comports())
    if not puertos:
        print("[ERROR] No se detectó ningún puerto COM conectado.")
        print("Asegúrate de conectar el ESP32 por cable USB de datos.")
        sys.exit(1)

    print("\nPuertos COM detectados:")
    for i, p in enumerate(puertos):
        print(f"  [{i + 1}] {p.device} - {p.description}")

    if len(puertos) == 1:
        puerto_sel = puertos[0].device
        print(f">> Seleccionado automáticamente: {puerto_sel}")
        return puerto_sel

    while True:
        try:
            opcion = input(f"\nSelecciona el número del puerto (1-{len(puertos)}): ").strip()
            idx = int(opcion) - 1
            if 0 <= idx < len(puertos):
                return puertos[idx].device
            print("Número inválido.")
        except ValueError:
            print("Por favor, ingresa un número válido.")


def analizar_calidad_audio(ruta_wav):
    """Analiza la señal de audio capturada y genera un diagnóstico de calidad acústica."""
    with wave.open(ruta_wav, "rb") as wf:
        n_canales = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        data_raw = wf.readframes(n_frames)

    # Extraer únicamente los frames completos recibidos
    num_muestras = len(data_raw) // sampwidth
    if num_muestras == 0:
        print("[AVISO] El archivo de audio está vacío.")
        return

    muestras = struct.unpack(f"<{num_muestras}h", data_raw[:num_muestras * sampwidth])

    # Cálculos estadísticos
    muestras_abs = [abs(m) for m in muestras]
    pico_max = max(muestras_abs)
    suma_cuad = sum(m * m for m in muestras)
    rms = math.sqrt(suma_cuad / len(muestras))

    # Cálculo en escala logarítmica dBFS (0 dBFS = saturación máxima a 32767)
    db_pico = 20 * math.log10((pico_max + 1) / 32768.0)
    db_rms = 20 * math.log10((rms + 1) / 32768.0)

    # Detección de silencios y ruido base (primeros 500 ms)
    muestras_ruido_base = muestras_abs[: int(framerate * 0.5)]
    ruido_rms = math.sqrt(sum(m * m for m in muestras_ruido_base) / max(1, len(muestras_ruido_base)))
    db_ruido = 20 * math.log10((ruido_rms + 1) / 32768.0)
    snr_estimado = db_rms - db_ruido

    # Conteo de muestras saturadas (clipping al límite de 16 bits)
    saturaciones = sum(1 for m in muestras_abs if m >= 32760)

    print("\n" + "=" * 60)
    print("        INFORME DE CALIDAD ACÚSTICA - INMP441")
    print("=" * 60)
    print(f" * Duración grabada      : {n_frames / framerate:.1f} segundos")
    print(f" * Frecuencia de muestreo: {framerate} Hz (Mono 16-bit PCM)")
    print(f" * Nivel Pico Máximo     : {pico_max} / 32767 ({db_pico:.1f} dBFS)")
    print(f" * Nivel RMS (Promedio)  : {rms:.0f} ({db_rms:.1f} dBFS)")
    print(f" * Ruido de Fondo        : {ruido_rms:.0f} ({db_ruido:.1f} dBFS)")
    print(f" * Relación Señal/Ruido  : ~{snr_estimado:.1f} dB")
    print(f" * Muestras Saturadas    : {saturaciones}")
    print("-" * 60)

    # Diagnóstico del estado del micrófono
    if pico_max == 0:
        print(" [DIAGNÓSTICO] -> FALLA TOTAL: Todas las muestras son 0.")
        print("  Causa: Pin L/R flotante (debe ir a GND) o cable SD desconectado.")
    elif saturaciones > 200:
        print(" [DIAGNÓSTICO] -> SATURACIÓN: El micrófono está demasiado cerca")
        print("  o se habló con volumen excesivo. Aléjate unos 15-20 cm.")
    elif pico_max < 1500:
        print(" [DIAGNÓSTICO] -> SEÑAL MUY BAJA: Apenas se percibe sonido.")
        print("  Habla más fuerte o acerca el micrófono a 10-15 cm.")
    elif snr_estimado > 12:
        print(" [DIAGNÓSTICO] -> ¡CALIDAD EXCELENTE! Claridad óptima para")
        print("  reconocimiento de voz, TinyML y proyectos de audio.")
    else:
        print(" [DIAGNÓSTICO] -> CALIDAD BUENA: Señal detectable con algo de ruido ambiental.")
    print("=" * 60 + "\n")


def capturar_audio(puerto_com):
    """Envía el comando de grabación al ESP32 y descarga el archivo WAV."""
    print(f"\n[CONEXIÓN] Abriendo {puerto_com} a {BAUD_RATE} baud...")
    
    try:
        ser = serial.Serial(puerto_com, BAUD_RATE, timeout=3.0)
    except Exception as e:
        print(f"[ERROR] No se pudo abrir {puerto_com}: {e}")
        print("Verifica si el Monitor Serial de Arduino IDE está abierto y ciérralo.")
        return False

    time.sleep(2.0)  # Esperar estabilización del ESP32 tras reset DTR/RTS
    ser.reset_input_buffer()

    print("[ESP32] Solicitando grabación de 5 segundos (enviando 'G')...")
    ser.write(b"G\n")
    ser.flush()

    # Esperar el marcador de inicio "===START_WAV===" (el ESP32 graba 5s en RAM primero)
    tiempo_inicio = time.time()
    marcador_encontrado = False

    while time.time() - tiempo_inicio < 12.0:
        linea = ser.readline().decode(errors="ignore").strip()
        if linea:
            print(f"  ESP32 > {linea}")
        if "===START_WAV===" in linea:
            marcador_encontrado = True
            break

    if not marcador_encontrado:
        print("[ERROR] El ESP32 no respondió con el marcador de audio.")
        ser.close()
        return False

    print("\n>> ¡GRABANDO! Habla hacia el micrófono INMP441 ahora...")

    # Leer los bytes del archivo WAV con tiempo suficiente (160 KB a 115200 toma ~14 s)
    bytes_recibidos = bytearray()
    tiempo_ultimo_byte = time.time()

    while len(bytes_recibidos) < BYTES_TOTALES_ESPERADOS:
        faltantes = BYTES_TOTALES_ESPERADOS - len(bytes_recibidos)
        bloque = ser.read(min(faltantes, 4096))
        if bloque:
            bytes_recibidos.extend(bloque)
            tiempo_ultimo_byte = time.time()
            porcentaje = (len(bytes_recibidos) / BYTES_TOTALES_ESPERADOS) * 100.0
            print(f"\rRecibiendo audio: {len(bytes_recibidos)} / {BYTES_TOTALES_ESPERADOS} bytes [{porcentaje:.0f}%]", end="")
        else:
            # Si pasan más de 3 segundos sin recibir ningún byte nuevo, terminar
            if time.time() - tiempo_ultimo_byte > 3.0:
                print("\n[INFO] Fin de transmisión detectado.")
                break

    print("\n[OK] Transmisión completada.")
    ser.close()

    if len(bytes_recibidos) <= 44:
        print("[ERROR] No se recibieron suficientes datos de audio.")
        return False

    # Guardar como archivo WAV estándar usando el módulo wave
    # para garantizar cabeceras 100% íntegras y reproducibles
    ruta_completa = os.path.abspath(NOMBRE_ARCHIVO_SALIDA)
    audio_pcm = bytes_recibidos[44:] if len(bytes_recibidos) > 44 else bytes_recibidos

    with wave.open(ruta_completa, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(audio_pcm)

    print(f"[GUARDADO] Audio grabado guardado en: {ruta_completa}")

    # Analizar acústicamente el archivo
    analizar_calidad_audio(ruta_completa)

    # Reproducción automática en Windows
    try:
        print("[REPRODUCCIÓN] Abriendo reproductor para que escuches tu grabación...")
        os.startfile(ruta_completa)
    except Exception as e:
        print(f"[INFO] Puedes abrir '{NOMBRE_ARCHIVO_SALIDA}' con tu reproductor favorito.")

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("  UTILIDAD DE PRUEBA Y EVALUACIÓN DE AUDIO - INMP441 / ESP32")
    print("=" * 60)
    puerto = listar_y_seleccionar_puerto()
    capturar_audio(puerto)
