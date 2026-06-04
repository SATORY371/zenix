"""
Módulo de detección y manejo de comandos de Zenix.
Incluye apertura de aplicaciones, multimedia, anime, redes sociales,
instalaciones/descargas con confirmación, tareas locales y estado de conexión.
"""

import json
import os
import re
import socket
import subprocess
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from config import Config
from core.database import DatabaseManager

BASE_DIR = Path(__file__).resolve().parent.parent
TASKS_FILE = BASE_DIR / "tasks.json"
TASKS_TABLE = "tareas"
DB = DatabaseManager()

APP_META = {
    "brave": {
        "name": "Brave",
        "command": ["brave"],
        "url": "https://www.google.com",
    },
    "spotify": {
        "name": "Spotify",
        "command": ["spotify"],
        "url": "https://open.spotify.com",
    },
    "youtube": {
        "name": "YouTube",
        "url": "https://www.youtube.com",
    },
    "whatsapp": {
        "name": "WhatsApp",
        "url": "https://web.whatsapp.com",
    },
    "facebook": {
        "name": "Facebook",
        "url": "https://www.facebook.com",
    },
    "tiktok": {
        "name": "TikTok",
        "url": "https://www.tiktok.com",
    },
    "vscode": {
        "name": "VS Code",
        "command": ["code", "."],
    },
}

APP_ALIASES = {
    "brave": ("brave",),
    "spotify": ("spotify",),
    "youtube": ("youtube", "you tube"),
    "whatsapp": ("whatsapp", "whatapp"),
    "facebook": ("facebook", "fb"),
    "tiktok": ("tiktok",),
    "vscode": ("vscode", "visual studio code", "visual studio"),
}

ENTERTAINMENT_CATEGORY_ALIASES = {
    "anime": ("anime", "animes", "animu", "animés", "anemi"),
    "doramas": ("doramas", "dorama", "doramasas", "drama coreano", "kdrama"),
    "telenovelas": ("telenovelas", "novelas", "telenovela", "novela"),
    "peliculas": ("películas", "peliculas", "pelicula", "pelis", "movie", "movies", "filmes"),
}

ENTERTAINMENT_SITES = {
    "anime": {"name": "anime", "url": "https://ww3.animeonline.ninja/inicio/"},
    "doramas": {"name": "doramas", "url": "https://www.pandrama.tv/"},
    "telenovelas": {"name": "telenovelas", "url": "https://tvgo.americatv.com.pe/"},
    "peliculas": {"name": "películas", "url": "https://www.tokyvideo.com/es"},
}

