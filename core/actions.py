"""Módulo de acciones de Zenix."""
from pathlib import Path
import subprocess


def open_vscode() -> str:
    try:
        subprocess.Popen(["code", "."])
        return "Abriendo VS Code~"
    except FileNotFoundError:
        return "No encontré VS Code en la ruta del sistema."
    except Exception as exc:
        return f"Error abriendo VS Code: {exc}"


def create_word_file(path: Path) -> str:
    return f"Funcionalidad de crear Word aún no implementada. Ruta: {path}"


def create_excel_file(path: Path) -> str:
    return f"Funcionalidad de crear Excel aún no implementada. Ruta: {path}"


def create_ppt_file(path: Path) -> str:
    return f"Funcionalidad de crear PowerPoint aún no implementada. Ruta: {path}"
