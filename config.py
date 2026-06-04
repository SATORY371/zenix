"""
╔══════════════════════════════════════════════════════════════════╗
║         ZENIX v2.0 — Configuración Global (CORREGIDO)           ║
║   Timeouts inteligentes, endpoints válidos, voces españolas      ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompts" / "system_prompt.txt"
USER_SETTINGS_PATH = BASE_DIR / "user_settings.json"


class Config:
    """Configuración centralizada con valores por defecto seguros."""

    # ═══════════════════════════════════════════════════════════════════
    # OLLAMA — Configuración de conexión y timeouts
    # ═══════════════════════════════════════════════════════════════════
    
    # URL base de Ollama (endpoint /api/chat)
    OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://127.0.0.1:11434/api/chat")
    
    # IMPORTANTE: Timeouts separados para conexión y lectura
    # - Conexión: 30 segundos (tiempo para establecer TCP)
    # - Lectura: 300 segundos (tiempo para recibir respuesta completa)
    # Usar como: timeout=(30, 300)
    OLLAMA_TIMEOUT_CONNECT = int(os.getenv("ZENIX_OLLAMA_TIMEOUT_CONNECT", "30"))
    OLLAMA_TIMEOUT_READ = int(os.getenv("ZENIX_OLLAMA_TIMEOUT_READ", "60"))
    
    # Asegurar rangos válidos
    OLLAMA_TIMEOUT_CONNECT = max(5, min(OLLAMA_TIMEOUT_CONNECT, 60))   # 5-60s
    OLLAMA_TIMEOUT_READ = max(30, min(OLLAMA_TIMEOUT_READ, 600))       # 30-600s
    
    # Tupla de timeouts para requests.post(timeout=...)
    OLLAMA_TIMEOUT = (OLLAMA_TIMEOUT_CONNECT, OLLAMA_TIMEOUT_READ)
    
    # Timeout para precarga/warmup (más corto, no crítico)
    OLLAMA_WARMUP_TIMEOUT = int(os.getenv("ZENIX_OLLAMA_WARMUP_TIMEOUT", "15"))
    OLLAMA_WARMUP_TIMEOUT = max(5, min(OLLAMA_WARMUP_TIMEOUT, 30))
    
    # Timeout para diagnóstico de Ollama (/api/tags, /api/status)
    OLLAMA_HEALTH_TIMEOUT = int(os.getenv("ZENIX_OLLAMA_HEALTH_TIMEOUT", "10"))
    OLLAMA_HEALTH_TIMEOUT = max(3, min(OLLAMA_HEALTH_TIMEOUT, 30))
    
    # Modelo a usar
    MODEL = os.getenv("ZENIX_MODEL", "llama3.2:3b")
    
    # Archivo de prompt del sistema
    SYSTEM_PROMPT_FILE = os.getenv("SYSTEM_PROMPT_FILE", str(PROMPT_PATH))
    USER_SETTINGS_FILE = str(USER_SETTINGS_PATH)
    MEMORY_DIR = os.getenv("ZENIX_MEMORY_DIR", str(BASE_DIR / "memory"))

    # ═══════════════════════════════════════════════════════════════════
    # STREAMING — Configuración de streaming de respuestas
    # ═══════════════════════════════════════════════════════════════════
    
    # Usar streaming en respuestas solo si se habilita explícitamente.
    # Por defecto, las respuestas normales se reciben completas para evitar fragmentación.
    USE_STREAMING = os.getenv("ZENIX_USE_STREAMING", "0").lower() in ("1", "true", "yes")
    
    # Tamaño mínimo de respuesta para usar streaming (bytes)
    STREAMING_MIN_LENGTH = int(os.getenv("ZENIX_STREAMING_MIN_LENGTH", "500"))

    # ═══════════════════════════════════════════════════════════════════
    # VOZ — Configuración de TTS y STT
    # ═══════════════════════════════════════════════════════════════════
    
    # Habilitar síntesis de voz
    USE_VOICE = os.getenv("ZENIX_USE_VOICE", "1").lower() in ("1", "true", "yes")
    
    # Velocidad de habla (palabras por minuto, típico 100-200)
    SPEECH_RATE = int(os.getenv("ZENIX_SPEECH_RATE", "180"))
    SPEECH_RATE = max(50, min(SPEECH_RATE, 300))
    
    # Volumen TTS (0.0 a 1.0)
    SPEECH_VOLUME = float(os.getenv("ZENIX_SPEECH_VOLUME", "1.0"))
    SPEECH_VOLUME = max(0.0, min(SPEECH_VOLUME, 1.0))
    
    # Voz TTS preferida (ahora con prioridad a voces españolas)
    # Valores válidos: nombre de voz del sistema
    # El sistema intentará: Sabina, Helena, Laura, es-ES, es-MX, Spanish, fallback inglés
    TTS_VOICE = os.getenv("ZENIX_TTS_VOICE", "")  # Vacío = auto-detect español
    
    # Idioma para reconocimiento de voz (Google STT)
    ASR_LANGUAGE = os.getenv("ZENIX_ASR_LANGUAGE", "es-ES")

    # ═══════════════════════════════════════════════════════════════════
    # BASE DE DATOS — MySQL para tareas pendientes
    # ═══════════════════════════════════════════════════════════════════
    
    MYSQL_HOST = os.getenv("ZENIX_DB_HOST", "127.0.0.1")
    MYSQL_PORT = int(os.getenv("ZENIX_DB_PORT", "3306"))
    MYSQL_USER = os.getenv("ZENIX_DB_USER", "root")
    MYSQL_PASSWORD = os.getenv("ZENIX_DB_PASSWORD", "vega")
    MYSQL_DATABASE = os.getenv("ZENIX_DB_NAME", "zenix_os")

    # ═══════════════════════════════════════════════════════════════════
    # RED — Configuración de WiFi
    # ═══════════════════════════════════════════════════════════════════
    
    WIFI_INTERFACE = os.getenv("ZENIX_WIFI_INTERFACE", "Wi-Fi")

    # ═══════════════════════════════════════════════════════════════════
    # LOGGING — Configuración de diagnóstico
    # ═══════════════════════════════════════════════════════════════════
    
    DEBUG = os.getenv("ZENIX_DEBUG", "1").lower() in ("1", "true", "yes")
    LOG_LEVEL = os.getenv("ZENIX_LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("ZENIX_LOG_FILE", str(BASE_DIR / "zenix.log"))


def get_system_prompt_path():
    """Devuelve la ruta al archivo de prompt del sistema."""
    return Path(Config.SYSTEM_PROMPT_FILE)


def get_ollama_base_url():
    """Devuelve la URL base de Ollama (sin /api/chat)."""
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(Config.OLLAMA_API_URL)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