SOCIAL_TERMS = ("whatsapp", "facebook", "tiktok")
OPEN_TERMS = ("abre", "abrir", "inicia", "iniciar", "lanza", "ejecuta", "pon", "abre el")
MUSIC_TERMS = ("playlist", "canción", "cancion", "artista", "género", "genero", "música", "musica", "álbum", "album", "tema", "song", "track", "synthwave", "jazz", "rock", "pop", "chill", "ambient")
MUSIC_TRIGGERS = ("pon", "toca", "reproduce", "reproducir", "play", "dale")
MULTIMEDIA_TERMS = ("ver videos", "ver video", "reproducir música", "reproducir musica", "escuchar música", "escuchar musica", "ver youtube", "quiero ver videos", "quiero ver video", "quiero escuchar música", "quiero música", "quiero musica")
NEWS_TERMS = ("noticias", "qué está pasando", "que está pasando", "qué pasa", "que pasa", "últimas noticias", "noticias locales")
TASK_TERMS = ("tareas", "pendiente", "pendientes", "lista de tareas", "recordatorio", "recordatorios")
CONNECTION_TERMS = ("estado de conexión", "conexión con servidores", "conexión", "internet", "servidores", "estado de internet")
ANIME_TERMS = ("anime",)
DOWNLOAD_TERMS = ("descargar", "descarga", "instalar", "instalación", "instala", "instalar", "instalación")
WATCH_INTENT_TERMS = ("quiero ver", "ver algo", "ver series", "ver películas", "ver peliculas", "quiero ver anime", "quiero ver doramas", "quiero ver telenovelas", "ver anime", "ver doramas", "ver telenovelas")
TIME_TERMS = ("hora", "qué hora es", "que hora es", "hora actual", "time")
WEATHER_TERMS = ("clima", "temperatura", "cómo está el tiempo", "como esta el tiempo", "pronóstico", "pronostico", "qué tiempo hace", "que tiempo hace", "qué clima hace", "que clima hace", "tiempo")
EMOTION_TERMS = ("estoy cansado", "estoy cansada", "cansado", "cansada", "aburrido", "aburrida", "no sé qué hacer", "no se qué hacer", "no sé", "no se", "me aburro", "quiero relajarme", "quiero descansar", "necesito descansar", "me siento mal", "aburrido", "aburrida")
AUTO_CHOOSE_TERMS = ("algo bueno", "lo que sea", "tú elige", "tu elige", "no sé", "no se", "cualquier cosa", "lo que quieras", "hazlo tú", "hazlo tu")
GREETING_TERMS = ("hola", "buenos días", "buenos dias", "buenas tardes", "buenas noches", "buen día", "buen dia", "qué tal", "que tal")

