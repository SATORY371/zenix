"""
╔══════════════════════════════════════════════════════════════════╗
║   ZENIX v2.0 — Módulo de Voz (TTS + STT)                        ║
║   Mantiene compatibilidad total con la API original              ║
║   Añade: selección de dispositivo, nivel de mic, VAD, Google STT ║
╚══════════════════════════════════════════════════════════════════╝
"""

import io
import logging
import math
import struct
import threading
import time
from typing import Any, Callable, Optional

from config import Config
from core.voice_provider import VoiceProvider, WindowsVoiceProvider

log = logging.getLogger("zenix.speech")

# ── Estado global del módulo ──────────────────────────────────────────
_tts_lock = threading.Lock()           # pyttsx3 no es thread-safe a nivel de motor
_tts_ready = threading.Event()          # Señaliza cuando TTS está listo para hablar
_tts_failed = False                     # Marca si la inicialización de TTS falló
_speaking = threading.Event()           # Activo mientras Zenix habla (anti-eco)
_output_device_index: Optional[int] = None
_voice_provider: VoiceProvider = WindowsVoiceProvider()

# Hilo y control para medición de nivel de micrófono
_level_thread: Optional[threading.Thread] = None
_level_stop = threading.Event()

recognizer: Optional[object] = None
sr: Optional[Any] = None


def _import_speech_recognition():
    global sr
    if sr is None:
        import speech_recognition as _sr
        sr = _sr
    return sr


def _get_recognizer():
    global recognizer
    if recognizer is None:
        sr_module = _import_speech_recognition()
        recognizer = sr_module.Recognizer()
    return recognizer


# ══════════════════════════════════════════════════════════════════════
# Detección de dispositivos
# ══════════════════════════════════════════════════════════════════════

def get_input_devices() -> list[dict]:
    """
    Devuelve lista de micrófonos disponibles en el sistema.
    Cada elemento: {"index": int, "name": str, "channels": int}
    """
    devices = []
    try:
        import sounddevice as sd
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append({
                    "index":    idx,
                    "name":     dev["name"],
                    "channels": dev["max_input_channels"],
                })
    except Exception as exc:
        log.error("No se pudieron listar dispositivos de entrada: %s", exc)
        # Fallback: listar con PyAudio
        devices = _list_pyaudio_inputs()
    return devices


def get_output_devices() -> list[dict]:
    """
    Devuelve lista de altavoces/auriculares disponibles.
    Cada elemento: {"index": int, "name": str, "channels": int}
    """
    devices = []
    try:
        import sounddevice as sd
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_output_channels"] > 0:
                devices.append({
                    "index":    idx,
                    "name":     dev["name"],
                    "channels": dev["max_output_channels"],
                })
    except Exception as exc:
        log.error("No se pudieron listar dispositivos de salida: %s", exc)
        devices = _list_pyaudio_outputs()
    return devices


def _list_pyaudio_inputs() -> list[dict]:
    """Fallback: lista micrófonos usando PyAudio."""
    devices = []
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                devices.append({
                    "index":    i,
                    "name":     info["name"],
                    "channels": int(info["maxInputChannels"]),
                })
        p.terminate()
    except Exception as exc:
        log.error("PyAudio input fallback falló: %s", exc)
    return devices


def _list_pyaudio_outputs() -> list[dict]:
    """Fallback: lista altavoces usando PyAudio."""
    devices = []
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxOutputChannels"] > 0:
                devices.append({
                    "index":    i,
                    "name":     info["name"],
                    "channels": int(info["maxOutputChannels"]),
                })
        p.terminate()
    except Exception as exc:
        log.error("PyAudio output fallback falló: %s", exc)
    return devices


def get_default_input_index() -> Optional[int]:
    """Devuelve el índice del dispositivo de entrada por defecto del sistema."""
    try:
        import sounddevice as sd
        return sd.default.device[0]
    except Exception:
        return None


def get_default_output_index() -> Optional[int]:
    """Devuelve el índice del dispositivo de salida por defecto del sistema."""
    try:
        import sounddevice as sd
        return sd.default.device[1]
    except Exception:
        return None

def set_output_device(device_index: Optional[int] = None) -> None:
    """Guarda el índice del dispositivo de salida que debe usarse para TTS."""
    global _output_device_index
    _output_device_index = device_index
    log.info("Dispositivo de salida configurado: %s", device_index)


