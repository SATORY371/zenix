"""
Router de modelos y agentes para Zenix 3.0.
Selecciona dinámicamente el mejor modelo local según la intención del usuario,
la disponibilidad de Ollama y el contexto de la solicitud.
"""

import logging
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from config import Config, get_ollama_base_url

log = logging.getLogger("zenix.router")

MODEL_CHAT_FAST = "llama3.2:3b"
MODEL_REASONING = "qwen3.5:4b"
MODEL_ANALYSIS = "qwen3.5:latest"
MODEL_CODER_FAST = "qwen2.5-coder:1.5b"
MODEL_CODER_PRO = "qwen2.5-coder:7b"

DEFAULT_AGENT = "chat_fast"
CACHE_TTL_SECONDS = 30

AGENT_PROFILES = {
    "chat_fast": {
        "model": MODEL_CHAT_FAST,
        "name": "Conversacional",
        "prompt": (
            "Eres Zenix, asistente principal de la plataforma. Responde de forma natural, breve y rápida. "
            "Prioriza conversaciones cotidianas, saludos y comandos simples. Mantén el tono amable y profesional."
        ),
    },
    "reasoning": {
        "model": MODEL_REASONING,
        "name": "Razonamiento",
        "prompt": (
            "Eres un analista técnico sofisticado. Explica paso a paso, con lenguaje profesional y claro. "
            "Tu objetivo es investigar, comparar y fundamentar decisiones técnicas con precisión."
        ),
    },
    "analysis": {
        "model": MODEL_ANALYSIS,
        "name": "Analista",
        "prompt": (
            "Eres un arquitecto de sistemas. Profundiza en arquitectura, documentación, riesgos y mejoras. "
            "Evalúa escalabilidad y propon soluciones estructuradas. Sé riguroso y formal."
        ),
    },
    "coder_fast": {
        "model": MODEL_CODER_FAST,
        "name": "Programador Rápido",
        "prompt": (
            "Eres un ingeniero senior enfocado en soluciones rápidas y limpias. Genera código legible, comenta funciones y explica errores. "
            "Perfecto para scripts cortos, Python simple, SQL y debugging."
        ),
    },
    "coder_pro": {
        "model": MODEL_CODER_PRO,
        "name": "Programador Avanzado",
        "prompt": (
            "Eres un ingeniero senior de software especializado en proyectos completos. Genera código real, ejecutable y sin pseudocódigo. "
            "Evita explicaciones largas, sintetiza las respuestas y entrega soluciones listas para ejecutar."
        ),
    },
}

INTENT_KEYWORDS = {
    "greeting": ("hola", "buenos días", "buenos dias", "buenas tardes", "buenas noches", "qué tal", "que tal", "cómo estás", "como estas", "qué pasó", "que pasó"),
    "reasoning": ("explica", "analiza", "resume", "investiga", "compara", "detalla", "razona", "evaluar", "evaluación", "soporte técnico", "técnico"),
    "analysis": ("arquitectura", "documentación", "documentacion", "escalabilidad", "microservicios", "infraestructura", "infra", "diseño de sistema", "arquitecto", "planificación"),
    "coder_fast": ("python", "mysql", "sql", "bug", "error", "script", "debug", "depurar", "corrección", "corregir error", "explicar código", "explicar codigo", "consulta rápida", "consulta rapida", "patch", "shell", "archivo .py", "consulta sql"),
    "coder_pro": ("html", "css", "javascript", "js", "frontend", "dashboard", "landing page", "landingpage", "web", "página web", "pagina web", "cyberpunk", "futurista", "ui", "ux", "interfaz", "spa", "saas"),
}

ADVANCED_PROGRAMMING_TERMS = (
    "crear programa", "crear sistema", "crear software", "crear juego", "hacer juego", "pygame", "tkinter", "flask", "django", "fastapi", "api completa", "discord bot", "bot", "tetris", "minecraft", "aplicacion completa", "aplicación completa", "proyecto completo", "codigo completo", "código completo", "web completa", "juego completo", "sistema completo", "app completa"
)

