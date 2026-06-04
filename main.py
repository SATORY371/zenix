"""
╔══════════════════════════════════════════════════════════════════╗
║         ZENIX v2.0 — Punto de Entrada Principal                  ║
║   Ejecuta: python main.py                                         ║
╚══════════════════════════════════════════════════════════════════╝
"""

# CRÍTICO: Inicializar logging PRIMERO antes de cualquier módulo
from core.logging_setup import setup_logging
setup_logging()

from core.gui import launch


if __name__ == "__main__":
    try:
        launch()
    except KeyboardInterrupt:
        print("\nZenix: Hasta luego, Amo... *cierra los ojos suavemente* 🦊")