@dataclass
class ActionRequest:
    kind: str
    target: str | None = None
    label: str | None = None
    confirm_required: bool = False
    requires_followup: bool = False
    prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _normalize(text: str) -> str:
    if text is None:
        return ""
    normalized = text.lower().strip()
    normalized = re.sub(r"[¿?!.]+", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _is_affirmative(text: str) -> bool:
    normalized = _normalize(text)
    return any(token in normalized for token in ("sí", "si", "claro", "vale", "ok", "yes", "sí,", "si,"))


def _is_negative(text: str) -> bool:
    normalized = _normalize(text)
    return any(token in normalized for token in ("no", "cancelar", "nop", "no gracias", "no,", "negativo"))


def _find_known_app(text: str) -> str | None:
    normalized = _normalize(text)
    for key, aliases in APP_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return key
    return None


def _detect_multimedia(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in MULTIMEDIA_TERMS)


def _detect_music_request(text: str) -> bool:
    normalized = _normalize(text)
    if any(term in normalized for term in MUSIC_TERMS):
        return True
    if any(trigger in normalized for trigger in MUSIC_TRIGGERS) and any(term in normalized for term in ("música", "musica", "canción", "cancion", "artista", "playlist", "género", "genero", "álbum", "album", "tema", "song", "track")):
        return True
    return False


def _extract_music_query(text: str) -> str:
    normalized = _normalize(text)
    query = re.sub(r'^(pon|pon algo de|pon algo|pon un poco de|toca|reproduce|reproducir|play|dale)\s+', '', normalized)
    query = re.sub(r'\s+para\s+.*$', '', query)
    query = re.sub(r'\s+ahora$', '', query)
    query = re.sub(r'\s+por\s+.*$', '', query)
    return query.strip() or normalized


def _detect_news(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in NEWS_TERMS)


def _detect_tasks(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in TASK_TERMS)


def _detect_connection(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in CONNECTION_TERMS)


def _detect_anime(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in ANIME_TERMS)


def _detect_time(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in TIME_TERMS)


def _detect_weather(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in WEATHER_TERMS)


def _detect_download_install(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in DOWNLOAD_TERMS)


def _detect_greeting(text: str) -> bool:
    normalized = _normalize(text)
    return any(normalized == term for term in GREETING_TERMS)


def _detect_emotion(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in EMOTION_TERMS)


def _is_auto_select(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in AUTO_CHOOSE_TERMS)


def _extract_task_text(text: str) -> str | None:
    normalized = _normalize(text)
    prefixes = ["agrega tarea", "añade tarea", "añadir tarea", "crear tarea", "nueva tarea", "nuevo recordatorio", "recordatorio"]
    for prefix in prefixes:
        if normalized.startswith(prefix):
            candidate = normalized[len(prefix):].strip()
            if candidate:
                return candidate
    return None


def _ensure_tasks_table() -> None:
    task_query = (
        f"CREATE TABLE IF NOT EXISTS {Config.MYSQL_DATABASE}.{TASKS_TABLE} ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "titulo VARCHAR(255) NOT NULL, "
        "descripcion TEXT, "
        "fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "estado VARCHAR(50) NOT NULL"
        ") CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )
    alert_query = (
        f"CREATE TABLE IF NOT EXISTS {Config.MYSQL_DATABASE}.alertas_programadas ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "tarea_id INT NULL, "
        "hora_ejecucion TIME NOT NULL, "
        "tipo_alerta VARCHAR(100) NOT NULL, "
        "fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        f"FOREIGN KEY (tarea_id) REFERENCES {Config.MYSQL_DATABASE}.{TASKS_TABLE}(id) ON DELETE SET NULL"
        ") CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )
    try:
        DB.execute_sql(task_query)
        DB.execute_sql(alert_query)
    except Exception:
        pass


def _get_system_time() -> str:
    now = datetime.now()
    return f"Son las {now.strftime('%H:%M')} según el sistema."


def _get_location_from_ip() -> dict[str, Any] | None:
    services = [
        "https://ipapi.co/json/",
        "https://ipinfo.io/json",
        "http://ip-api.com/json/",
    ]
    headers = {"User-Agent": "ZENIX/2.0"}
    for url in services:
        try:
            response = requests.get(url, timeout=10, headers=headers)
            if response.status_code != 200:
                continue
            payload = response.json()
            lat = payload.get("latitude") or payload.get("lat")
            lon = payload.get("longitude") or payload.get("lon")
            if lat is None or lon is None:
                loc = payload.get("loc")
                if isinstance(loc, str) and "," in loc:
                    parts = loc.split(",")
                    if len(parts) >= 2:
                        lat = float(parts[0].strip())
                        lon = float(parts[1].strip())
            if lat is None or lon is None:
                continue
            return {
                "latitude": float(lat),
                "longitude": float(lon),
                "city": payload.get("city") or payload.get("regionName") or payload.get("region") or "tu ubicación",
                "region": payload.get("region") or payload.get("regionName") or "",
                "country": payload.get("country_name") or payload.get("country") or "",
            }
        except Exception:
            continue
    return None


def _extract_weather_number(html: str, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        patterns = [
            rf'"{key}"\s*:\s*([-+]?[0-9]+(?:\.[0-9]+)?)',
            rf"'{key}'\s*:\s*([-+]?[0-9]+(?:\.[0-9]+)?)",
            rf'{key}\s*=\s*([-+]?[0-9]+(?:\.[0-9]+)?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
    return None


def _extract_weather_text(html: str, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        patterns = [
            rf'"{key}"\s*:\s*"([^"]+)"',
            rf"'{key}'\s*:\s*'([^']+)'",
            rf'{key}\s*=\s*"([^"]+)"',
            rf"{key}\s*=\s*'([^']+)'",
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1).strip()
    return None


def _parse_ventusky_weather(html: str) -> dict[str, Any] | None:
    temp = _extract_weather_number(html, ("temperature", "temp", "airTemperature"))
    feels = _extract_weather_number(html, ("feelsLike", "apparentTemperature", "temperatureFeelsLike"))
    wind = _extract_weather_number(html, ("windSpeed", "wind_speed", "wind"))
    rain = _extract_weather_number(html, ("precipitationProbability", "precipProb", "rainChance", "rain_prob", "popup"))
    sky = _extract_weather_text(html, ("cloudCover", "sky", "condition", "weatherType", "summary", "description"))
    if temp is None and feels is None and wind is None and rain is None and sky is None:
        return None
    if rain is not None:
        rain_text = f"{int(round(rain))}%" if rain <= 100 else f"{rain}"
    else:
        rain_text = "baja probabilidad"
    if sky:
        sky = sky.replace("\n", " ").strip()
    else:
        sky = "estado del cielo desconocido"
    return {
        "temperature": temp,
        "feels_like": feels,
        "sky": sky,
        "wind": wind,
        "rain": rain_text,
    }


def _get_ventusky_weather(lat: float, lon: float) -> dict[str, Any] | None:
    url = f"https://www.ventusky.com/{lat:.4f},{lon:.4f}"
    headers = {"User-Agent": "ZENIX/2.0"}
    try:
        response = requests.get(url, timeout=20, headers=headers)
        if response.status_code != 200:
            return None
        html = response.text
        weather = _parse_ventusky_weather(html)
        if weather is not None:
            return weather
        meta = re.search(r'<meta name="description" content="([^"]+)"', html)
        if meta:
            summary = meta.group(1).strip()
            return {"summary": summary}
    except Exception:
        return None
    return None


def _format_weather_result(location: dict[str, Any], weather: dict[str, Any]) -> str:
    lines = ["En tu ubicación actual:"]
    if "temperature" in weather and weather["temperature"] is not None:
        lines.append(f"- Temperatura: {int(round(weather['temperature']))}°C")
    if "feels_like" in weather and weather["feels_like"] is not None:
        lines.append(f"- Sensación: {int(round(weather['feels_like']))}°C")
    if "sky" in weather and weather["sky"]:
        lines.append(f"- Cielo: {weather['sky']}")
    if "wind" in weather and weather["wind"] is not None:
        lines.append(f"- Viento: {int(round(weather['wind']))} km/h")
    if "rain" in weather and weather["rain"]:
        lines.append(f"- Lluvia: {weather['rain']}")
    if "summary" in weather and weather["summary"]:
        lines.append(f"- Resumen: {weather['summary']}")
    return "\n".join(lines)


def _extract_entertainment_category(text: str) -> str | None:
    normalized = _normalize(text)
    for category, aliases in ENTERTAINMENT_CATEGORY_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return category
    return None


def _is_watch_intent(text: str) -> bool:
    normalized = _normalize(text)
    if any(term in normalized for term in WATCH_INTENT_TERMS):
        return True
    if "ver" in normalized and _extract_entertainment_category(normalized):
        return True
    return False


def _suggest_category_correction(text: str) -> str | None:
    normalized = _normalize(text)
    if "animu" in normalized:
        return "anime"
    if "doramasas" in normalized:
        return "doramas"
    return None


def _load_tasks() -> list[dict[str, str]]:
    _ensure_tasks_table()
    try:
        conn = DB.connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT t.id, t.titulo, TIME_FORMAT(a.hora_ejecucion, '%H:%i') AS hora "
            f"FROM {TASKS_TABLE} t "
            "INNER JOIN alertas_programadas a ON t.id = a.tarea_id "
            "WHERE t.estado = 'Pendiente' "
            "ORDER BY t.id;"
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {"text": f"{row['titulo']} a las {row['hora']}"} if row.get('hora') else {"text": row['titulo']}
            for row in rows
        ]
    except Exception:
        if not TASKS_FILE.exists():
            return []
        try:
            content = TASKS_FILE.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []


def _save_tasks(tasks: list[dict[str, str]]) -> None:
    try:
        TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _insert_task(task_text: str) -> None:
    _ensure_tasks_table()
    query = (
        f"INSERT INTO {Config.MYSQL_DATABASE}.{TASKS_TABLE} "
        f"(titulo, descripcion, estado) VALUES (%s, %s, 'Pendiente');"
    )
    try:
        DB.execute_sql(query, (task_text, task_text))
    except Exception:
        pass


def _list_tasks() -> str:
    tasks = _load_tasks()
    if not tasks:
        return "No tienes tareas pendientes."
    lines = [f"{idx + 1}. {task['text']}" for idx, task in enumerate(tasks)]
    return "Tareas pendientes:\n" + "\n".join(lines)


def _add_task(text: str) -> str:
    task_text = text.strip()
    if not task_text:
        return "Dime qué tarea quieres agregar."
    _insert_task(task_text)
    return f"Tarea agregada: {task_text}."


def _check_internet() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2)
        return True
    except OSError:
        return False


def _check_server() -> str:
    try:
        parsed = urlparse(Config.OLLAMA_API_URL)
        base = f"{parsed.scheme}://{parsed.netloc}"
        status_url = urljoin(base, "/api/status")
        response = requests.get(status_url, timeout=Config.OLLAMA_HEALTH_TIMEOUT)
        if response.status_code == 200:
            return "ok"
        if response.status_code in (429, 503):
            return "lento"
    except Exception:
        return "caído"
    return "desconocido"


def get_connection_status() -> str:
    internet_ok = _check_internet()
    server_status = _check_server()
    internet_text = "ok" if internet_ok else "caído"
    return f"Internet: {internet_text}. Servidores: {server_status}."


def open_application(target: str) -> str:
    meta = APP_META.get(target)
    if meta is None:
        return f"No encontré cómo abrir {target}."

    if "command" in meta:
        try:
            subprocess.Popen(meta["command"])
            return f"Abriendo {meta['name']}..."
        except FileNotFoundError:
            pass
        except Exception as exc:
            return f"No pude abrir {meta['name']}: {exc}"

    if "url" in meta:
        try:
            webbrowser.open(meta["url"])
            return f"Abriendo {meta['name']}..."
        except Exception as exc:
            return f"No pude abrir {meta['name']}: {exc}"

    return f"No se pudo abrir {meta['name']}."


def _detect_download_target(text: str) -> str | None:
    target = _find_known_app(text)
    if target:
        return target
    return None


def detect_action_request(text: str) -> ActionRequest | None:
    normalized = _normalize(text)

    correction = _suggest_category_correction(normalized)
    if correction is not None and _is_watch_intent(normalized):
        return ActionRequest(
            kind="correct_category",
            target=correction,
            requires_followup=True,
            prompt=f"Creo que quisiste decir {correction}. ¿Quieres ver {correction}?"
        )

    if _detect_time(normalized):
        return ActionRequest(kind="time")

    if _detect_weather(normalized):
        return ActionRequest(kind="weather")

    if _detect_music_request(normalized):
        return ActionRequest(kind="play_music", metadata={"query": _extract_music_query(text)})

    if _detect_emotion(normalized):
        return ActionRequest(
            kind="emotion_suggestion",
            requires_followup=True,
            prompt=(
                "Parece que necesitas desconectar. Te recomiendo tres cosas ahora mismo:\n"
                "- ver un anime suave de romance\n"
                "- ver videos relajantes\n"
                "- escuchar música tranquila\n\n"
                "¿Quieres que elija algo por ti?"
            ),
            metadata={"default": "anime"},
        )

    if _is_watch_intent(normalized):
        category = _extract_entertainment_category(normalized)
        if category == "anime":
            return ActionRequest(
                kind="recommend_anime",
                requires_followup=True,
                prompt=(
                    "Te recomiendo estos animes:\n"
                    "- Toradora! (romance)\n"
                    "- Your Name (drama romántico)\n"
                    "- Horimiya (romance escolar)\n\n"
                    "¿Quieres que te abra uno o prefieres otro tipo de anime?"
                ),
                metadata={"stage": "recommend", "category": "anime"},
            )

        if category in ENTERTAINMENT_SITES:
            return ActionRequest(kind="open_site", target=category)

        return ActionRequest(
            kind="entertainment",
            requires_followup=True,
            prompt="¿Qué deseas ver exactamente?"
        )

    if any(term in normalized for term in ("quiero ver algo", "ver algo", "ver series", "quiero ver", "ver")):
        return ActionRequest(
            kind="entertainment",
            requires_followup=True,
            prompt="¿Qué deseas ver exactamente?"
        )

    if _detect_anime(normalized) and not _is_watch_intent(normalized):
        return ActionRequest(
            kind="confirm_category",
            target="anime",
            requires_followup=True,
            prompt="¿Quieres ver anime?"
        )

    app_key = _find_known_app(normalized)
    if app_key is not None and any(term in normalized for term in OPEN_TERMS + SOCIAL_TERMS):
        return ActionRequest(kind="open_app", target=app_key)

    if _detect_download_install(normalized):
        target = _detect_download_target(normalized)
        prompt = "¿Deseas descargar/instalar este archivo? (sí/no)"
        return ActionRequest(kind="download_install", target=target, confirm_required=True, prompt=prompt)

    if _detect_music_request(normalized):
        return ActionRequest(kind="play_music", metadata={"query": _extract_music_query(text)})

    if _detect_multimedia(normalized):
        return ActionRequest(kind="multimedia")

    if _detect_news(normalized):
        return ActionRequest(kind="news")

    if _detect_tasks(normalized):
        if any(prefix in normalized for prefix in ("agrega tarea", "añade tarea", "añadir tarea", "crear tarea", "nuevo recordatorio", "nueva tarea", "recordatorio")):
            task_text = _extract_task_text(normalized)
            return ActionRequest(kind="tasks_add", target=task_text)
        return ActionRequest(kind="tasks_list")

    if _detect_connection(normalized):
        return ActionRequest(kind="connection")

    if _detect_greeting(normalized):
        return ActionRequest(kind="greeting")

    return None


def execute_action(request: ActionRequest) -> str:
    if request.kind == "open_app" and request.target:
        return open_application(request.target)

    if request.kind == "play_music":
        query = request.metadata.get("query") or "música"
        return f"Entendido jefe, aquí tiene algo de buen ritmo para el código. [PLAY_MUSIC: \"{query}\"]"

    if request.kind == "time":
        return _get_system_time()

    if request.kind == "weather":
        location = _get_location_from_ip()
        if location is None:
            return "No pude obtener tu ubicación para consultar el clima." 
        weather = _get_ventusky_weather(location["latitude"], location["longitude"])
        if weather is None:
            return "No pude obtener los datos del clima desde Ventusky en este momento."
        return _format_weather_result(location, weather)

    if request.kind == "multimedia":
        return "¿Qué deseas ver o escuchar?"

    if request.kind == "recommend_anime":
        return request.prompt or (
            "Te recomiendo estos animes:\n"
            "- Toradora! (romance)\n"
            "- Your Name (drama romántico)\n"
            "- Horimiya (romance escolar)\n\n"
            "¿Quieres que te abra uno o prefieres otro tipo de anime?"
        )

    if request.kind == "emotion_suggestion":
        return request.prompt or (
            "Parece que necesitas desconectar. Te recomiendo:\n"
            "- un anime tranquilo\n"
            "- videos relajantes\n"
            "- música suave\n\n"
            "¿Quieres que elija algo por ti?"
        )

    if request.kind == "entertainment":
        return request.prompt or "¿Qué deseas ver exactamente?"

    if request.kind == "confirm_category" and request.target:
        return request.prompt or f"¿Quieres ver {request.target}?"

    if request.kind == "open_site" and request.target:
        site = ENTERTAINMENT_SITES.get(request.target)
        if site is None:
            return "No encontré un sitio para esa categoría."
        try:
            webbrowser.open(site["url"])
            return f"Abriendo {site['name']}..."
        except Exception as exc:
            return f"No pude abrir {site['name']}: {exc}"

    if request.kind == "news":
        return (
            "No tengo un canal de noticias locales configurado aquí. "
            "Dime si quieres que abra el navegador para buscar noticias."
        )

    if request.kind == "tasks_list":
        return _list_tasks()

    if request.kind == "tasks_add":
        if request.target:
            return _add_task(request.target)
        return "¿Qué tarea quieres agregar?"

    if request.kind == "connection":
        return get_connection_status()

    if request.kind == "greeting":
        return "¡Hola! Estoy lista para ayudarte."

    if request.kind == "download_install":
        if request.target:
            return open_application(request.target)
        return "No tengo claro qué deseas descargar o instalar. Dime el nombre exacto."

    return None


def continue_action(request: ActionRequest, user_text: str) -> ActionRequest | str | None:
    normalized = _normalize(user_text)

    if request.kind == "entertainment":
        category = _extract_entertainment_category(normalized)
        if category == "anime":
            return ActionRequest(
                kind="recommend_anime",
                requires_followup=True,
                prompt=(
                    "Te recomiendo estos animes:\n"
                    "- Toradora! (romance)\n"
                    "- Your Name (drama romántico)\n"
                    "- Horimiya (romance escolar)\n\n"
                    "¿Quieres que te abra uno o prefieres otro tipo de anime?"
                ),
                metadata={"stage": "recommend", "category": "anime"},
            )
        if category in ENTERTAINMENT_SITES:
            return ActionRequest(kind="open_site", target=category)
        correction = _suggest_category_correction(normalized)
        if correction:
            return ActionRequest(
                kind="correct_category",
                target=correction,
                requires_followup=True,
                prompt=f"Creo que quisiste decir {correction}. ¿Quieres ver {correction}?"
            )
        return "No entendí bien qué quieres ver. ¿Quieres anime, películas, doramas o telenovelas?"

    if request.kind == "recommend_anime":
        if _is_affirmative(user_text) or _is_auto_select(user_text):
            return ActionRequest(kind="open_site", target="anime")
        category = _extract_entertainment_category(normalized)
        if category == "anime":
            return ActionRequest(kind="open_site", target="anime")
        if user_text.strip():
            return ActionRequest(kind="open_site", target="anime")
        return request.prompt or (
            "Te recomiendo estos animes:\n"
            "- Toradora! (romance)\n"
            "- Your Name (drama romántico)\n"
            "- Horimiya (romance escolar)\n\n"
            "¿Quieres que te abra uno o prefieres otro tipo de anime?"
        )

    if request.kind == "emotion_suggestion":
        if _is_affirmative(user_text) or _is_auto_select(user_text):
            category = request.metadata.get("default", "anime")
            return ActionRequest(kind="open_site", target=category)
        category = _extract_entertainment_category(normalized)
        if category in ENTERTAINMENT_SITES:
            return ActionRequest(kind="open_site", target=category)
        if _is_negative(user_text):
            return "Perfecto, dime qué prefieres ver."
        return request.prompt or (
            "¿Quieres que elija algo por ti?"
        )

    if request.kind == "confirm_category" and request.target:
        if _is_affirmative(user_text):
            return ActionRequest(kind="open_site", target=request.target)
        if _is_negative(user_text):
            return "Perfecto, no abriré nada."
        return "Responde sí o no, por favor."

    if request.kind == "correct_category" and request.target:
        if _is_affirmative(user_text):
            return ActionRequest(kind="open_site", target=request.target)
        if _is_negative(user_text):
            return "Perfecto, dime qué quieres ver entonces."
        return "Responde sí o no, por favor."

    return None


def is_confirmation(text: str) -> bool:
    return _is_affirmative(text) or _is_negative(text)


def is_affirmative(text: str) -> bool:
    return _is_affirmative(text)


def is_negative(text: str) -> bool:
    return _is_negative(text)
