from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("zenix.voice")


def _play_wave_on_output_device(path: str, device_index: Optional[int] = None) -> None:
    """Reproduce un WAV en el dispositivo de salida seleccionado."""
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
            device=device_index,
        ) as stream:
            stream.write(frames)
            stream.stop()
    except Exception as exc:
        log.warning("[VOICE] No se pudo reproducir WAV en dispositivo (%s): %s", device_index, exc)


class VoiceProvider(ABC):
    """Interfaz abstracta para integraciones de TTS futuras."""

    @abstractmethod
    def initialize(self, voice_name: Optional[str], rate: int, volume: float) -> None:
        raise NotImplementedError()

    @abstractmethod
    def get_available_voices(self) -> List[Dict[str, str]]:
        raise NotImplementedError()

    @abstractmethod
    def speak(self, text: str, voice_name: Optional[str] = None, output_device_index: Optional[int] = None) -> None:
        raise NotImplementedError()


class WindowsVoiceProvider(VoiceProvider):
    """Proveedor de voz para Windows usando pyttsx3."""

    def __init__(self) -> None:
        self._engine = None
        self._selected_voice_id: Optional[str] = None
        self._voice_name: Optional[str] = None
        self._rate: int = 0
        self._volume: float = 1.0
        self._initialized: bool = False

    def initialize(self, voice_name: Optional[str], rate: int, volume: float) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()

            if self._initialized and self._voice_name == voice_name and self._rate == rate and self._volume == volume:
                log.info("[VOICE] TTS ya estaba inicializado con la misma configuración.")
                return

            if voice_name:
                self._selected_voice_id = self._find_voice_id(voice_name, engine)
            else:
                self._selected_voice_id = self._select_spanish_voice(engine)

            if self._selected_voice_id:
                log.info("[VOICE] Voz inicializada: %s", self._selected_voice_id)
            else:
                log.warning("[VOICE] No se encontró una voz válida, usando configuración por defecto.")

            try:
                engine.stop()
            except Exception:
                pass
            self._engine = None
            self._voice_name = voice_name
            self._rate = rate
            self._volume = volume
            self._initialized = True

        except Exception as exc:
            log.error("[VOICE] Error inicializando proveedor de voz Windows: %s", exc, exc_info=True)
            self._engine = None
            self._selected_voice_id = None
            self._initialized = False
            self._voice_name = None

    def get_available_voices(self) -> List[Dict[str, str]]:
        voices_list: List[Dict[str, str]] = []
        try:
            import pyttsx3
            engine = pyttsx3.init()
            for voice in engine.getProperty("voices"):
                voices_list.append({"id": voice.id, "name": voice.name or voice.id})
            engine.stop()
        except Exception as exc:
            log.error("[VOICE] No se pudieron listar voces de Windows: %s", exc, exc_info=True)
        return voices_list

    def speak(self, text: str, voice_name: Optional[str] = None, output_device_index: Optional[int] = None) -> None:
        if not text.strip():
            return

        engine = None
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self._rate or 170)
            engine.setProperty("volume", self._volume)

            if voice_name:
                voice_id = self._find_voice_id(voice_name, engine)
                if voice_id:
                    engine.setProperty("voice", voice_id)
            elif self._selected_voice_id:
                engine.setProperty("voice", self._selected_voice_id)

            if output_device_index is not None:
                import tempfile
                import os
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
                        temp_path = temp_file.name
                    engine.save_to_file(text, temp_path)
                    engine.runAndWait()
                    _play_wave_on_output_device(temp_path, output_device_index)
                finally:
                    if temp_path and os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
            else:
                engine.say(text)
                engine.runAndWait()
        except Exception as exc:
            log.error("[VOICE] Error al reproducir texto: %s", exc, exc_info=True)
        finally:
            if engine is not None:
                try:
                    engine.stop()
                except Exception:
                    pass

    def _find_voice_id(self, target_voice: str, engine=None) -> Optional[str]:
        try:
            active_engine = engine or self._engine
            voices = active_engine.getProperty("voices") if active_engine else []
            target = target_voice.lower()
            for voice in voices:
                if target in (voice.name or "").lower() or target in (voice.id or "").lower():
                    return voice.id
        except Exception:
            pass
        return None

    def _select_spanish_voice(self, engine=None) -> Optional[str]:
        active_engine = engine or self._engine
        if active_engine is None:
            return None
        voices = active_engine.getProperty("voices")
        priority_names = ["sabina", "helena", "laura"]
        for voice in voices:
            name = (voice.name or "").lower()
            if any(priority in name for priority in priority_names):
                return voice.id
        for voice in voices:
            name = (voice.name or "").lower()
            if "es-es" in name:
                return voice.id
        for voice in voices:
            name = (voice.name or "").lower()
            if "es-mx" in name:
                return voice.id
        for voice in voices:
            if "spanish" in (voice.name or "").lower():
                return voice.id
        return voices[0].id if voices else None


class FutureAIVoiceProvider(VoiceProvider):
    """Proveedor de voz futuro para integrar TTS basado en IA."""

    def initialize(self, voice_name: Optional[str], rate: int, volume: float) -> None:
        log.info("[VOICE] FutureAIVoiceProvider inicializado (stub). No hay motor configurado aún.")

    def get_available_voices(self) -> List[Dict[str, str]]:
        log.info("[VOICE] FutureAIVoiceProvider no implementa voces todavía.")
        return []

    def speak(self, text: str, voice_name: Optional[str] = None, output_device_index: Optional[int] = None) -> None:
        log.warning("[VOICE] FutureAIVoiceProvider no puede reproducir audio todavía.")


class PiperProvider(VoiceProvider):
    """Stub para futuros proveedores Piper."""

    def initialize(self, voice_name: Optional[str], rate: int, volume: float) -> None:
        log.warning("[VOICE] PiperProvider no implementado todavía.")

    def get_available_voices(self) -> List[Dict[str, str]]:
        return []

    def speak(self, text: str, voice_name: Optional[str] = None, output_device_index: Optional[int] = None) -> None:
        log.warning("[VOICE] PiperProvider no puede reproducir audio todavía.")


class XTTSProvider(VoiceProvider):
    """Stub para futuros proveedores XTTS."""

    def initialize(self, voice_name: Optional[str], rate: int, volume: float) -> None:
        log.warning("[VOICE] XTTSProvider no implementado todavía.")

    def get_available_voices(self) -> List[Dict[str, str]]:
        return []

    def speak(self, text: str, voice_name: Optional[str] = None, output_device_index: Optional[int] = None) -> None:
        log.warning("[VOICE] XTTSProvider no puede reproducir audio todavía.")


class KokoroProvider(VoiceProvider):
    """Stub para futuros proveedores Kokoro."""

    def initialize(self, voice_name: Optional[str], rate: int, volume: float) -> None:
        log.warning("[VOICE] KokoroProvider no implementado todavía.")

    def get_available_voices(self) -> List[Dict[str, str]]:
        return []

    def speak(self, text: str, voice_name: Optional[str] = None, output_device_index: Optional[int] = None) -> None:
        log.warning("[VOICE] KokoroProvider no puede reproducir audio todavía.")