def check_input_device(device_index: Optional[int] = None) -> bool:
    """Verifica que el dispositivo de entrada exista y pueda abrirse."""
    try:
        sr_module = _import_speech_recognition()
        mic_kwargs = {"device_index": device_index} if device_index is not None else {}
        with sr_module.Microphone(**mic_kwargs) as source:
            return True
    except Exception as exc:
        log.warning("Verificación de micrófono falló: %s", exc)
        return False


def check_output_device(device_index: Optional[int] = None) -> bool:
    """Verifica que el dispositivo de salida exista y pueda inicializarse."""
    try:
        import sounddevice as sd
        with sd.RawOutputStream(channels=1, samplerate=16000,
                                dtype="int16", device=device_index):
            return True
    except Exception as exc:
        log.warning("Verificación de salida falló: %s", exc)
        return False


def _play_wave_on_output_device(path: str) -> None:
    """Lee un WAV y lo reproduce a través del dispositivo de salida seleccionado."""
    try:
        import sounddevice as sd
        import wave
        with wave.open(path, "rb") as wf:
            samplerate = wf.getframerate()
            channels = wf.getnchannels()
            frames = wf.readframes(wf.getnframes())

        with sd.RawOutputStream(
            samplerate=samplerate,
            channels=channels,
            dtype="int16",
            device=_output_device_index,
        ) as stream:
            stream.write(frames)
            stream.stop()
    except Exception as exc:
        log.warning("No se pudo reproducir en dispositivo específico (%s): %s", _output_device_index, exc)
        raise

# ══════════════════════════════════════════════════════════════════════
# Inicialización TTS (API original preservada)
# ══════════════════════════════════════════════════════════════════════

def init_speech(voice_name: Optional[str] = None,
                rate: Optional[int] = None,
                volume: Optional[float] = None) -> None:
    """
    Inicializa el motor de síntesis de voz.

    Esta función es idempotente, thread-safe y protege contra inicializaciones
    simultáneas. Si ya hay un motor activo con la misma configuración, no lo
    reinicia.
    """
    global _tts_failed
    with _tts_lock:
        start_time = time.time()
        requested_voice = voice_name or Config.TTS_VOICE
        chosen_rate = rate if rate is not None else Config.SPEECH_RATE
        chosen_volume = volume if volume is not None else Config.SPEECH_VOLUME

        try:
            _voice_provider.initialize(requested_voice, chosen_rate, chosen_volume)
            _tts_failed = False
            _tts_ready.set()
            actual_voice = getattr(_voice_provider, "_selected_voice_id", None)
            log.info("[TTS INIT] %.0fms", (time.time() - start_time) * 1000)
            log.info("[VOICE] VOZ SELECCIONADA: %s", actual_voice or requested_voice or "auto")
        except Exception as exc:
            _tts_failed = True
            _tts_ready.clear()
            log.error("[VOICE] Error inicializando TTS: %s", exc, exc_info=True)


def get_available_voices() -> list[dict]:
    """Devuelve las voces TTS disponibles en el sistema."""
    return _voice_provider.get_available_voices()




# ══════════════════════════════════════════════════════════════════════
# Síntesis de voz — speak() (API original preservada)
# ══════════════════════════════════════════════════════════════════════

def speak(text: str, voice_name: Optional[str] = None) -> None:
    """
    Reproduce el texto con TTS.

    Activa el flag `_speaking` durante la reproducción para el anti-eco.
    Si TTS no está disponible, se excluye silenciosamente sin bloquear la app.
    """
    text = text.strip()
    if not text:
        return

    if not is_tts_ready():
        if _tts_failed:
            log.warning("[VOICE] TTS ya falló. Omitiendo speak.")
            return

        log.debug("[VOICE] TTS aún no está listo, esperando hasta 2s...")
        if not _tts_ready.wait(2.0):
            log.warning("[VOICE] TTS no quedó listo tras 2s, omitiendo speak.")
            return

    log.debug("Zenix TTS: %s", text[:80])
    start_time = time.time()

    with _tts_lock:
        try:
            _speaking.set()
            _voice_provider.speak(
                text,
                voice_name=voice_name,
                output_device_index=_output_device_index,
            )
            log.info("[TTS SPEAK] %.0fms", (time.time() - start_time) * 1000)
        except Exception as exc:
            log.error("[VOICE] Error de TTS: %s", exc, exc_info=True)
        finally:
            _speaking.clear()
            log.info("[TTS STOP] OK")


