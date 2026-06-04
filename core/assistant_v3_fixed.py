"""
╔══════════════════════════════════════════════════════════════════╗
║         ZENIX v2.0 — Módulo Ollama (COMPLETAMENTE CORREGIDO)    ║
║   Timeouts inteligentes, streaming, endpoint válido, robusto     ║
╚══════════════════════════════════════════════════════════════════╝

CAMBIOS PRINCIPALES:
1. Timeouts: (30s conexión, 300s lectura) para respuestas largas
2. Payload: Solo usa options.num_predict, SIN max_tokens duplicado
3. Endpoints: Solo /api/tags (es fiable), sin /api/models (404)
4. Streaming: Implementado stream=True con lectura incremental
5. Precarga: No marca Ollama como offline si falla
6. Logging: Centralizado con UTF-8
"""

import json
import logging
import re
import requests
import socket
import threading
import time
from urllib.parse import urljoin, urlparse
from config import Config, get_ollama_base_url
from .logging_setup import setup_logging

log = logging.getLogger("zenix.ollama")


def load_system_prompt() -> str:
    """Carga el prompt del sistema desde archivo."""
    from config import get_system_prompt_path
    prompt_path = get_system_prompt_path()
    if not prompt_path.exists():
        raise FileNotFoundError(f"No se encontró el prompt del sistema en {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


PERSONALIDAD_BASE = load_system_prompt()


# ══════════════════════════════════════════════════════════════════════
# LÍMITES Y PROCESAMIENTO DE RESPUESTAS
# ══════════════════════════════════════════════════════════════════════

def _is_long_explanation_request(user_text: str) -> bool:
    """Detecta si el usuario solicita una explicación extendida."""
    normalized = user_text.strip().lower()
    keywords = [
        "explica", "explícame", "explicame", "detalla", "detallar", "razón", "razon", 
        "por qué", "por que", "más detalles", "mas detalles", "explicación", "profundiza", 
        "describe", "ampliar", "amplía", "cómo", "como"
    ]
    return any(keyword in normalized for keyword in keywords)


def _determine_max_tokens(user_text: str) -> int:
    """Determina max_tokens según el tipo de consulta."""
    return 180 if _is_long_explanation_request(user_text) else 60


def _sanitize_response_text(text: str) -> str:
    """Elimina razonamiento interno y cleaning de la respuesta."""
    if text is None:
        return ""
    cleaned = text.strip()
    # Marcadores a eliminar (Thinking Process, Chain of Thought, etc.)
    markers = [
        "Thinking Process:", "Thinking...", "Chain of Thought", "razonamiento interno",
        "proceso de razonamiento", "pensando", "thinking process", "chain of thought",
        "<think>", "</think>", "<thinking>", "</thinking>", "<internal>", "</internal>"
    ]
    for marker in markers:
        cleaned = cleaned.replace(marker, "")
    # Normalizar espacios
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _limit_text_to_sentences(text: str, max_sentences: int) -> str:
    """Limita el texto a N oraciones máximo."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) <= max_sentences:
        return text.strip()
    truncated = " ".join(sentences[:max_sentences]).strip()
    if truncated and truncated[-1] not in ".!?":
        truncated += "."
    return truncated


def _truncate_text_by_tokens(text: str, max_tokens: int) -> str:
    """Limita el texto a N tokens aproximados."""
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text.strip()
    return " ".join(tokens[:max_tokens]).strip()


def _limit_response(user_text: str, response_text: str) -> str:
    """Pipeline completo de limitación de respuesta."""
    normalized = _sanitize_response_text(response_text)
    max_sentences = 4 if _is_long_explanation_request(user_text) else 2
    max_tokens = 180 if _is_long_explanation_request(user_text) else 60
    normalized = _limit_text_to_sentences(normalized, max_sentences)
    normalized = _truncate_text_by_tokens(normalized, max_tokens)
    return normalized.strip()


# ══════════════════════════════════════════════════════════════════════
# CONSTRUCCIÓN DE PAYLOAD
# ══════════════════════════════════════════════════════════════════════

def _build_ollama_payload(user_text: str, hidden: bool = False) -> dict:
    """
    Construye payload válido para Ollama 0.2.x+
    
    CORREGIDO:
    - Solo usa 'options' con 'num_predict', SIN 'max_tokens' duplicado
    - Usa 'stream' para controlar streaming
    - Incluye 'keep_alive' para mantener modelo cargado
    """
    message_content = user_text if not hidden else "Hola"
    
    payload = {
        "model": Config.MODEL,
        "messages": [
            {"role": "system", "content": PERSONALIDAD_BASE},
            {"role": "user", "content": message_content},
        ],
        "stream": Config.USE_STREAMING and not hidden,
        "options": {
            "temperature": 0.7,
            "num_predict": _determine_max_tokens(user_text) if not hidden else 10,
        },
        "keep_alive": "5m",  # Mantener modelo 5 minutos en memoria
    }
    
    log.debug("[OLLAMA] Payload construido: modelo=%s, tokens=%s, stream=%s",
              payload["model"], payload["options"]["num_predict"], payload["stream"])
    
    return payload


# ══════════════════════════════════════════════════════════════════════
# UTILIDADES DE OLLAMA
# ══════════════════════════════════════════════════════════════════════

def _normalize_ollama_base_url() -> str:
    """Extrae URL base de Ollama (sin /api/chat)."""
    parsed = urlparse(Config.OLLAMA_API_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def _extract_text_from_ollama_response(obj) -> str:
    """Extrae texto de Ollama con prioridad estricta, sin campos thinking."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, dict):
        message = obj.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                text = content.strip()
                log.info("[OLLAMA] CONTENT DETECTADO:\n%s", text)
                return text

        for key in ("content", "response", "text", "output_text"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        # Buscar en choices (formato API estándar)
        if "choices" in obj and obj["choices"]:
            return _extract_text_from_ollama_response(obj["choices"][0])
        # Buscar en output
        if "output" in obj:
            return _extract_text_from_ollama_response(obj["output"])
        # Buscar en delta (streaming)
        if "delta" in obj:
            return _extract_text_from_ollama_response(obj["delta"])
        return ""
    if isinstance(obj, list):
        pieces = []
        for item in obj:
            text = _extract_text_from_ollama_response(item)
            if text:
                pieces.append(text)
        return "".join(pieces).strip()
    return ""


def _parse_ollama_response(response: requests.Response) -> dict | str:
    """
    Parsea respuesta de Ollama (JSON completo o streaming).
    
    Retorna:
        - dict si es JSON completo
        - str si es streaming concatenado
    """
    log.debug("[OLLAMA] Status: %d, Content-Length: %s",
              response.status_code, response.headers.get("content-length", "unknown"))
    
    # Intenta JSON completo primero
    try:
        full = response.json()
        text = _extract_text_from_ollama_response(full)
        if text:
            return {"stream_text": text, "raw": full}
        return full
    except json.JSONDecodeError:
        log.debug("[OLLAMA] No es JSON completo, intentando streaming...")
    
    # Fallback: parsea línea por línea (streaming)
    text_parts = []
    try:
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if line.startswith("data:"):
                line = line[len("data:"):].strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                text = ""
                message = item.get("message") if isinstance(item, dict) else None
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        text = content.strip()
                if text:
                    text_parts.append(text)
            except json.JSONDecodeError:
                continue
    except Exception as exc:
        log.warning("[OLLAMA] Error parseando líneas: %s", exc)
    
    if text_parts:
        return "".join(text_parts)
    
    # Último recurso: devuelve raw text
    return response.text


# ══════════════════════════════════════════════════════════════════════
# LLAMADAS A OLLAMA
# ══════════════════════════════════════════════════════════════════════

def _perform_ollama_request(payload: dict, timeout: tuple | int | None = None) -> requests.Response:
    """
    Realiza POST a Ollama con timeouts configurables.
    
    Args:
        payload: Dict con configuración de modelo
        timeout: None = usar Config.OLLAMA_TIMEOUT (30s, 300s)
                 int = igual para conexión y lectura
                 tuple = (conexión, lectura)
    """
    if timeout is None:
        timeout = Config.OLLAMA_TIMEOUT  # (30, 300)
    
    url = Config.OLLAMA_API_URL
    log.info("[OLLAMA] POST %s (timeout=%s)", url, timeout)
    
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response


def _extract_token_count(data: dict | str) -> int | None:
    """Intenta extraer información de tokens de la respuesta."""
    if isinstance(data, str):
        return None
    if not isinstance(data, dict):
        return None
    
    # Buscar en campos estándar
    for field in ("usage", "token_usage"):
        if field in data and isinstance(data[field], dict):
            for key in ("total_tokens", "completion_tokens"):
                if key in data[field]:
                    return data[field][key]
    
    # Buscar en top level
    for key in ("total_tokens", "tokens", "token_count"):
        if key in data and isinstance(data[key], int):
            return data[key]
    
    return None


# ══════════════════════════════════════════════════════════════════════
# PRECARGA DE MODELO (WARMUP)
# ══════════════════════════════════════════════════════════════════════

_warmup_done = False
_last_warmup = 0.0


def preload_ollama_model() -> bool:
    """
    Precarga el modelo en Ollama sin marcar como error si falla.
    
    CORREGIDO:
    - No marca Ollama como desconectado si falla
    - Solo advierte en logs
    - Usa timeout más corto (WARMUP_TIMEOUT)
    
    Retorna:
        True si la precarga fue exitosa
        False si falló (pero no es crítico)
    """
    global _warmup_done, _last_warmup
    
    # Evitar caché: solo precargar cada 5 minutos max
    if _warmup_done and time.time() - _last_warmup < 300:
        return True
    
    log.info("[OLLAMA] Iniciando precarga del modelo...")
    payload = _build_ollama_payload("Hola", hidden=True)
    
    try:
        start = time.perf_counter()
        # TIMEOUT SEPARADO para warmup (más corto, no crítico)
        response = _perform_ollama_request(payload, timeout=Config.OLLAMA_WARMUP_TIMEOUT)
        data = _parse_ollama_response(response)
        elapsed = (time.perf_counter() - start) * 1000
        
        log.info("[OLLAMA] Precarga completada en %.0f ms", elapsed)
        
        tokens = _extract_token_count(data)
        if tokens:
            log.debug("[OLLAMA] Tokens de precarga: %d", tokens)
        
        _warmup_done = True
        _last_warmup = time.time()
        return True
        
    except requests.Timeout:
        # Timeout en precarga NO es crítico
        log.warning("[OLLAMA] Precarga tardó más de %ds (normal en modelos lentos, intentando luego)",
                    Config.OLLAMA_WARMUP_TIMEOUT)
        return False
    except Exception as exc:
        # Otros errores: solo advertencia, NO marca offline
        log.warning("[OLLAMA] Precarga falló (no crítico): %s", exc)
        return False
    finally:
        _last_warmup = time.time()


# ══════════════════════════════════════════════════════════════════════
# INTERFAZ PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

def ask_ollama(user_text: str) -> tuple[str, float]:
    """
    Consulta a Ollama y retorna respuesta + tiempo de ejecución.
    
    Args:
        user_text: Pregunta del usuario
    
    Retorna:
        (respuesta_procesada, tiempo_segundos)
    """
    log.info("[CHAT] Usuario: %s", user_text)
    
    start_total = time.perf_counter()
    
    # Construir payload
    payload_start = time.perf_counter()
    payload = _build_ollama_payload(user_text)
    payload_time = (time.perf_counter() - payload_start) * 1000
    log.debug("[OLLAMA] Payload en %.0f ms", payload_time)
    
    try:
        # Llamar a Ollama (con timeout inteligente)
        request_start = time.perf_counter()
        response = _perform_ollama_request(payload)
        request_time = (time.perf_counter() - request_start) * 1000
        
        # Parsear respuesta
        data = _parse_ollama_response(response)
        total_time = (time.perf_counter() - start_total) * 1000
        
        log.info("[PERFORMANCE] Generación: %.0f ms | Total: %.0f ms",
                 request_time, total_time)
        
        tokens = _extract_token_count(data) if isinstance(data, dict) else None
        if tokens:
            log.debug("[PERFORMANCE] Tokens: %d", tokens)
        
        # Extraer y procesar texto
        if isinstance(data, dict) and isinstance(data.get("stream_text"), str):
            raw_text = data["stream_text"].strip()
        elif isinstance(data, dict):
            raw_text = _extract_text_from_ollama_response(data)
        else:
            raw_text = data.strip() if isinstance(data, str) else ""
        
        if raw_text:
            log.info("[OLLAMA] CONTENT DETECTADO:\n%s", raw_text)
        
        result_text = _limit_response(user_text, raw_text) if raw_text else ""
        
        if not result_text:
            log.warning("[OLLAMA] Respuesta vacía de Ollama")
            return ("No recibí respuesta válida de Ollama.", total_time / 1000.0)
        
        # Logs de rendimiento
        if total_time > 30000:  # 30 segundos
            log.warning("[PERFORMANCE] Respuesta lenta: %.0f ms", total_time)
        
        log.debug("[OLLAMA] Respuesta: %s", result_text[:100])
        return (result_text, total_time / 1000.0)
        
    except requests.Timeout as exc:
        elapsed = time.perf_counter() - start_total
        log.error("[OLLAMA] TIMEOUT después de %.0f s: %s", elapsed, exc)
        # Precarga en background si falló por timeout
        threading.Thread(target=preload_ollama_model, daemon=True).start()
        return (
            f"Ollama tardó más de {Config.OLLAMA_TIMEOUT_READ}s. Intenta una pregunta más simple.",
            elapsed
        )
    except requests.ConnectionError as exc:
        elapsed = time.perf_counter() - start_total
        log.error("[OLLAMA] ERROR DE CONEXIÓN: %s", exc)
        return (
            f"No puedo conectar con Ollama en {Config.OLLAMA_API_URL}. ¿Está ejecutándose?",
            elapsed
        )
    except requests.RequestException as exc:
        elapsed = time.perf_counter() - start_total
        log.error("[OLLAMA] ERROR EN REQUEST: %s", exc)
        return (f"Error de red: {exc}", elapsed)
    except json.JSONDecodeError as exc:
        elapsed = time.perf_counter() - start_total
        log.error("[OLLAMA] ERROR PARSEANDO JSON: %s", exc)
        return (f"Respuesta inválida de Ollama: {exc}", elapsed)
    except Exception as exc:
        elapsed = time.perf_counter() - start_total
        log.error("[OLLAMA] ERROR INESPERADO: %s", exc, exc_info=True)
        return (f"Error inesperado: {exc}", elapsed)


# ══════════════════════════════════════════════════════════════════════
# DIAGNÓSTICO DE OLLAMA
# ══════════════════════════════════════════════════════════════════════

def diagnose_ollama() -> dict:
    """
    Diagnóstico completo de la conexión a Ollama.
    
    CORREGIDO:
    - Solo usa /api/tags (nunca /api/models que devuelve 404)
    - Usa timeout de diagnóstico (Config.OLLAMA_HEALTH_TIMEOUT)
    - No marca como offline si hay timeout en diagnóstico
    """
    result = {
        "connected": False,
        "port_available": False,
        "api_responding": False,
        "model_installed": False,
        "available_models": [],
        "errors": [],
    }
    
    parsed = urlparse(Config.OLLAMA_API_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    
    # Verificar puerto
    log.info("[DIAGNÓSTICO] Verificando puerto %s:%d...", host, port)
    try:
        with socket.create_connection((host, port), timeout=2):
            result["port_available"] = True
            log.info("[DIAGNÓSTICO] Puerto disponible")
    except OSError as exc:
        result["errors"].append(f"Puerto no accesible: {exc}")
        log.warning("[DIAGNÓSTICO] Puerto no accesible: %s", exc)
        return result
    
    base_url = _normalize_ollama_base_url()
    
    # Verificar /api/status
    log.info("[DIAGNÓSTICO] Verificando /api/status...")
    try:
        resp = requests.get(f"{base_url}/api/status", timeout=Config.OLLAMA_HEALTH_TIMEOUT)
        resp.raise_for_status()
        result["api_responding"] = True
        log.info("[DIAGNÓSTICO] API respondiendo")
    except Exception as exc:
        result["errors"].append(f"/api/status falló: {exc}")
        log.warning("[DIAGNÓSTICO] /api/status falló: %s", exc)
    
    # Verificar /api/tags (ÚNICO endpoint fiable para modelos)
    log.info("[DIAGNÓSTICO] Verificando /api/tags...")
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=Config.OLLAMA_HEALTH_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        
        # Extraer modelos
        if "models" in data:
            for model in data["models"]:
                if isinstance(model, dict):
                    model_name = model.get("name") or model.get("model")
                    if model_name:
                        result["available_models"].append(model_name)
                        if model_name == Config.MODEL:
                            result["model_installed"] = True
        
        log.info("[DIAGNÓSTICO] Modelos encontrados: %s", result["available_models"])
    except Exception as exc:
        result["errors"].append(f"/api/tags falló: {exc}")
        log.warning("[DIAGNÓSTICO] /api/tags falló: %s", exc)
    
    result["connected"] = result["port_available"] and result["api_responding"]
    
    log.info("[DIAGNÓSTICO] Resultado: %s", result)
    return result


def prompt_loop() -> None:
    """
    Loop REPL para testing (CLI sin GUI).
    
    CORREGIDO: Maneja tupla desde ask_ollama
    """
    from .speech import speak
    
    speak("Hola, soy Zenix 2.0. Di \"salir\" para terminar.")
    
    while True:
        try:
            user_text = input(">> ").strip()
            if not user_text:
                continue
            if user_text.lower() in {"salir", "adiós", "adios", "exit"}:
                speak("¡Hasta luego!")
                break
            
            # CORREGIDO: ask_ollama devuelve tupla
            response, elapsed = ask_ollama(user_text)
            speak(response)
            print(f"[{elapsed:.2f}s]\n")
            
        except KeyboardInterrupt:
            break
        except Exception as exc:
            log.error("[REPL] Error: %s", exc)
            print(f"Error: {exc}")