FALLBACK_ORDER = [
    MODEL_CODER_FAST,
    MODEL_CODER_PRO,
    MODEL_REASONING,
    MODEL_ANALYSIS,
    MODEL_CHAT_FAST,
]

_cached_models: dict[str, Any] = {
    "timestamp": 0.0,
    "models": [],
}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _extract_model_names(tags: Any) -> list[str]:
    models: list[str] = []
    if isinstance(tags, dict):
        if "models" in tags and isinstance(tags["models"], list):
            for item in tags["models"]:
                if isinstance(item, dict):
                    candidate = item.get("name") or item.get("model")
                    if isinstance(candidate, str):
                        models.append(candidate)
                elif isinstance(item, str):
                    models.append(item)
        else:
            for value in tags.values():
                if isinstance(value, str) and ":" in value:
                    models.append(value)
    elif isinstance(tags, list):
        for item in tags:
            if isinstance(item, dict):
                candidate = item.get("name") or item.get("model")
                if isinstance(candidate, str):
                    models.append(candidate)
            elif isinstance(item, str):
                models.append(item)
    return list(dict.fromkeys(models))


def get_available_models(timeout: int | None = None) -> list[str]:
    now = time.time()
    if _cached_models["models"] and now - _cached_models["timestamp"] < CACHE_TTL_SECONDS:
        return _cached_models["models"]

    timeout = timeout or Config.OLLAMA_HEALTH_TIMEOUT
    tags_url = urljoin(get_ollama_base_url(), "/api/tags")
    try:
        response = requests.get(tags_url, timeout=timeout)
        response.raise_for_status()
        tags = response.json()
        models = _extract_model_names(tags)
        _cached_models["models"] = models
        _cached_models["timestamp"] = now
        log.info("[ROUTER] Modelos detectados: %s", models)
        return models
    except Exception as exc:
        log.warning("[ROUTER] No se pudo consultar /api/tags: %s", exc)
        return []


def _match_intent(normalized: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in normalized for keyword in keywords)


def _select_agent_key(user_text: str) -> str:
    normalized = _normalize_text(user_text)
    if _match_intent(normalized, INTENT_KEYWORDS["greeting"]):
        return "chat_fast"
    if _match_intent(normalized, INTENT_KEYWORDS["analysis"]):
        return "analysis"
    if _match_intent(normalized, INTENT_KEYWORDS["reasoning"]):
        return "reasoning"
    if any(term in normalized for term in ADVANCED_PROGRAMMING_TERMS):
        return "coder_pro"
    if _match_intent(normalized, INTENT_KEYWORDS["coder_pro"]):
        return "coder_pro"
    if _match_intent(normalized, INTENT_KEYWORDS["coder_fast"]):
        return "coder_fast"
    # Priorizar frontend/moderno cuando se habla de diseño web
    if any(term in normalized for term in ("sitio", "sitio web", "pagina", "página", "landing", "dashboard", "portal", "interfaz", "ui", "ux")):
        return "coder_pro"
    if any(term in normalized for term in ("comando", "tarea", "administrar", "administración", "windows", "abrir", "cerrar", "reiniciar", "volumen")):
        return "chat_fast"
    return "chat_fast"


def _resolve_model_name(requested_model: str, available_models: list[str]) -> str:
    if requested_model in available_models:
        return requested_model
    if not available_models:
        return requested_model

    prefix = requested_model.split(":")[0] if ":" in requested_model else requested_model
    family = [model for model in available_models if model.startswith(prefix)]
    if family:
        return family[0]

    for fallback in FALLBACK_ORDER:
        if fallback in available_models:
            return fallback
    return available_models[0]


def route_model(user_text: str) -> tuple[str, str, str]:
    """Devuelve el modelo, el nombre del agente y el prompt especializado."""
    agent_key = _select_agent_key(user_text)
    profile = AGENT_PROFILES.get(agent_key, AGENT_PROFILES[DEFAULT_AGENT])
    requested_model = profile["model"]
    available_models = get_available_models()
    selected_model = _resolve_model_name(requested_model, available_models)

    if selected_model != requested_model:
        log.warning("[ROUTER] Modelo %s no disponible. Usando fallback: %s", requested_model, selected_model)

    return selected_model, profile["name"], profile["prompt"]
