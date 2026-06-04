"""
╔══════════════════════════════════════════════════════════════════╗
║         ZENIX v2.0 — Módulo de Interfaz Gráfica (GUI)           ║
║   Fox Girl Cyberpunk Kawaii · Tkinter · Ollama · qwen3.5:4b      ║
╚══════════════════════════════════════════════════════════════════╝
"""

import tkinter as tk
from tkinter import scrolledtext, font
import threading
import time
import os
import sys
import logging
from concurrent.futures import ThreadPoolExecutor
import concurrent.futures as cf
from pathlib import Path

# Asegurar que el directorio raíz esté en el path para importar config y core
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import Config, get_system_prompt_path
from core.logging_setup import setup_logging
from core.assistant import ask_ollama, preload_ollama_model
from core.memory_manager import MemoryManager
from core.model_router import route_model
from core.resource_downloader import download_image
from core.artifacts import (
    ArtifactRequest,
    code_prompt,
    describe_paths,
    detect_artifact_request,
    document_prompt,
    is_ambiguous_artifact_request,
    parse_languages,
    save_code_artifact,
    save_document_artifacts,
)
from core.command_handler import (
    ActionRequest,
    detect_action_request,
    execute_action,
    continue_action,
    is_affirmative,
    is_negative,
)
from core.system_monitor import SystemMonitor
from core.speech import (
    check_input_device, check_output_device, init_speech, is_speaking,
    is_tts_ready, listen_microphone, listen_with_vad,
    get_input_devices, get_output_devices,
    set_output_device, speak, wait_for_tts_ready,
)
from core.settings_manager import get_settings

log = logging.getLogger("zenix.gui")

# Inicializar logging centralizado con UTF-8
# CORREGIDO: Usar setup_logging() en lugar de basicConfig
setup_logging()

# ── Directorios ──────────────────────────────────────────────────
AVATAR_DIR = ROOT_DIR / "assets" / "avatar"

# ── Paleta de colores cyberpunk ───────────────────────────────────
COLORS = {
    "bg":          "#080B14",   # Fondo principal casi negro
    "panel":       "#0D1117",   # Paneles secundarios
    "panel_light": "#161B27",   # Paneles con un poco de luz
    "border":      "#1E2D45",   # Bordes sutiles
    "cyan":        "#00F5FF",   # Cyan neón principal
    "cyan_dim":    "#0A7E8A",   # Cyan apagado
    "magenta":     "#FF2D78",   # Magenta/Rosa neón (Zenix)
    "magenta_dim": "#7A1440",   # Magenta apagado
    "purple":      "#BD00FF",   # Púrpura neón (acentos)
    "yellow":      "#FFD700",   # Amarillo dorado (sistema)
    "green":       "#00FF88",   # Verde neón (estado)
    "text":        "#C8D6E5",   # Texto general claro
    "text_dim":    "#5A7080",   # Texto secundario apagado
    "white":       "#F0F4FF",   # Blanco suave
    "user_bubble": "#0A1E35",   # Fondo burbuja usuario
    "zen_bubble":  "#1A0825",   # Fondo burbuja Zenix
}

# ── Mapeo de situaciones a imágenes de avatar ────────────────────
# Las claves son estados internos; los valores son nombres de archivo
AVATAR_STATES = {
    "idle":        "ZENIX 1.png",
    "happy":       "Cara feliz emocionada.png",
    "thinking":    "Cara pensativa.png",
    "speaking_1":  "Boca ligeramente abierta.png",
    "speaking_2":  "Boca abierta media.png",
    "speaking_3":  "Boca más abierta.png",
    "speaking_4":  "Sonriendo mientras habla.png",
    "o_mouth":     "Boca en forma de O.png",
    "surprised":   "Cara de sorpresa.png",
    "shocked":     "sorpresa al maximo.png",
    "shy":         "Cara de vergüenza sonrojada.png",
    "serious":     "Cara seria profesional.png",
    "tsundere":    "Cara regañona tsundere.png",
    "laughing":    "risa.png",
}

# Secuencia de frames para la animación de "habla"
SPEAKING_FRAMES = [
    "speaking_1", "speaking_2", "speaking_3", "speaking_4",
    "speaking_2", "speaking_1", "o_mouth", "speaking_2",
]