def play_test_sound(text: str = "¡Hola! Soy Zenix, tu asistente fox girl. ¡Nya!") -> None:
    """Reproduce un texto de prueba para verificar la salida de audio."""
    threading.Thread(target=speak, args=(text,), daemon=True).start()


# ══════════════════════════════════════════════════════════════════════
# Reconocimiento de voz — listen_microphone() (API original preservada)
# ══════════════════════════════════════════════════════════════════════

def listen_microphone(device_index: Optional[int] = None,
                      engine: str = "google",
                      timeout: int = 6,
                      phrase_limit: int = 15) -> Optional[str]:
    """
    Captura voz del micrófono y la convierte a texto.

    Parámetros:
      device_index  — índice del micrófono (None = por defecto del sistema)
      engine        — "google" (online) | "sphinx" (offline)
      timeout       — segundos de espera antes de rendirse
      phrase_limit  — duración máxima de la frase en segundos

    Retorna el texto reconocido o None si falla.
    API original: listen_microphone() sigue funcionando sin argumentos.
    """
    if not Config.USE_VOICE:
        return None

    # Anti-eco: no escuchar mientras Zenix está hablando
    if _speaking.is_set():
        log.debug("Anti-eco: TTS activo, omitiendo captura.")
        return None

    try:
        sr_module = _import_speech_recognition()
        recognizer = _get_recognizer()
        mic_kwargs = {}
        if device_index is not None:
            mic_kwargs["device_index"] = device_index

        with sr_module.Microphone(**mic_kwargs) as source:
            log.info("Escuchando (motor=%s, dispositivo=%s)...", engine, device_index)
            recognizer.adjust_for_ambient_noise(source, duration=0.8)
            audio = recognizer.listen(source, timeout=timeout,
                                      phrase_time_limit=phrase_limit)

        return _transcribe(audio, engine)

    except sr.WaitTimeoutError:
        log.debug("Timeout de escucha: no se detectó voz.")
    except OSError as exc:
        log.error("Micrófono no disponible: %s", exc, exc_info=True)
    except Exception as exc:
        log.error("Error de reconocimiento de voz: %s", exc, exc_info=True)
    return None


def _transcribe(audio, engine: str) -> Optional[str]:
    """Convierte AudioData a texto usando el motor indicado."""
    sr_module = _import_speech_recognition()
    recognizer = _get_recognizer()
    if engine == "google":
        try:
            return recognizer.recognize_google(audio, language=Config.ASR_LANGUAGE)
        except sr_module.UnknownValueError:
            log.debug("Google STT: no se entendió la voz.")
        except sr_module.RequestError as exc:
            log.warning("Google STT sin conexión (%s), intentando Sphinx...", exc)
            return _transcribe_sphinx(audio)
    else:
        return _transcribe_sphinx(audio)
    return None


def _transcribe_sphinx(audio) -> Optional[str]:
    """STT offline con PocketSphinx como fallback."""
    sr_module = _import_speech_recognition()
    recognizer = _get_recognizer()
    try:
        return recognizer.recognize_sphinx(audio, language=Config.ASR_LANGUAGE)
    except (sr_module.UnknownValueError, sr_module.RequestError) as exc:
        log.debug("Sphinx STT falló: %s", exc)
    return None


# ══════════════════════════════════════════════════════════════════════
# Nivel de micrófono en tiempo real (para la barra de volumen)
# ══════════════════════════════════════════════════════════════════════

def start_microphone_level(callback: Callable[[float], None],
                           device_index: Optional[int] = None,
                           interval: float = 0.05) -> None:
    """
    Inicia un hilo que mide el nivel RMS del micrófono cada `interval` segundos
    y llama a `callback(nivel_0_a_1)` con el resultado normalizado (0.0–1.0).

    Parámetros:
      callback      — función que recibe float 0.0–1.0
      device_index  — índice del micrófono (None = por defecto)
      interval      — segundos entre muestras (default 0.05 = 20 fps)
    """
    global _level_thread
    _level_stop.clear()

    def _loop():
        try:
            import pyaudio
            CHUNK = 1024
            RATE  = 16000
            p = pyaudio.PyAudio()
            kwargs = {"input_device_index": device_index} if device_index is not None else {}
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
                **kwargs
            )
            log.info("Stream de nivel de micrófono iniciado (device=%s)", device_index)
            while not _level_stop.is_set():
                try:
                    data  = stream.read(CHUNK, exception_on_overflow=False)
                    rms   = _calc_rms(data)
                    level = min(rms / 3000.0, 1.0)  # normalizar: 3000 ≈ voz normal
                    callback(level)
                except Exception:
                    pass
                time.sleep(interval)
            stream.stop_stream()
            stream.close()
            p.terminate()
            log.info("Stream de nivel de micrófono detenido.")
        except Exception as exc:
            log.error("Error en stream de nivel de micrófono: %s", exc)

    _level_thread = threading.Thread(target=_loop, daemon=True)
    _level_thread.start()


