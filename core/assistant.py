import json
import logging
import re
import requests
import socket
import threading
import time
from urllib.parse import urljoin, urlparse
from config import Config, get_system_prompt_path
from .speech import listen_microphone, speak

log = logging.getLogger("zenix.ollama")


def load_system_prompt() -> str:
    prompt_path = get_system_prompt_path()
    if not prompt_path.exists():
        raise FileNotFoundError(f"No se encontró el prompt del sistema en {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


PERSONALIDAD_BASE = load_system_prompt()


def _is_long_explanation_request(user_text: str) -> bool:
    normalized = user_text.strip().lower()
    keywords = [
        "explica", "explícame", "explicame", "detalla", "detallar", "razón", "razon", "por qué", "por que",
        "más detalles", "mas detalles", "explicación", "profundiza", "describe", "ampliar", "amplía"
    ]
    return any(keyword in normalized for keyword in keywords)


def _determine_max_tokens(user_text: str) -> int:
    # Long explanations need more tokens; very short greetings should be fast.
    if _is_long_explanation_request(user_text):
        return 180
    short = user_text.strip()
    if len(short) <= 20:
        return 40
    return 60


def _sanitize_response_text(text: str) -> str:
    if text is None:
        return ""
    cleaned = text.strip()
    markers = [
        "Thinking Process:", "Thinking...", "Chain of Thought", "razonamiento interno",
        "proceso de razonamiento", "pensando", "thinking process", "chain of thought"
    ]
    for marker in markers:
        cleaned = cleaned.replace(marker, "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _limit_text_to_sentences(text: str, max_sentences: int) -> str:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) <= max_sentences:
        return text.strip()
    truncated = " ".join(sentences[:max_sentences]).strip()
    if truncated and truncated[-1] not in ".!?":
        truncated += "."
    return truncated


def _truncate_text_by_tokens(text: str, max_tokens: int) -> str:
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text.strip()
    return " ".join(tokens[:max_tokens]).strip()


def _limit_response(user_text: str, response_text: str) -> str:
    normalized = _sanitize_response_text(response_text)
    max_sentences = 4 if _is_long_explanation_request(user_text) else 2
    max_tokens = 180 if _is_long_explanation_request(user_text) else 60
    normalized = _limit_text_to_sentences(normalized, max_sentences)
    normalized = _truncate_text_by_tokens(normalized, max_tokens)
    return normalized.strip()


def _shorten_text(text: str, max_chars: int = 80) -> str:
    snippet = text.strip().replace("\n", " ").replace("\r", " ")
    snippet = re.sub(r"\s+", " ", snippet)
    if len(snippet) <= max_chars:
        return snippet
    return snippet[:max_chars].rstrip(" .,:;?!")


def _summarize_chat_history(history: list[dict]) -> str:
    if not history:
        return ""
    user_excerpts = [item["content"] for item in history if item.get("role") == "user" and item.get("content")]
    if not user_excerpts:
        return ""
    recent_requests = [ _shorten_text(text, 90) for text in user_excerpts[-5:] ]
    return (
        f"El historial previo contiene {len(user_excerpts)} solicitudes. "
        f"Últimas solicitudes: {'; '.join(recent_requests)}."
    )


def _build_history_messages(history: list[dict]) -> list[dict]:
    if not history:
        return []
    if len(history) <= 20:
        return [dict(item) for item in history]

    recent = history[-20:]
    summary = _summarize_chat_history(history[:-20])
    if summary:
        return [
            {"role": "system", "content": f"Resumen de la conversación previa: {summary}"},
            *[dict(item) for item in recent],
        ]
    return [dict(item) for item in recent]


def _build_ollama_payload(
    user_text: str,
    hidden: bool = False,
    history: list[dict] | None = None,
    extra_system_messages: list[str] | None = None,
    max_tokens: int | None = None,
    model_name: str | None = None,
) -> dict:
    message_content = user_text if not hidden else "Hola"
    messages = [{"role": "system", "content": PERSONALIDAD_BASE}]

    if history:
        messages.extend(_build_history_messages(history))

    if extra_system_messages:
        for system_message in extra_system_messages:
            messages.append({"role": "system", "content": system_message})

    if hidden or not history or not (
        history and history[-1].get("role") == "user" and history[-1].get("content") == user_text
    ):
        messages.append({"role": "user", "content": message_content})

    payload = {
        "model": model_name if model_name else Config.MODEL,
        "messages": messages,
        "options": {
            "temperature": 0.7,
            "num_predict": max_tokens if max_tokens is not None else (_determine_max_tokens(user_text) if not hidden else 10),
        },
        "stream": False,
        "keep_alive": "5m",
    }

    log.info(
        "[OLLAMA] Payload preparado: modelo=%s, mensajes=%d, tokens=%s, stream=%s",
        payload["model"],
        len(payload["messages"]),
        payload["options"]["num_predict"],
        payload["stream"],
    )
    return payload


def _normalize_ollama_base_url() -> str:
    parsed = urlparse(Config.OLLAMA_API_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def _iter_json_objects(raw_text: str):
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(raw_text):
        while idx < len(raw_text) and raw_text[idx].isspace():
            idx += 1
        if idx >= len(raw_text):
            break
        try:
            obj, consumed = decoder.raw_decode(raw_text[idx:])
        except ValueError:
            break
        yield obj
        idx += consumed


def _extract_text_from_ollama_object(obj) -> str:
    # Prioridad estricta: A) message.content B) content C) response D) text E) output_text.
    # Nunca se extraen campos thinking/razonamiento.
    if obj is None:
        return ""

    if isinstance(obj, str):
        return obj.strip()

    if isinstance(obj, dict):
        message = obj.get('message')
        if isinstance(message, dict):
            content = message.get('content')
            if isinstance(content, str) and content.strip():
                text = content.strip()
                log.info('[OLLAMA] CONTENT DETECTADO:\n%s', text)
                return text

        for key in ('content', 'response', 'text', 'output_text'):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

        return ""

    # Si es lista, concatenar únicamente valores válidos extraídos recursivamente
    if isinstance(obj, list):
        pieces: list[str] = []
        for item in obj:
            if isinstance(item, (dict, list, str)):
                text = _extract_text_from_ollama_object(item)
                if text:
                    pieces.append(text)
        return "".join(pieces).strip()

    return ""


def _find_string_values(obj) -> list[str]:
    if obj is None:
        return []
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        values: list[str] = []
        for value in obj.values():
            values.extend(_find_string_values(value))
        return values
    if isinstance(obj, list):
        values: list[str] = []
        for item in obj:
            values.extend(_find_string_values(item))
        return values
    return []


def _parse_ollama_response(response: requests.Response):
    """Parsea la respuesta de Ollama de forma segura.

    - Soporta respuesta completa JSON y streaming line-delimited JSON / SSE.
    - Extrae solo message.content o campos fallback simples.
    - Ignora thinking, reasoning y metadatos.
    - Reconstruye chunks de stream en texto final.
    """

    def _fallback_raw_text() -> str:
        try:
            raw = response.text
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8', errors='replace')
            raw = (raw or '').strip()
            return raw
        except Exception:
            return ""

    try:
        full = response.json()
        log.debug("[OLLAMA] JSON completo recibido: %s", type(full))
        text = _extract_text_from_ollama_object(full)
        if text:
            return {'stream_text': text, 'raw': full}
        return full
    except ValueError:
        log.debug('[OLLAMA] No es JSON completo; devolviendo texto bruto.')
    except Exception as exc:
        log.warning('[OLLAMA] Error al parsear JSON completo: %s', exc, exc_info=True)

    return _fallback_raw_text()


def _perform_ollama_request(payload: dict) -> requests.Response:
    url = Config.OLLAMA_API_URL
    log.info("[OLLAMA] POST %s", url)
    # habilitar stream en requests sólo si el payload solicita streaming
    stream_flag = bool(payload.get('stream', False))
    try:
        response = requests.post(url, json=payload, timeout=Config.OLLAMA_TIMEOUT, stream=stream_flag)
    except TypeError:
        # requests versiones antiguas pueden rechazar tuple timeout en ciertas firmas
        response = requests.post(url, json=payload, timeout=Config.OLLAMA_TIMEOUT)
    response.raise_for_status()
    return response


def _extract_token_usage(data: dict) -> int | None:
    if not isinstance(data, dict):
        return None
    candidates = []
    if "usage" in data and isinstance(data["usage"], dict):
        candidates.append(data["usage"].get("total_tokens"))
        candidates.append(data["usage"].get("completion_tokens"))
        candidates.append(data["usage"].get("prompt_tokens"))
    if "token_usage" in data and isinstance(data["token_usage"], dict):
        candidates.extend(data["token_usage"].values())
    for key in ("total_tokens", "tokens", "token_count"):
        candidates.append(data.get(key))
    for value in candidates:
        if isinstance(value, int):
            return value
    return None


_warmup_done = False
_last_warmup = 0.0


def preload_ollama_model() -> None:
    global _warmup_done, _last_warmup
    if _warmup_done and time.time() - _last_warmup < 300:
        return

    log.info("[OLLAMA] Iniciando precarga de modelo con consulta oculta...")
    payload = _build_ollama_payload("Hola", hidden=True)
    try:
        start = time.perf_counter()
        response = _perform_ollama_request(payload)
        self_data = _parse_ollama_response(response)
        elapsed = (time.perf_counter() - start) * 1000
        log.info("[OLLAMA] Precarga completada en %.0f ms", elapsed)
        if isinstance(self_data, dict):
            tokens = _extract_token_usage(self_data)
            if tokens is not None:
                log.info("[OLLAMA] Tokens de precarga: %s", tokens)
    except Exception as exc:
        log.warning("[OLLAMA] No se pudo precargar el modelo: %s", exc)
    finally:
        _warmup_done = True
        _last_warmup = time.time()


def ask_ollama(
    user_text: str,
    history: list[dict] | None = None,
    strict: bool = False,
    allow_retry: bool = True,
    full_response: bool = False,
    max_tokens: int | None = None,
    model_name: str | None = None,
    extra_system_messages: list[str] | None = None,
) -> tuple[str, float, dict[str, float]]:
    log.info("[CHAT] Usuario: %s", user_text)
    start_total = time.perf_counter()
    payload_start = time.perf_counter()

    # Inicializar métricas para evitar UnboundLocalError
    request_ms = 0.0
    parse_ms = 0.0
    total_ms = 0.0

    # Combinar mensajes extra proporcionados por el llamador con los internos (p.ej. strict)
    combined_extra_system_messages: list[str] = []
    if extra_system_messages:
        combined_extra_system_messages.extend(extra_system_messages)
    if strict:
        combined_extra_system_messages.append(
            "Responde únicamente con la respuesta final. No muestres razonamiento. "
            "No muestres thinking. No expliques tu proceso mental."
        )

    payload = _build_ollama_payload(
        user_text,
        history=history,
        extra_system_messages=combined_extra_system_messages or None,
        max_tokens=max_tokens,
        model_name=model_name,
    )
    payload_build_ms = (time.perf_counter() - payload_start) * 1000
    log.info("[OLLAMA] Payload preparado en %.0f ms", payload_build_ms)
    log.info("[OLLAMA] Modelo enviado a API: %s", payload["model"])

    # Ejecutar la petición con detección de timeouts y posibilidad de reintento
    data = None
    tokens = None
    last_exception = None
    for attempt in range(2):
        try:
            request_start = time.perf_counter()
            response = _perform_ollama_request(payload)
            request_ms = (time.perf_counter() - request_start) * 1000

            parse_start = time.perf_counter()
            data = _parse_ollama_response(response)
            parse_ms = (time.perf_counter() - parse_start) * 1000

            total_ms = (time.perf_counter() - start_total) * 1000
            tokens = _extract_token_usage(data) if isinstance(data, dict) else None
            log.info("[PERFORMANCE] Payload: %.0f ms | Request: %.0f ms | Parse: %.0f ms | Total: %.0f ms",
                     payload_build_ms, request_ms, parse_ms, total_ms)
            if tokens is not None:
                log.info("[PERFORMANCE] Tokens generados: %d", tokens)
            # Diagnóstico adicional: uso de memoria y VRAM cuando sea posible
            try:
                import psutil
                mem = psutil.virtual_memory()
                log.info("[DIAGNOSTIC] RAM uso: %s%% (%sMB available)", mem.percent, int(mem.available / 1024 / 1024))
            except Exception:
                log.debug("[DIAGNOSTIC] psutil no disponible para diagnóstico de memoria")
            try:
                import GPUtil
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    log.info("[DIAGNOSTIC] GPU memoria usada: %sMB / %sMB", int(gpu.memoryUsed), int(gpu.memoryTotal))
            except Exception:
                log.debug("[DIAGNOSTIC] GPUtil no disponible o sin GPU detectada")
            if total_ms > 5000:
                log.warning("[PERFORMANCE] ADVERTENCIA: consulta tardó %.0f ms (> 5000 ms)", total_ms)
                if not _warmup_done:
                    try:
                        threading.Thread(target=preload_ollama_model, daemon=True).start()
                    except Exception:
                        pass
            # éxito
            break
        except requests.exceptions.ReadTimeout as exc:
            # Timeout de lectura: permitir un reintento rápido, luego devolver mensaje amigable
            log.warning("[OLLAMA] ReadTimeout (%s). Intento %d/2", exc, attempt + 1)
            last_exception = exc
            if attempt == 0 and allow_retry:
                continue
            # devolver mensaje amigable
            friendly = (
                "El modelo tardó demasiado en responder. Intenta nuevamente o usa un modelo más ligero."
            )
            total_ms = (time.perf_counter() - start_total) * 1000
            return friendly, total_ms / 1000.0, {"payload_ms": payload_build_ms, "request_ms": request_ms, "parse_ms": parse_ms, "total_ms": total_ms}
        except requests.RequestException as exc:
            # Error de red u otro problema; no reintentar por defecto
            log.error("[OLLAMA] ERROR de request: %s", exc, exc_info=True)
            last_exception = exc
            diagnosis = verificar_ollama()
            log.error("[OLLAMA] DIAGNÓSTICO AUTOMÁTICO: %s", diagnosis)
            total_ms = (time.perf_counter() - start_total) * 1000
            return (
                f"No pude conectar con Ollama. Revisa que esté ejecutándose en {Config.OLLAMA_API_URL}. Error: {exc}",
                total_ms / 1000.0,
                {"payload_ms": payload_build_ms, "request_ms": request_ms, "parse_ms": parse_ms, "total_ms": total_ms},
            )
        except ValueError as exc:
            log.error("[OLLAMA] ERROR parseando respuesta: %s", exc, exc_info=True)
            total_ms = (time.perf_counter() - start_total) * 1000
            return (f"Respuesta inválida de Ollama: {exc}", total_ms / 1000.0, {"payload_ms": payload_build_ms, "request_ms": request_ms, "parse_ms": parse_ms, "total_ms": total_ms})

    if isinstance(data, dict) and isinstance(data.get('stream_text'), str) and data['stream_text'].strip():
        raw_text = data['stream_text'].strip()
    elif isinstance(data, (dict, list)):
        raw_text = _extract_text_from_ollama_object(data)
    else:
        raw_text = data if isinstance(data, str) else ""

    raw_text = raw_text.strip() if isinstance(raw_text, str) else ""

    log.debug('[OLLAMA] Texto bruto extraido (len=%d) preview=%s', len(raw_text) if raw_text else 0, _shorten_text(raw_text, 80))

    # Si hay texto válido, priorizarlo y devolver sin reintentos ni modo estricto.
    if raw_text:
        log.info('[OLLAMA] CONTENT DETECTADO:\n%s', raw_text)
        result_text = raw_text.strip() if full_response else _limit_response(user_text, raw_text)
        log.info('[OLLAMA] Respuesta final (len=%d) generada en %.0f ms', len(result_text), total_ms)
        log.info('[OLLAMA] Caracteres generados: %d', len(result_text))
        return result_text, total_ms / 1000.0, {
            "payload_ms": payload_build_ms,
            "request_ms": request_ms,
            "parse_ms": parse_ms,
            "total_ms": total_ms,
        }

    # Si no hay texto real, se puede reintentar. El campo thinking nunca decide validez.
    if not raw_text:
        if allow_retry:
            log.warning('[OLLAMA] Respuesta sin content utilizable. Reintentando con instrucciones estrictas.')
            return ask_ollama(
                user_text,
                history=history,
                strict=True,
                allow_retry=False,
                full_response=full_response,
                max_tokens=max_tokens,
            )

        log.warning('[OLLAMA] Respuesta sin content utilizable después de reintentos.')
        return ("No recibí una respuesta válida de Ollama. Por favor intenta reformular tu pregunta.", total_ms / 1000.0, {
            "payload_ms": payload_build_ms,
            "request_ms": request_ms,
            "parse_ms": parse_ms,
            "total_ms": total_ms,
        })


def verificar_ollama(timeout: int = Config.OLLAMA_TIMEOUT) -> dict[str, object]:
    result: dict[str, object] = {
        "url": Config.OLLAMA_API_URL,
        "model": Config.MODEL,
        "port_available": False,
        "status": None,
        "models": [],
        "model_installed": False,
        "available_models": [],
        "tags": [],
    }

    parsed = urlparse(Config.OLLAMA_API_URL)
    try:
        port = parsed.port or 11434
        host = parsed.hostname or "127.0.0.1"
        with socket.create_connection((host, port), timeout=2):
            result["port_available"] = True
    except OSError as exc:
        result["status"] = f"Puerto {parsed.netloc} no accesible: {exc}"
        log.warning("[OLLAMA] Puerto no disponible: %s", exc)
        return result

    base_url = _normalize_ollama_base_url()
    status_url = urljoin(base_url, "/api/status")
    tags_url = urljoin(base_url, "/api/tags")

    try:
        status_resp = requests.get(status_url, timeout=timeout)
        status_resp.raise_for_status()
        result["status"] = status_resp.json()
    except requests.RequestException as exc:
        result["status"] = f"No se pudo consultar /api/status: {exc}"
        log.warning("[OLLAMA] Status check falló: %s", exc)

    try:
        tags_resp = requests.get(tags_url, timeout=timeout)
        tags_resp.raise_for_status()
        result["tags"] = tags_resp.json()
        log.info("[OLLAMA] JSON completo recibido desde /api/tags: %s", result["tags"])

        if isinstance(result["tags"], dict) and "models" in result["tags"]:
            for item in result["tags"]["models"]:
                if isinstance(item, dict):
                    model_name = item.get("name") or item.get("model")
                    if isinstance(model_name, str):
                        result["available_models"].append(model_name)
                        if model_name == Config.MODEL:
                            result["model_installed"] = True
        if not result["model_installed"]:
            found_in_tags = Config.MODEL in _find_string_values(result["tags"])
            if found_in_tags:
                result["model_installed"] = True
                log.info("[OLLAMA] Modelo configurado encontrado en /api/tags: %s", Config.MODEL)

        if result["available_models"]:
            result["active_model"] = Config.MODEL if result["model_installed"] else result["available_models"][0]
            result["model_detected"] = result["active_model"]
            log.info("[OLLAMA] MODELO ACTIVO REAL: %s", result["active_model"])
        else:
            result["active_model"] = None
            result["model_detected"] = None
    except requests.RequestException as exc:
        result["tags"] = []
        log.warning("[OLLAMA] Tags check falló: %s", exc)

    if result["port_available"] and result["status"] and result["model_installed"]:
        log.info("[OLLAMA] Conectado")

    log.info("[OLLAMA] VERIFICACIÓN: %s", result)
    return result


def prompt_loop() -> None:
    """
    Loop REPL para testing (CLI sin GUI).

    CORREGIDO: Maneja tupla desde ask_ollama y conserva historial local.
    """
    speak("Hola, soy Zenix 2.0. Puedes hablarme o escribirme tu comando. Di \"salir\" para terminar.")
    history: list[dict] = []

    while True:
        try:
            user_text = input(">> ").strip()
            if not user_text:
                continue
            if user_text.lower() in {"salir", "adios", "adiós", "exit", "cerrar"}:
                speak("¡Hasta luego! Vuelve pronto, nyan~")
                break

            response, elapsed, metrics = ask_ollama(user_text, history=history)
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": response})
            history = history[-200:]

            print(f"[{elapsed:.2f}s]")
            speak(response)

        except KeyboardInterrupt:
            break
        except Exception as exc:
            log.error("[REPL] Error: %s", exc)
            print(f"Error: {exc}")