# ─────────────────────────────────────────────────────────────────
class ZenixGUI:
    """Ventana principal de Zenix v2 con avatar, chat y controles."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self._configure_window()
        self._pending_command = None
        # ── Estado de la app ──────────────────────────────────────────
        self._is_speaking   = False
        self._is_listening  = False
        self._continuous_mode = False     # Modo manos libres
        self._continuous_thread: threading.Thread | None = None
        self._avatar_images: dict[str, tk.PhotoImage] = {}
        self._chat_history: list[dict] = []  # Historial completo para Ollama
        self._last_response: str = ""
        self._pending_artifact: ArtifactRequest | None = None

        # Cargar configuración persistente del usuario
        self._settings = get_settings()
        self._audio_cfg = self._settings.get_audio()
        self._memory_manager = MemoryManager()
        self._system_monitor = SystemMonitor()
        # Executor para llamadas a Ollama para evitar bloquear la UI
        self._executor = ThreadPoolExecutor(max_workers=4)

        # Cargar fuentes y UI
        self._define_fonts()
        self._build_ui()
        self._log_boot("Iniciando UI...")
        self._set_avatar("happy")

        # Aplicar configuración de audio guardada
        self._apply_audio_settings()

        # Inicializar TTS en hilo separado para no bloquear
        threading.Thread(target=self._init_tts, daemon=True).start()

        # Mensaje de bienvenida
        self._post_welcome()

        # Cargar avatar de forma asíncrona para no bloquear el arranque
        self._append_sys("[BOOT] Verificando Avatar...")
        self.root.after(100, self._load_all_avatars)

        # Comprobar Ollama y audio sin bloquear la interfaz
        self._start_system_checks()

    # ── Configuración de ventana ──────────────────────────────────

    def _configure_window(self):
        self.root.title("Zenix — Tu Asistente Fox Girl  ✦  v2.0")
        self.root.geometry("1000x680")
        self.root.minsize(800, 560)
        self.root.configure(bg=COLORS["bg"])
        # Icono opcional (no falla si no existe)
        icon_path = AVATAR_DIR / "ZENIX 1.png"
        if icon_path.exists():
            try:
                from PIL import Image, ImageTk
                icon = ImageTk.PhotoImage(Image.open(icon_path).resize((32, 32)))
                self.root.iconphoto(True, icon)
            except Exception:
                pass

    def _define_fonts(self):
        self.font_title   = font.Font(family="Consolas", size=15, weight="bold")
        self.font_header  = font.Font(family="Consolas", size=11, weight="bold")
        self.font_chat    = font.Font(family="Consolas", size=10)
        self.font_name    = font.Font(family="Consolas", size=10, weight="bold")
        self.font_input   = font.Font(family="Consolas", size=11)
        self.font_small   = font.Font(family="Consolas", size=9)
        self.font_btn     = font.Font(family="Consolas", size=10, weight="bold")

    # ── Construcción de la UI ─────────────────────────────────────

    def _build_ui(self):
        """Ensambla todos los widgets de la ventana."""
        self._build_topbar()
        self._build_body()
        self._build_bottombar()

    def _build_topbar(self):
        """Barra superior con título y estado de sistema."""
        bar = tk.Frame(self.root, bg=COLORS["panel"], height=48)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)

        # Indicador de "conexión"
        tk.Label(bar, text="◉", fg=COLORS["green"], bg=COLORS["panel"],
                 font=font.Font(size=13)).pack(side=tk.LEFT, padx=(18, 4), pady=12)
        tk.Label(bar, text="SISTEMA EN LÍNEA", fg=COLORS["green"], bg=COLORS["panel"],
                 font=self.font_small).pack(side=tk.LEFT, pady=12)

        # Título central
        tk.Label(bar, text="ZENIX_OS  //  v2.0  ·  ASSISTANT FOX GIRL",
                 fg=COLORS["cyan"], bg=COLORS["panel"],
                 font=self.font_title).pack(side=tk.LEFT, expand=True)

        # ── Botón de configuración de audio (NUEVO) ───────────────────
        self._audio_cfg_btn = tk.Button(
            bar, text="⚙ AUDIO",
            font=self.font_small,
            bg=COLORS["panel_light"], fg=COLORS["purple"],
            activebackground=COLORS["purple"], activeforeground=COLORS["bg"],
            relief=tk.FLAT, bd=0, cursor="hand2",
            command=self._open_audio_config,
        )
        self._audio_cfg_btn.pack(side=tk.RIGHT, padx=(0, 8), pady=10, ipady=3, ipadx=6)
        self._add_hover(self._audio_cfg_btn,
                        COLORS["purple"], COLORS["panel_light"],
                        COLORS["bg"], COLORS["purple"])

        # Modelo activo
        tk.Label(bar, text=f"⚡ {Config.MODEL}", fg=COLORS["purple"],
                 bg=COLORS["panel"], font=self.font_small).pack(side=tk.RIGHT, padx=8)

        self._memory_status_var = tk.StringVar(value="[MEMORIA] sin datos")
        tk.Label(bar, textvariable=self._memory_status_var, fg=COLORS["text_dim"],
                 bg=COLORS["panel"], font=self.font_small).pack(side=tk.RIGHT, padx=8)

        self._system_metrics_var = tk.StringVar(value="CPU -- · RAM -- · GPU --")
        tk.Label(bar, textvariable=self._system_metrics_var, fg=COLORS["text_dim"],
                 bg=COLORS["panel"], font=self.font_small).pack(side=tk.RIGHT, padx=8)

    def _build_body(self):
        """Zona central: panel de avatar + panel de chat."""
        body = tk.Frame(self.root, bg=COLORS["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(10, 0))

        # ─── Panel Avatar (izquierda) ─────────────────────────────
        left = tk.Frame(body, bg=COLORS["panel"], width=300,
                        highlightbackground=COLORS["border"], highlightthickness=1)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))
        left.pack_propagate(False)

        # Etiqueta del panel
        tk.Label(left, text=">_ VISUAL_LINK // AVATAR",
                 fg=COLORS["cyan_dim"], bg=COLORS["panel"],
                 font=self.font_small).pack(pady=(10, 0))

        # Canvas para avatar (imagen centrada)
        self._avatar_canvas = tk.Label(left, bg=COLORS["panel"],
                                       relief=tk.FLAT, bd=0)
        self._avatar_canvas.pack(expand=True, fill=tk.BOTH, padx=8, pady=8)

        # Nombre y estado
        tk.Label(left, text="ZENIX  2.0", fg=COLORS["magenta"],
                 bg=COLORS["panel"], font=self.font_header).pack(pady=(0, 2))
        self._status_var = tk.StringVar(value="[ ESPERANDO ORDEN ]")
        tk.Label(left, textvariable=self._status_var,
                 fg=COLORS["cyan_dim"], bg=COLORS["panel"],
                 font=self.font_small).pack(pady=(0, 4))

        # ── Indicadores de audio (NUEVO) ──────────────────────────────
        audio_indicators = tk.Frame(left, bg=COLORS["panel"])
        audio_indicators.pack(pady=(0, 4))

        self._mic_indicator = tk.Label(
            audio_indicators, text="🎙 MIC",
            font=self.font_small, bg=COLORS["panel"], fg=COLORS["text_dim"])
        self._mic_indicator.pack(side=tk.LEFT, padx=5)

        self._spk_indicator = tk.Label(
            audio_indicators, text="🔊 SPK",
            font=self.font_small, bg=COLORS["panel"], fg=COLORS["text_dim"])
        self._spk_indicator.pack(side=tk.LEFT, padx=5)

        # Botón modo manos libres
        self._continuous_btn = tk.Button(
            left, text="🔄 Manos Libres: OFF",
            font=self.font_small,
            bg=COLORS["panel_light"], fg=COLORS["text_dim"],
            activebackground=COLORS["green"], activeforeground=COLORS["bg"],
            relief=tk.FLAT, bd=0, cursor="hand2",
            command=self._toggle_continuous_mode,
        )
        self._continuous_btn.pack(pady=(0, 4), ipadx=4, ipady=2)

        # Separador decorativo
        tk.Frame(left, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=10)

        # Chips de estado en la parte inferior del panel
        mood_frame = tk.Frame(left, bg=COLORS["panel"])
        mood_frame.pack(pady=8)
        for emoji, label in [("🦊", "Fox Mode"), ("⚡", "Activa"), ("💜", "Leal")]:
            chip = tk.Frame(mood_frame, bg=COLORS["panel_light"],
                            highlightbackground=COLORS["border"], highlightthickness=1)
            chip.pack(side=tk.LEFT, padx=4, pady=2, ipadx=5, ipady=2)
            tk.Label(chip, text=f"{emoji} {label}",
                     fg=COLORS["text_dim"], bg=COLORS["panel_light"],
                     font=self.font_small).pack()

        # ─── Panel Chat (derecha) ──────────────────────────────────
        right = tk.Frame(body, bg=COLORS["panel"],
                         highlightbackground=COLORS["border"], highlightthickness=1)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        tk.Label(right, text=">_ CHAT_STREAM // HISTORIAL",
                 fg=COLORS["cyan_dim"], bg=COLORS["panel"],
                 font=self.font_small).pack(anchor=tk.W, padx=12, pady=(10, 2))

        # Área de scroll del chat
        self._chat_area = scrolledtext.ScrolledText(
            right,
            wrap=tk.WORD,
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=self.font_chat,
            insertbackground=COLORS["cyan"],
            padx=14, pady=10,
            relief=tk.FLAT,
            state=tk.DISABLED,
            cursor="arrow",
        )
        self._chat_area.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        # Tags de color en el área de chat
        self._chat_area.tag_config("user_name",  foreground=COLORS["cyan"],    font=self.font_name)
        self._chat_area.tag_config("zenix_name", foreground=COLORS["magenta"], font=self.font_name)
        self._chat_area.tag_config("sys_name",   foreground=COLORS["yellow"],  font=self.font_name)
        self._chat_area.tag_config("user_text",  foreground=COLORS["white"])
        self._chat_area.tag_config("zenix_text", foreground=COLORS["text"])
        self._chat_area.tag_config("sys_text",   foreground=COLORS["text_dim"])
        self._chat_area.tag_config("divider",    foreground=COLORS["border"])

    def _build_bottombar(self):
        """Barra inferior con micrófono, campo de texto y botón enviar."""
        bar = tk.Frame(self.root, bg=COLORS["panel"],
                       highlightbackground=COLORS["border"], highlightthickness=1)
        bar.pack(fill=tk.X, side=tk.BOTTOM, padx=14, pady=(8, 12))

        # ─── Botón micrófono ──────────────────────────────────────
        self._mic_btn = tk.Button(
            bar,
            text="🎙",
            font=font.Font(size=15),
            bg=COLORS["panel_light"],
            fg=COLORS["cyan"],
            activebackground=COLORS["cyan"],
            activeforeground=COLORS["bg"],
            relief=tk.FLAT,
            bd=0,
            width=3,
            cursor="hand2",
            command=self._on_mic_click,
        )
        self._mic_btn.pack(side=tk.LEFT, padx=(10, 6), pady=8, ipady=4)
        self._add_hover(self._mic_btn, COLORS["cyan"], COLORS["panel_light"],
                        COLORS["bg"], COLORS["cyan"])

        # ─── Campo de texto ───────────────────────────────────────
        input_frame = tk.Frame(bar, bg=COLORS["border"], bd=0)
        input_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=8)

        self._input_var = tk.StringVar()
        self._input_entry = tk.Entry(
            input_frame,
            textvariable=self._input_var,
            bg=COLORS["bg"],
            fg=COLORS["cyan"],
            insertbackground=COLORS["cyan"],
            font=self.font_input,
            relief=tk.FLAT,
            bd=0,
        )
        self._input_entry.pack(fill=tk.X, ipady=10, padx=2)
        self._input_entry.bind("<Return>", lambda _e: self._on_send())
        self._input_entry.insert(0, "Escribe tu mensaje aquí...")
        self._input_entry.config(fg=COLORS["text_dim"])
        self._input_entry.bind("<FocusIn>",  self._clear_placeholder)
        self._input_entry.bind("<FocusOut>", self._restore_placeholder)

        # ─── Botón Enviar ─────────────────────────────────────────
        self._send_btn = tk.Button(
            bar,
            text="  ENVIAR ▶  ",
            font=self.font_btn,
            bg=COLORS["magenta_dim"],
            fg=COLORS["magenta"],
            activebackground=COLORS["magenta"],
            activeforeground=COLORS["bg"],
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            command=self._on_send,
        )
        self._send_btn.pack(side=tk.RIGHT, padx=(6, 10), pady=8, ipady=6, ipadx=4)
        self._add_hover(self._send_btn, COLORS["magenta"], COLORS["magenta_dim"],
                        COLORS["bg"], COLORS["magenta"])

        # Tip de teclado
        tk.Label(bar, text="↵ Enter para enviar",
                 fg=COLORS["text_dim"], bg=COLORS["panel"],
                 font=self.font_small).pack(side=tk.RIGHT, padx=4)

    # ── Avatar ───────────────────────────────────────────────────

    def _load_all_avatars(self):
        """Carga las imágenes del avatar de forma incremental para no bloquear la UI."""
        try:
            from PIL import Image, ImageTk
        except ImportError:
            self._append_sys("⚠ Instala Pillow para ver el avatar: pip install Pillow")
            return

        avatar_items = [
            (state_key, AVATAR_DIR / filename)
            for state_key, filename in AVATAR_STATES.items()
        ]
        self._avatar_load_index = 0
        self._avatar_images_temp = {}
        self._avatar_image_loader(Image, ImageTk, avatar_items)

    def _avatar_image_loader(self, Image, ImageTk, avatar_items):
        if self._avatar_load_index >= len(avatar_items):
            loaded = len(self._avatar_images_temp)
            if loaded == 0:
                self._avatar_canvas.config(
                    text="[ Sin avatar ]\nPon imágenes en\nassets/avatar/",
                    fg=COLORS["text_dim"], font=self.font_small
                )
            else:
                self._avatar_images = self._avatar_images_temp
                self._set_avatar("happy")
                log.info("[BOOT] Avatar cargado: %s imágenes", loaded)
            return

        state_key, path = avatar_items[self._avatar_load_index]
        self._avatar_load_index += 1

        if path.exists():
            try:
                img = Image.open(path)
                img.thumbnail((280, 480), Image.Resampling.LANCZOS)
                self._avatar_images_temp[state_key] = ImageTk.PhotoImage(img)
            except Exception as e:
                log.warning("[BOOT] No se pudo cargar avatar '%s': %s", path, e)

        self.root.after(10, lambda: self._avatar_image_loader(Image, ImageTk, avatar_items))

    def _set_avatar(self, state: str):
        """Cambia la imagen del avatar al estado dado de forma thread-safe."""
        def _update_avatar():
            nonlocal state
            if state not in self._avatar_images:
                state = "idle" if "idle" in self._avatar_images else (
                    next(iter(self._avatar_images), None)
                )
            if state and state in self._avatar_images:
                self._avatar_canvas.config(image=self._avatar_images[state])
        self.root.after(0, _update_avatar)

    def _animate_speaking(self):
        """Hilo de animación: alterna frames mientras Zenix habla."""
        frame_index = 0
        while self._is_speaking:
            state = SPEAKING_FRAMES[frame_index % len(SPEAKING_FRAMES)]
            self.root.after(0, self._set_avatar, state)
            frame_index += 1
            time.sleep(0.18)
        # Al terminar, volver al estado feliz/idle
        self.root.after(0, self._set_avatar, "happy")

    # ── Chat helpers ──────────────────────────────────────────────

    def _append_message(self, sender: str, text: str,
                        name_tag: str, text_tag: str):
        """Inserta un mensaje en el área de chat de forma thread-safe."""
        def _insert():
            self._chat_area.config(state=tk.NORMAL)
            self._chat_area.insert(tk.END, f"\n{sender}\n", name_tag)
            self._chat_area.insert(tk.END, f"{text}\n", text_tag)
            self._chat_area.insert(tk.END, "─" * 60 + "\n", "divider")
            self._chat_area.see(tk.END)
            self._chat_area.config(state=tk.DISABLED)
        self.root.after(0, _insert)

    def _append_user(self, text: str):
        self._append_message("[ TÚ ]", text, "user_name", "user_text")

    def _append_zenix(self, text: str):
        self._append_message("[ ZENIX ]", text, "zenix_name", "zenix_text")

    def _append_sys(self, text: str):
        log.info("[UI-SYS] %s", text)

    def _log_boot(self, message: str):
        log.info("[BOOT] %s", message)
        self._append_sys(f"[BOOT] {message}")

    def _set_status(self, text: str):
        self.root.after(0, self._status_var.set, text)

    # ── Lógica de envío de mensajes ───────────────────────────────

    def _on_send(self):
        """Manejador del botón Enviar y tecla Enter."""
        user_text = self._input_var.get().strip()
        # Ignorar si está vacío o es el placeholder
        if not user_text or user_text == "Escribe tu mensaje aquí...":
            return
        # Limpiar campo
        self._input_var.set("")
        self._input_entry.config(fg=COLORS["cyan"])

        self._append_user(user_text)

        # Comandos de salida
        if user_text.lower() in {"salir", "adiós", "adios", "exit", "cerrar"}:
            farewell = "¡Hasta luego, Amo! Vuelve pronto... *mueve la cola con tristeza* 🦊💜"
            self._append_zenix(farewell)
            threading.Thread(target=lambda: (time.sleep(2), self.root.destroy()), daemon=True).start()
            return

        # Deshabilitar controles mientras procesa
        self._lock_controls(True)
        self._set_status("[ RESPONDIENDO ]")
        self._set_avatar("happy")

        # Procesar en hilo separado para no congelar la UI
        threading.Thread(target=self._process_message, args=(user_text,), daemon=True).start()

    def _process_message(self, user_text: str):
        """Llama a Ollama, anima el avatar y muestra la respuesta."""
        self._set_avatar("thinking")

        start = time.perf_counter()
        model_name, agent_name, agent_prompt = route_model(user_text)
        self._append_sys(f"[ROUTER] Agente seleccionado: {agent_name}")
        self._append_sys(f"[MODELO] Modelo utilizado: {model_name}")
        self._memory_manager.log_interaction("user", user_text, agent_name, model_name)

        if (command_response := self._handle_command_flow(user_text)) is not None:
            response = command_response
            elapsed = time.perf_counter() - start
            metrics = {"request_ms": 0.0, "parse_ms": 0.0, "total_ms": elapsed * 1000}
        else:
            artifact_response = self._handle_artifact_flow(user_text)
            if artifact_response is not None:
                response = artifact_response
                elapsed = time.perf_counter() - start
                metrics = {"request_ms": 0.0, "parse_ms": 0.0, "total_ms": elapsed * 1000}
            elif self._is_repeat_request(user_text):
                response = self._last_response or "Todavía no tengo una respuesta anterior para leer."
                elapsed = time.perf_counter() - start
                metrics = {"request_ms": 0.0, "parse_ms": 0.0, "total_ms": elapsed * 1000}
            else:
                # Enviar petición a Ollama vía ThreadPoolExecutor con watchdog
                read_timeout = Config.OLLAMA_TIMEOUT[1] if isinstance(Config.OLLAMA_TIMEOUT, tuple) else Config.OLLAMA_TIMEOUT
                future = self._executor.submit(
                    ask_ollama,
                    user_text,
                    history=self._chat_history,
                    max_tokens=120,
                    model_name=model_name,
                    full_response=False,
                    extra_system_messages=[agent_prompt],
                )
                try:
                    response, elapsed, metrics = future.result(timeout=read_timeout + 5)
                except cf.TimeoutError:
                    future.cancel()
                    response = "El modelo tardó demasiado en responder. Intenta nuevamente o usa un modelo más ligero."
                    elapsed = 0.0
                    metrics = {"payload_ms": 0.0, "request_ms": 0.0, "parse_ms": 0.0, "total_ms": 0.0}
                    log.warning("[OLLAMA] Watchdog: petición cancelada por timeout en GUI")
                except Exception as exc:
                    response = f"Error procesando la solicitud: {exc}"
                    elapsed = 0.0
                    metrics = {"payload_ms": 0.0, "request_ms": 0.0, "parse_ms": 0.0, "total_ms": 0.0}
                    log.exception("[OLLAMA] Error al ejecutar ask_ollama en executor: %s", exc)

        # Añadir al historial de conversación
        self._chat_history.append({"role": "user", "content": user_text})
        self._chat_history.append({"role": "assistant", "content": response})
        self._memory_manager.log_interaction("assistant", response, agent_name, model_name)
        self._last_response = response

        # Limitar el historial en memoria para evitar prompts demasiado largos
        if len(self._chat_history) > 200:
            self._chat_history = self._chat_history[-200:]

        # Iniciar animación de habla + TTS en paralelo
        self._is_speaking = True
        anim_thread = threading.Thread(target=self._animate_speaking, daemon=True)
        tts_thread = threading.Thread(target=self._run_tts, args=(response,), daemon=True)
        anim_thread.start()
        tts_thread.start()

        # Mostrar texto en la UI inmediatamente (sin esperar TTS)
        # Procesar etiquetas especiales como [DOWNLOAD_IMAGE: "keywords", "file.jpg"]
        processed_response = self._handle_download_tags(response)
        self._append_zenix(processed_response)
        log.info("[IA] Respuesta generada en %.2f segundos", elapsed)
        log.info(
            "[DIAGNOSTICO] Ollama %.2fs | Parse %.2fs | Total %.2fs",
            metrics["request_ms"] / 1000,
            metrics["parse_ms"] / 1000,
            metrics["total_ms"] / 1000,
        )
        if elapsed > 5.0:
            log.warning("[IA] Respuesta lenta detectada")
        self._set_status("[ HABLANDO... ]")

        # Supervisar el fin del TTS sin bloquear el hilo de procesamiento
        self.root.after(100, lambda: self._wait_for_tts_completion(tts_thread))

    def _is_repeat_request(self, text: str) -> bool:
        normalized = text.strip().lower()
        triggers = (
            "lee la respuesta",
            "leeme la respuesta",
            "léeme la respuesta",
            "repite la respuesta",
            "vuelve a decir",
            "lee lo que dijiste",
        )
        return any(trigger in normalized for trigger in triggers)

    def _handle_artifact_flow(self, user_text: str) -> str | None:
        if self._pending_artifact is not None:
            return self._continue_artifact_flow(user_text)

        request = detect_artifact_request(user_text)
        if request is None:
            if is_ambiguous_artifact_request(user_text):
                return "¿Quieres crear un sitio web, un documento o prefieres una conversación?"
            return None

        self._pending_artifact = request
        if request.kind == "code":
            return "Claro. ¿De qué tema quieres que sea el código?"
        return "Claro. ¿De qué tema quieres que sea el documento?"

    def _handle_command_flow(self, user_text: str) -> str | None:
        if self._pending_command is not None:
            continuation = continue_action(self._pending_command, user_text)
            if isinstance(continuation, ActionRequest):
                self._pending_command = continuation if continuation.requires_followup or continuation.confirm_required else None
                return execute_action(continuation)
            self._pending_command = None
            return continuation

        request = detect_action_request(user_text)
        if request is None:
            return None

        if request.confirm_required or request.requires_followup:
            self._pending_command = request
        return execute_action(request)

    def _continue_artifact_flow(self, user_text: str) -> str:
        request = self._pending_artifact
        if request is None:
            return "No hay una solicitud de archivo pendiente."

        if request.stage == "topic":
            request.topic = user_text.strip()
            if request.kind == "code":
                if request.languages and "html" in request.languages and request.html_include_assets is None:
                    request.stage = "html_assets"
                    return "Jefe, ¿quieres que el HTML incluya CSS y JavaScript dentro del mismo archivo? Responde sí o no."
                if request.languages:
                    self._pending_artifact = None
                    return self._generate_code_artifacts(request)
                request.stage = "languages"
                return "Perfecto. ¿Qué lenguaje o lenguajes quieres usar?"
            if request.kind == "document" and "html" in request.formats and request.html_include_assets is None:
                request.stage = "html_assets"
                return "Jefe, ¿quieres que incluya estilos CSS e imágenes en el HTML? Responde sí o no."
            self._pending_artifact = None
            return self._generate_document_artifacts(request)

        if request.stage == "html_assets":
            answer = user_text.strip().lower()
            request.html_include_assets = self._is_affirmative(answer)
            if request.kind == "code":
                if request.languages:
                    self._pending_artifact = None
                    return self._generate_code_artifacts(request)
                request.stage = "languages"
                return "Perfecto. ¿Qué lenguaje o lenguajes quieres usar?"
            self._pending_artifact = None
            return self._generate_document_artifacts(request)

        if request.stage == "languages":
            request.languages = parse_languages(user_text)
            self._pending_artifact = None
            return self._generate_code_artifacts(request)

        self._pending_artifact = None
        return "La solicitud quedó incompleta. Vuelve a pedirme el archivo."

    def _generate_document_artifacts(self, request: ArtifactRequest) -> str:
        prompt = document_prompt(request.topic, request.formats)
        model_name, agent_name, agent_prompt = route_model(request.topic)
        # Ejecutar la petición a Ollama en el executor con watchdog
        read_timeout = Config.OLLAMA_TIMEOUT[1] if isinstance(Config.OLLAMA_TIMEOUT, tuple) else Config.OLLAMA_TIMEOUT
        future = self._executor.submit(
            ask_ollama,
            prompt,
            full_response=True,
            max_tokens=1400,
            model_name=model_name,
            extra_system_messages=[agent_prompt],
        )
        try:
            content, _elapsed, _metrics = future.result(timeout=read_timeout + 5)
        except cf.TimeoutError:
            future.cancel()
            content = "El modelo tardó demasiado en responder. Intenta nuevamente o usa un modelo más ligero."
            _elapsed = 0.0
            _metrics = {"payload_ms": 0.0, "request_ms": 0.0, "parse_ms": 0.0, "total_ms": 0.0}
            log.warning("[OLLAMA] Watchdog: petición cancelada por timeout en generación de documentos")
        except Exception as exc:
            content = f"Error procesando la solicitud: {exc}"
            _elapsed = 0.0
            _metrics = {"payload_ms": 0.0, "request_ms": 0.0, "parse_ms": 0.0, "total_ms": 0.0}
            log.exception("[OLLAMA] Error al ejecutar ask_ollama en executor: %s", exc)
        self._append_sys(f"[ROUTER] Agente '{agent_name}' para documento. Modelo: {model_name}")
        paths = save_document_artifacts(
            request.topic,
            request.formats,
            content,
            html_assets=request.html_include_assets is True,
        )
        return describe_paths(paths)

    def _generate_code_artifacts(self, request: ArtifactRequest) -> str:
        paths = []
        html_assets = request.html_include_assets is True
        for language in request.languages:
            normalized = language.lower().strip()
            model_name, agent_name, agent_prompt = route_model(f"{request.topic} {normalized}")
            if normalized == "html":
                if html_assets:
                    future = self._executor.submit(
                        ask_ollama,
                        code_prompt(request.topic, "html", include_assets=True),
                        full_response=True,
                        max_tokens=2200,
                        model_name=model_name,
                        extra_system_messages=[agent_prompt],
                    )
                    try:
                        html_content, _elapsed, _metrics = future.result(timeout=Config.OLLAMA_TIMEOUT[1] + 5)
                    except cf.TimeoutError:
                        future.cancel()
                        html_content = "El modelo tardó demasiado en responder. Intenta nuevamente o usa un modelo más ligero."
                        _elapsed = 0.0
                        _metrics = {"payload_ms": 0.0, "request_ms": 0.0, "parse_ms": 0.0, "total_ms": 0.0}
                        log.warning("[OLLAMA] Watchdog: petición cancelada por timeout en generación de HTML")
                    except Exception as exc:
                        html_content = f"Error procesando la solicitud: {exc}"
                        _elapsed = 0.0
                        _metrics = {"payload_ms": 0.0, "request_ms": 0.0, "parse_ms": 0.0, "total_ms": 0.0}
                        log.exception("[OLLAMA] Error al ejecutar ask_ollama en executor: %s", exc)
                    self._append_sys(f"[ROUTER] Agente '{agent_name}' para HTML. Modelo: {model_name}")
                    paths.append(save_code_artifact(request.topic, "html", html_content))
                    continue
                prompt = code_prompt(request.topic, "html")
                future = self._executor.submit(
                    ask_ollama,
                    prompt,
                    full_response=True,
                    max_tokens=1800,
                    model_name=model_name,
                    extra_system_messages=[agent_prompt],
                )
                try:
                    content, _elapsed, _metrics = future.result(timeout=Config.OLLAMA_TIMEOUT[1] + 5)
                except cf.TimeoutError:
                    future.cancel()
                    content = "El modelo tardó demasiado en responder. Intenta nuevamente o usa un modelo más ligero."
                    _elapsed = 0.0
                    _metrics = {"payload_ms": 0.0, "request_ms": 0.0, "parse_ms": 0.0, "total_ms": 0.0}
                    log.warning("[OLLAMA] Watchdog: petición cancelada por timeout en generación de HTML")
                except Exception as exc:
                    content = f"Error procesando la solicitud: {exc}"
                    _elapsed = 0.0
                    _metrics = {"payload_ms": 0.0, "request_ms": 0.0, "parse_ms": 0.0, "total_ms": 0.0}
                    log.exception("[OLLAMA] Error al ejecutar ask_ollama en executor: %s", exc)
                self._append_sys(f"[ROUTER] Agente '{agent_name}' para HTML. Modelo: {model_name}")
                paths.append(save_code_artifact(request.topic, "html", content))
                continue

            if html_assets and normalized in {"css", "javascript", "js"}:
                continue

            prompt = code_prompt(request.topic, language)
            future = self._executor.submit(
                ask_ollama,
                prompt,
                full_response=True,
                max_tokens=1800,
                model_name=model_name,
                extra_system_messages=[agent_prompt],
            )
            try:
                content, _elapsed, _metrics = future.result(timeout=Config.OLLAMA_TIMEOUT[1] + 5)
            except cf.TimeoutError:
                future.cancel()
                content = "El modelo tardó demasiado en responder. Intenta nuevamente o usa un modelo más ligero."
                _elapsed = 0.0
                _metrics = {"payload_ms": 0.0, "request_ms": 0.0, "parse_ms": 0.0, "total_ms": 0.0}
                log.warning("[OLLAMA] Watchdog: petición cancelada por timeout en generación de código")
            except Exception as exc:
                content = f"Error procesando la solicitud: {exc}"
                _elapsed = 0.0
                _metrics = {"payload_ms": 0.0, "request_ms": 0.0, "parse_ms": 0.0, "total_ms": 0.0}
                log.exception("[OLLAMA] Error al ejecutar ask_ollama en executor: %s", exc)
            self._append_sys(f"[ROUTER] Agente '{agent_name}' para lenguaje {language}. Modelo: {model_name}")
            paths.append(save_code_artifact(request.topic, language, content))
        return describe_paths(paths)

    def _is_affirmative(self, text: str) -> bool:
        return any(token in text for token in ("si", "sí", "s", "claro", "vale", "ok", "yes", "y"))

    def _run_tts(self, text: str):
        """Ejecuta text-to-speech en su propio hilo."""
        try:
            speak(text)
        except Exception as e:
            log.error("[TTS] Error reproducir texto: %s", e, exc_info=True)

    def _handle_download_tags(self, text: str) -> str:
        """Busca etiquetas [DOWNLOAD_IMAGE: "keywords", "filename"] y descarga las imágenes.

        Reemplaza la etiqueta por la ruta local `images/filename` si la descarga es exitosa.
        """
        import re

        pattern = re.compile(r"\[DOWNLOAD_IMAGE:\s*\"([^\"]+)\"\s*,\s*\"([^\"]+)\"\s*\]")
        match = pattern.search(text)
        if not match:
            return text
        keywords = match.group(1).strip()
        filename = match.group(2).strip()
        # Intentar descargar (no bloquear UI por mucho tiempo)
        try:
            local_path = download_image(keywords, filename)
            if local_path:
                new_text = pattern.sub(local_path, text, count=1)
                # Añadir nota breve al log y notificar al usuario en la UI
                self._append_sys(f"Imagen descargada: {local_path}")
                return new_text
            else:
                self._append_sys("No se pudo descargar la imagen solicitada.")
        except Exception as exc:
            log.exception("Error procesando DOWNLOAD_IMAGE: %s", exc)
            self._append_sys("Error al descargar la imagen.")
        # En caso de fallo, eliminar la etiqueta para evitar mostrarla cruda
        return pattern.sub("", text)

    # ── Micrófono ─────────────────────────────────────────────────

    def _on_mic_click(self):
        """Activa el reconocimiento de voz en un hilo separado."""
        if self._is_listening or self._is_speaking:
            return
        self._is_listening = True
        self._lock_controls(True)
        self._set_status("[ ESCUCHANDO... 🎙 ]")
        self._set_avatar("surprised")
        threading.Thread(target=self._listen_and_send, daemon=True).start()

    def _listen_and_send(self):
        """Escucha el micrófono y envía el texto reconocido."""
        try:
            cfg = self._settings.get_audio()
            device_index = cfg.get("mic_device_index")
            engine = cfg.get("stt_engine", "google")
            text = listen_microphone(device_index=device_index, engine=engine)
        except Exception as e:
            text = None
            print(f"[Mic] Error: {e}")
        finally:
            self._is_listening = False

        if text:
            self._input_var.set(text)
            self.root.after(0, self._on_send)
        else:
            self._append_sys("No se detectó voz. Prueba escribir tu mensaje. 🦊")
            self.root.after(0, self._lock_controls, False)
            self._set_status("[ ESPERANDO ORDEN ]")
            self.root.after(0, self._set_avatar, "happy")

    # ── Inicialización TTS ────────────────────────────────────────

    def _init_tts(self):
        """Inicializa el motor de voz con la configuración guardada."""
        try:
            cfg = self._settings.get_audio()
            init_speech(
                voice_name=cfg.get("tts_voice"),
                rate=cfg.get("speech_rate"),
                volume=cfg.get("speech_volume"),
            )
            set_output_device(cfg.get("output_device_index"))
            self.root.after(0, self._update_audio_indicators)
        except Exception as e:
            log.error("[TTS] No se pudo inicializar: %s", e)

    # ── Configuración de audio ────────────────────────────────────

    def _apply_audio_settings(self):
        """Aplica la configuración de audio guardada al arrancar."""
        cfg = self._settings.get_audio()
        self._audio_cfg = cfg
        self._continuous_mode = cfg.get("continuous_mode", False)
        set_output_device(cfg.get("output_device_index"))
        if self._continuous_mode:
            self.root.after(500, self._start_continuous_mode)
            self.root.after(0, self._update_continuous_btn)
        self.root.after(200, self._update_audio_indicators)

    def _open_audio_config(self):
        """Abre la ventana modal de configuración de audio."""
        from core.audio_config_window import AudioConfigWindow
        win = AudioConfigWindow(self.root)
        # Al cerrar la ventana de config, recargar ajustes
        self.root.wait_window(win)
        self._audio_cfg = self._settings.get_audio()
        self._continuous_mode = self._audio_cfg.get("continuous_mode", False)
        set_output_device(self._audio_cfg.get("output_device_index"))
        self._update_continuous_btn()
        self._update_audio_indicators()
        log.info("Configuración de audio recargada tras cierre del panel.")

    def _update_audio_indicators(self):
        """Actualiza los indicadores de micrófono y altavoz en el panel."""
        cfg = self._settings.get_audio()
        saved_mic = cfg.get("mic_device_index")
        saved_out = cfg.get("output_device_index")

        try:
            inputs = get_input_devices()
            mic_ok = len(inputs) > 0
            mic_selected_ok = (saved_mic is None) or any(d["index"] == saved_mic for d in inputs)
        except Exception:
            mic_ok = False
            mic_selected_ok = False

        try:
            outputs = get_output_devices()
            spk_ok = len(outputs) > 0
            spk_selected_ok = (saved_out is None) or any(d["index"] == saved_out for d in outputs)
        except Exception:
            spk_ok = False
            spk_selected_ok = False

        mic_color = COLORS["green"] if mic_ok and mic_selected_ok else COLORS["red"]
        spk_color = COLORS["green"] if spk_ok and spk_selected_ok else COLORS["red"]
        mic_text = "🎙 MIC ●" if mic_ok and mic_selected_ok else "🎙 MIC ✗"
        spk_text = "🔊 SPK ●" if spk_ok and spk_selected_ok else "🔊 SPK ✗"

        if hasattr(self, "_mic_indicator"):
            self._mic_indicator.config(text=mic_text, fg=mic_color)
        if hasattr(self, "_spk_indicator"):
            self._spk_indicator.config(text=spk_text, fg=spk_color)

    # ── Modo manos libres ─────────────────────────────────────────

    def _toggle_continuous_mode(self):
        """Activa o desactiva el modo de conversación continua."""
        self._continuous_mode = not self._continuous_mode
        self._settings.set_audio("continuous_mode", self._continuous_mode)
        self._update_continuous_btn()

        if self._continuous_mode:
            self._start_continuous_mode()
            self._append_sys(
                "🔄 Modo Manos Libres ACTIVADO. "
                "Habla y Zenix te escuchará automáticamente. "
                "Di 'salir' para terminar. 🦊"
            )
        else:
            self._stop_continuous_mode()
            self._append_sys("⏸ Modo Manos Libres DESACTIVADO.")

    def _update_continuous_btn(self):
        """Actualiza el texto y color del botón de modo continuo."""
        if not hasattr(self, "_continuous_btn"):
            return
        if self._continuous_mode:
            self._continuous_btn.config(
                text="🔄 Manos Libres: ON",
                bg=COLORS["green"], fg=COLORS["bg"],
            )
        else:
            self._continuous_btn.config(
                text="🔄 Manos Libres: OFF",
                bg=COLORS["panel_light"], fg=COLORS["text_dim"],
            )

    def _start_continuous_mode(self):
        """Lanza el hilo de escucha continua (VAD)."""
        if self._continuous_thread and self._continuous_thread.is_alive():
            return
        self._continuous_thread = threading.Thread(
            target=self._continuous_listen_loop, daemon=True
        )
        self._continuous_thread.start()
        log.info("Modo manos libres iniciado.")

    def _stop_continuous_mode(self):
        """Señala al hilo de escucha continua que debe detenerse."""
        self._continuous_mode = False
        log.info("Modo manos libres detenido.")

    def _continuous_listen_loop(self):
        """Bucle de escucha continua usando VAD. Corre en hilo separado."""
        cfg = self._settings.get_audio()
        device_index    = cfg.get("mic_device_index")
        engine          = cfg.get("stt_engine", "google")
        noise_threshold = cfg.get("noise_threshold", 600)
        silence_ms      = cfg.get("vad_silence_ms", 1200)

        log.info("Bucle VAD iniciado (device=%s, engine=%s)", device_index, engine)

        while self._continuous_mode:
            # No escuchar mientras Zenix habla (anti-eco)
            if self._is_speaking or self._is_listening:
                time.sleep(0.2)
                continue

            self._set_status("[ 🎙 ESCUCHA ACTIVA... ]")
            self.root.after(0, lambda: self._mic_indicator.config(
                text="🎙 MIC ⬤", fg=COLORS["cyan"]))

            text = listen_with_vad(
                device_index=device_index,
                engine=engine,
                noise_threshold=noise_threshold,
                silence_ms=silence_ms,
            )

            # Restaurar indicador
            self.root.after(0, self._update_audio_indicators)

            if text and self._continuous_mode:
                log.info("VAD detectó: '%s'", text)
                self._input_var.set(text)
                self.root.after(0, self._on_send)
                # Esperar a que termine de responder antes de volver a escuchar
                while (self._is_speaking or self._is_listening) and self._continuous_mode:
                    time.sleep(0.3)

        self._set_status("[ ESPERANDO ORDEN ]")
        log.info("Bucle VAD terminado.")

    # ── Bienvenida ────────────────────────────────────────────────

    def _post_welcome(self):
        """Muestra el mensaje de bienvenida al arrancar."""
        welcome = (
            "¡Iniciando Zenix 2.0...\n"
            "Verificando sistemas y conectando los servicios. "
            "Espera un momento, Amo."
        )
        self._append_zenix(welcome)

    def _start_system_checks(self):
        """Inicia la verificación de Ollama y audio en segundo plano."""
        threading.Thread(target=self._run_system_checks, daemon=True).start()

    def _run_system_checks(self):
        self._log_boot("Verificando Ollama...")
        self._set_status("[ INICIALIZANDO SISTEMA... ]")
        self._append_sys("Verificando Ollama, audio y avatar. Esto no bloquea la interfaz.")

        self._log_boot("Verificando TTS...")
        tts_ready = self._wait_for_tts_ready(timeout=3.0)
        self._append_sys(f"[BOOT] TTS listo: {'Sí' if tts_ready else 'No'}")
        self._log_boot("Verificando Audio...")
        audio_ok = self._check_audio_devices()
        from core.assistant import verificar_ollama
        ollama_info = verificar_ollama(timeout=5)

        model_ok = bool(ollama_info.get("model_installed"))
        connected = ollama_info.get("port_available") and bool(ollama_info.get("status"))

        self.root.after(0, self._display_system_health, connected, model_ok, audio_ok, ollama_info)
        self.root.after(0, self._load_memory_status)
        self.root.after(0, self._start_monitor_loop)

        self._log_boot("Sistema listo.")
        if connected and model_ok:
            print("[OLLAMA] Conectado")
            print(f"[MODELO] {Config.MODEL}")
            threading.Thread(target=preload_ollama_model, daemon=True).start()
            self.root.after(1000, self._auto_start_greeting)
            self._set_status("[ ESPERANDO ORDEN ]")
        else:
            self._append_sys("No se pudo conectar con Ollama. Reintentando automáticamente en 5 segundos...")
            self._set_status("[ REINTENTANDO... ]")
            self.root.after(5000, self._start_system_checks)

    def _wait_for_tts_ready(self, timeout: float = 5.0) -> bool:
        try:
            return wait_for_tts_ready(timeout)
        except Exception as exc:
            log.warning("[BOOT] wait_for_tts_ready falló: %s", exc)
            return False

    def _check_audio_devices(self) -> bool:
        cfg = self._settings.get_audio()
        mic_ok = False
        spk_ok = False

        with ThreadPoolExecutor(max_workers=2) as executor:
            mic_future = executor.submit(check_input_device, cfg.get("mic_device_index"))
            spk_future = executor.submit(check_output_device, cfg.get("output_device_index"))
            try:
                mic_ok = mic_future.result(timeout=3)
            except Exception as exc:
                log.warning("[BOOT] Timeout/verificación micrófono: %s", exc)
                mic_ok = False
            try:
                spk_ok = spk_future.result(timeout=3)
            except Exception as exc:
                log.warning("[BOOT] Timeout/verificación altavoz: %s", exc)
                spk_ok = False

        return mic_ok and spk_ok

    def _display_system_health(self, connected: bool, model_ok: bool, audio_ok: bool, ollama_info: dict):
        status_lines = ["[SISTEMA]"]
        status_lines.append("✓ Ollama conectado" if connected else "✘ Ollama desconectado")
        status_lines.append(f"✓ Modelo {Config.MODEL}" if model_ok else f"✘ Modelo {Config.MODEL} no encontrado")
        status_lines.append("✓ Audio operativo" if audio_ok else "✘ Audio con problema")
        status_lines.append("✓ Avatar cargado" if self._avatar_images else "✘ Avatar no cargado")
        if isinstance(ollama_info.get("tags"), list) and ollama_info["tags"]:
            status_lines.append(f"✓ Tags: {len(ollama_info['tags'])} disponibles")
        self._append_sys("\n".join(status_lines))

    def _load_memory_status(self):
        summary = self._memory_manager.get_context_summary()
        self._memory_status_var.set(f"[MEMORIA] {summary}")
        self._append_sys(f"[MEMORIA] Contexto cargado: {summary}")

    def _start_monitor_loop(self):
        threading.Thread(target=self._system_monitor_loop, daemon=True).start()

    def _system_monitor_loop(self):
        while True:
            try:
                summary = self._system_monitor.get_summary()
                display = SystemMonitor.format_summary(summary)
                self.root.after(0, self._system_metrics_var.set, display)
                self.root.after(0, self._append_sys, f"[SISTEMA] {display}")
            except Exception as exc:
                log.warning("[MONITOR] Error actualizando métricas de sistema: %s", exc)
            time.sleep(5)

    def _auto_start_greeting(self):
        greeting = (
            "Hola jefe, qué gusto tenerte aquí nuevamente. "
            "Todos los sistemas están en línea y estoy lista para ayudarte."
        )
        self._append_zenix(greeting)
        self._is_speaking = True
        self._set_status("[ RESPONDIENDO... ]")
        anim_thread = threading.Thread(target=self._animate_speaking, daemon=True)
        tts_thread = threading.Thread(target=self._run_tts, args=(greeting,), daemon=True)
        anim_thread.start()
        tts_thread.start()
        self.root.after(100, lambda: self._wait_for_greeting_completion(tts_thread))

    def _wait_for_greeting_completion(self, tts_thread: threading.Thread):
        if tts_thread.is_alive():
            self.root.after(100, lambda: self._wait_for_greeting_completion(tts_thread))
            return
        self._is_speaking = False
        self._set_status("[ ESPERANDO ORDEN ]")

    def _wait_for_tts_completion(self, tts_thread: threading.Thread, start_time: float | None = None):
        if start_time is None:
            start_time = time.time()

        if not tts_thread.is_alive():
            self._is_speaking = False
            self._lock_controls(False)
            self._set_status("[ ESPERANDO ORDEN ]")
            return

        if time.time() - start_time > 15.0:
            log.warning("[TTS] Tiempo máximo de espera excedido, desbloqueando la UI.")
            self._is_speaking = False
            self._lock_controls(False)
            self._set_status("[ ESPERANDO ORDEN ]")
            return

        self.root.after(100, lambda: self._wait_for_tts_completion(tts_thread, start_time))

    # ── Utilidades UI ─────────────────────────────────────────────

    def _lock_controls(self, locked: bool):
        """Habilita o deshabilita botones de envío."""
        def _set_state():
            state = tk.DISABLED if locked else tk.NORMAL
            self._send_btn.config(state=state)
            self._mic_btn.config(state=state)
            self._input_entry.config(state=state)
        self.root.after(0, _set_state)

    def _add_hover(self, widget: tk.Button,
                   hover_bg: str, normal_bg: str,
                   hover_fg: str, normal_fg: str):
        """Añade efecto hover de color a un botón."""
        widget.bind("<Enter>", lambda _e: widget.config(bg=hover_bg, fg=hover_fg))
        widget.bind("<Leave>", lambda _e: widget.config(bg=normal_bg, fg=normal_fg))

    def _clear_placeholder(self, _event):
        """Borra el placeholder al hacer foco en el campo de texto."""
        if self._input_var.get() == "Escribe tu mensaje aquí...":
            self._input_var.set("")
            self._input_entry.config(fg=COLORS["cyan"])

    def _restore_placeholder(self, _event):
        """Restaura el placeholder si el campo está vacío al perder el foco."""
        if not self._input_var.get():
            self._input_entry.insert(0, "Escribe tu mensaje aquí...")
            self._input_entry.config(fg=COLORS["text_dim"])


# ─────────────────────────────────────────────────────────────────
def launch():
    """Punto de entrada para lanzar la GUI."""
    root = tk.Tk()
    ZenixGUI(root)
    root.mainloop()