def stop_microphone_level() -> None:
    """Detiene el hilo de medición de nivel de micrófono."""
    _level_stop.set()
    if _level_thread and _level_thread.is_alive():
        _level_thread.join(timeout=1.0)


def _calc_rms(data: bytes) -> float:
    """Calcula el valor RMS de un buffer PCM de 16 bits."""
    n = len(data) // 2
    if n == 0:
        return 0.0
    shorts = struct.unpack(f"{n}h", data)
    rms = math.sqrt(sum(s * s for s in shorts) / n)
    return rms


# ══════════════════════════════════════════════════════════════════════
# VAD simple — Voice Activity Detection basado en energía
# ══════════════════════════════════════════════════════════════════════

def listen_with_vad(device_index: Optional[int] = None,
                    engine: str = "google",
                    noise_threshold: int = 600,
                    silence_ms: int = 1200,
                    max_duration: int = 15) -> Optional[str]:
    """
    Escucha continuamente hasta detectar voz y el silencio posterior (VAD).

    Parámetros:
      device_index    — índice del micrófono
      engine          — motor STT
      noise_threshold — nivel RMS mínimo para considerar "hay voz"
      silence_ms      — milisegundos de silencio para terminar la frase
      max_duration    — duración máxima total en segundos

    Retorna el texto reconocido o None.
    Se aborta automáticamente si `_speaking` está activo (anti-eco).
    """
    if _speaking.is_set():
        return None

    RATE  = 16000
    CHUNK = int(RATE * 0.02)  # 20ms por chunk

    try:
        import pyaudio
        p = pyaudio.PyAudio()
        kwargs = {"input_device_index": device_index} if device_index is not None else {}
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
            **kwargs
        )

        frames: list[bytes] = []
        silence_chunks   = int(silence_ms / 20)
        max_chunks       = int(max_duration * 50)
        silent_count     = 0
        speech_detected  = False
        total_chunks     = 0

        log.info("VAD activo (threshold=%d, silence=%dms)", noise_threshold, silence_ms)

        while total_chunks < max_chunks:
            if _speaking.is_set():          # Anti-eco: Zenix habló
                log.debug("VAD: anti-eco activado, abortando.")
                frames = []
                break

            data = stream.read(CHUNK, exception_on_overflow=False)
            rms  = _calc_rms(data)

            if rms > noise_threshold:
                speech_detected = True
                silent_count = 0
                frames.append(data)
            elif speech_detected:
                frames.append(data)
                silent_count += 1
                if silent_count >= silence_chunks:
                    break              # Silencio suficiente: fin de frase
            # Si aún no detectó voz, sigue esperando

            total_chunks += 1

        stream.stop_stream()
        stream.close()
        p.terminate()

        if not speech_detected or not frames:
            return None

        # Convertir frames a AudioData de SpeechRecognition
        sr_module = _import_speech_recognition()
        raw_audio = b"".join(frames)
        audio_data = sr_module.AudioData(raw_audio, RATE, 2)  # sample_width=2 (paInt16)
        return _transcribe(audio_data, engine)

    except Exception as exc:
        log.error("Error en listen_with_vad: %s", exc)
    return None


# ══════════════════════════════════════════════════════════════════════
# Propiedad global anti-eco (consultable desde otros módulos)
# ══════════════════════════════════════════════════════════════════════

def is_speaking() -> bool:
    """Retorna True si Zenix está reproduciendo TTS en este momento."""
    return _speaking.is_set()


def is_tts_ready() -> bool:
    """Retorna True si el motor TTS ya fue inicializado correctamente."""
    try:
        return _tts_ready.is_set() and not _tts_failed
    except Exception:
        return False


def wait_for_tts_ready(timeout: float = 5.0) -> bool:
    """Espera hasta que TTS esté listo, con timeout y sin lanzar excepciones."""
    try:
        return _tts_ready.wait(timeout)
    except Exception as exc:
        log.warning("[VOICE] wait_for_tts_ready falló: %s", exc)
        return False
