"""
Monitoreo del sistema para Zenix 3.0.
Recopila métricas de CPU, RAM, disco, GPU y red de forma segura.
"""

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    import psutil
except Exception:
    psutil = None

log = logging.getLogger("zenix.monitor")

GPU_QUERY_COMMAND = ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]


def _format_percent(value: float | None) -> str:
    return f"{value:.0f}%" if value is not None else "N/A"


def _format_value(value: float | None, units: str) -> str:
    return f"{value:.0f}{units}" if value is not None else "N/A"


def _get_root_path() -> str:
    return Path.cwd().anchor if sys.platform.startswith("win") else "/"


class SystemMonitor:
    """Recopila métricas de hardware y estado local."""

    @classmethod
    def get_cpu_percent(cls) -> float | None:
        if psutil:
            try:
                return psutil.cpu_percent(interval=0.12)
            except Exception as exc:
                log.warning("[MONITOR] No se pudo leer CPU: %s", exc)
        return None

    @classmethod
    def get_ram_percent(cls) -> float | None:
        if psutil:
            try:
                return psutil.virtual_memory().percent
            except Exception as exc:
                log.warning("[MONITOR] No se pudo leer RAM: %s", exc)
        return None

    @classmethod
    def get_disk_percent(cls) -> float | None:
        if psutil:
            try:
                return psutil.disk_usage(_get_root_path()).percent
            except Exception as exc:
                log.warning("[MONITOR] No se pudo leer disco: %s", exc)
        else:
            try:
                usage = shutil.disk_usage(_get_root_path())
                return usage.used / usage.total * 100 if usage.total else None
            except Exception as exc:
                log.warning("[MONITOR] No se pudo leer disco (shutil): %s", exc)
        return None

    @classmethod
    def get_temperature(cls) -> float | None:
        if psutil and hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for key in ("coretemp", "cpu-thermal", "acpitz"):
                        entries = temps.get(key)
                        if entries:
                            return float(entries[0].current)
                    # fallback al primer sensor disponible
                    first = next(iter(temps.values()), None)
                    if first:
                        return float(first[0].current)
            except Exception as exc:
                log.warning("[MONITOR] No se pudo leer temperatura: %s", exc)
        return None

    @classmethod
    def get_gpu_status(cls) -> dict[str, Any]:
        if not shutil.which("nvidia-smi"):
            return {"available": False, "description": "GPU no detectada", "usage": None}

        try:
            completed = subprocess.run(
                GPU_QUERY_COMMAND,
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            )
            output = completed.stdout.strip()
            if not output:
                return {"available": False, "description": "GPU sin datos", "usage": None}

            usage_lines = [line.strip() for line in output.splitlines() if line.strip()]
            if not usage_lines:
                return {"available": False, "description": "GPU sin datos", "usage": None}

            values = [line.split(",") for line in usage_lines]
            gpu_texts: list[str] = []
            for row in values:
                parts = [part.strip() for part in row]
                if len(parts) >= 3:
                    gpu_texts.append(f"GPU {parts[0]}% | MEM {parts[1]}/{parts[2]} MiB")
            return {
                "available": True,
                "description": "; ".join(gpu_texts) if gpu_texts else "GPU detectada",
                "usage": float(values[0][0]) if values and values[0] and values[0][0].isdigit() else None,
            }
        except Exception as exc:
            log.warning("[MONITOR] No se pudo consultar nvidia-smi: %s", exc)
            return {"available": False, "description": "GPU no accesible", "usage": None}

    @classmethod
    def get_network_summary(cls) -> str:
        if psutil:
            try:
                net = psutil.net_io_counters()
                sent = net.bytes_sent / 1024 / 1024
                recv = net.bytes_recv / 1024 / 1024
                return f"↑{sent:.1f}MiB ↓{recv:.1f}MiB"
            except Exception:
                pass
        return "N/A"

    @classmethod
    def get_summary(cls) -> dict[str, Any]:
        cpu = cls.get_cpu_percent()
        ram = cls.get_ram_percent()
        disk = cls.get_disk_percent()
        temp = cls.get_temperature()
        gpu = cls.get_gpu_status()
        return {
            "cpu": cpu,
            "ram": ram,
            "disk": disk,
            "temperature": temp,
            "gpu": gpu,
            "network": cls.get_network_summary(),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    @classmethod
    def format_summary(cls, summary: dict[str, Any]) -> str:
        cpu = _format_percent(summary.get("cpu"))
        ram = _format_percent(summary.get("ram"))
        gpu_desc = summary.get("gpu", {}).get("description") if isinstance(summary.get("gpu"), dict) else "N/A"
        temp = _format_value(summary.get("temperature"), "°C")
        net = summary.get("network", "N/A")
        return f"CPU {cpu} · RAM {ram} · GPU {gpu_desc} · T {temp} · Net {net}"
