"""
╔══════════════════════════════════════════════════════════════════╗
║         ZENIX v2.0 — Setup de Logging (NUEVO)                   ║
║   Configuración centralizada, UTF-8, manejo robusto de errores   ║
╚══════════════════════════════════════════════════════════════════╝
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from config import Config


def setup_logging():
    """
    Configura el sistema de logging centralizado para ZENIX.
    
    - Encoding UTF-8 para manejar caracteres españoles
    - Dos salidas: consola + archivo
    - Formato detallado con timestamp
    - Excepciones dentro de logging capturadas robustamente
    """
    
    # Crear directorio de logs si no existe
    log_dir = Path(Config.LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Definir formato de logging
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(name)-15s] %(levelname)-8s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Obtener logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, Config.LOG_LEVEL, logging.INFO))
    
    # Limpiar handlers anteriores si existen
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # ─── Handler de consola (stdout) ────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, Config.LOG_LEVEL, logging.INFO))
    console_handler.setFormatter(formatter)
    
    # Hacer robusto: capturar excepciones de logging
    console_handler.handleError = _safe_handle_error
    
    root_logger.addHandler(console_handler)
    
    # ─── Handler de archivo (UTF-8) ─────────────────────────────────
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            Config.LOG_FILE,
            maxBytes=10_000_000,  # 10 MB
            backupCount=5,
            encoding="utf-8",  # CRÍTICO: UTF-8 para español
        )
        file_handler.setLevel(logging.DEBUG)  # Archivo siempre con máximo detalle
        file_handler.setFormatter(formatter)
        file_handler.handleError = _safe_handle_error
        
        root_logger.addHandler(file_handler)
    except Exception as exc:
        # Si falla el archivo, al menos tenemos consola
        root_logger.warning("No se pudo configurar logging a archivo (%s), usando solo consola", exc)
    
    # ─── Configurar handlers específicos por módulo ──────────────────
    
    # Ollama: más detallado
    logging.getLogger("zenix.ollama").setLevel(logging.DEBUG)
    
    # GUI: normal
    logging.getLogger("zenix.gui").setLevel(logging.INFO)
    
    # Speech: verbose para diagnosis
    logging.getLogger("zenix.speech").setLevel(logging.DEBUG)
    
    # Librerías externas: warnings only
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pyttsx3").setLevel(logging.WARNING)
    
    root_logger.debug("[LOGGING] Sistema de logging inicializado correctamente")


def _safe_handle_error(handler, record):
    """
    Manejador de errores robusto para logging.
    
    Si un error ocurre dentro del logging (ej: encoding), 
    lo capturamos silenciosamente sin romper la app.
    """
    try:
        # Intento simplificado: escribir solo el mensaje sin formato
        if hasattr(handler, 'stream'):
            handler.stream.write(f"[LOGGING_ERROR] {record.getMessage()}\n")
            handler.stream.flush()
    except Exception:
        # Si todo falla, al menos no rompemos la app
        pass


class ZenixLoggerAdapter(logging.LoggerAdapter):
    """
    Adaptador de logging que prefija automáticamente [ZENIX] a cada línea.
    
    Uso:
        log = logging.getLogger("zenix.module")
        adapter = ZenixLoggerAdapter(log, {})
        adapter.info("Mensaje")  # Salida: [ZENIX] Mensaje
    """
    
    def process(self, msg, kwargs):
        return f"[ZENIX] {msg}", kwargs


# Inicializar logging al importar este módulo
setup_logging()
