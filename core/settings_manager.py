"""
╔══════════════════════════════════════════════════════════════════╗
║   ZENIX v2.0 — Módulo de Configuración Persistente del Usuario   ║
║   Gestiona lectura/escritura de user_settings.json               ║
╚══════════════════════════════════════════════════════════════════╝
"""

import json
import logging
from pathlib import Path
from typing import Any

from config import Config

log = logging.getLogger("zenix.settings")

# ── Valores por defecto ─────────────────────────────────────────────
DEFAULTS: dict[str, Any] = {
    "audio": {
        "mic_device_index":    None,   # None = dispositivo por defecto del sistema
        "mic_device_name":     "",
        "output_device_index": None,
        "output_device_name":  "",
        "stt_engine":          "google",   # "google" | "sphinx"
        "tts_voice":           "",       # Vacío = auto-selección de voz española
    }
}


class SettingsManager:
    """Administra la configuración persistente del usuario en JSON."""

    def __init__(self):
        self._path = Path(Config.USER_SETTINGS_FILE)
        self._data: dict[str, Any] = {}
        self._load()

    # ── Carga / guardado ──────────────────────────────────────────────

    def _load(self) -> None:
        """Lee el archivo JSON. Si no existe o está corrupto, usa defaults."""
        if self._path.exists():
            try:
                raw = self._path.read_text(encoding="utf-8")
                self._data = json.loads(raw)
                # Fusionar con defaults para asegurar claves nuevas
                self._merge_defaults()
                log.info("Configuración de usuario cargada desde %s", self._path)
            except (json.JSONDecodeError, OSError) as exc:
                
                log.warning("No se pudo leer '%s': %s — usando defaults.", self._path, exc)
                self._data = json.loads(json.dumps(DEFAULTS))  # deep copy
        else:
            self._data = json.loads(json.dumps(DEFAULTS))  # deep copy
            log.info("No existe user_settings.json — se usarán valores por defecto.")

    def _merge_defaults(self) -> None:
        """Asegura que todas las claves de DEFAULTS existan en self._data."""
        for section, values in DEFAULTS.items():
            if section not in self._data:
                self._data[section] = {}
            for key, default_val in values.items():
                self._data[section].setdefault(key, default_val)

    def save(self) -> None:
        """Escribe la configuración actual en el archivo JSON."""
        try:
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            log.info("Configuración guardada en %s", self._path)
        except OSError as exc:
            log.error("No se pudo guardar la configuración: %s", exc)

    # ── Acceso a secciones ────────────────────────────────────────────

    def get_audio(self) -> dict[str, Any]:
        """Devuelve la sección de configuración de audio (copia)."""
        return dict(self._data.get("audio", DEFAULTS["audio"]))

    def set_audio(self, key: str, value: Any) -> None:
        """Actualiza un valor de audio y guarda en disco."""
        self._data.setdefault("audio", {})
        self._data["audio"][key] = value
        self.save()

    def update_audio(self, changes: dict[str, Any]) -> None:
        """Actualiza múltiples valores de audio y guarda en disco."""
        self._data.setdefault("audio", {})
        self._data["audio"].update(changes)
        self.save()

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Acceso genérico a cualquier sección/clave."""
        return self._data.get(section, {}).get(key, default)

    def reset_audio_to_defaults(self) -> None:
        """Restaura la sección de audio a los valores por defecto."""
        import copy
        self._data["audio"] = copy.deepcopy(DEFAULTS["audio"])
        self.save()


# ── Instancia global (singleton ligero) ──────────────────────────────
_manager: SettingsManager | None = None


def get_settings() -> SettingsManager:
    """Devuelve la instancia global de SettingsManager (lazy singleton)."""
    global _manager
    if _manager is None:
        _manager = SettingsManager()
    return _manager
