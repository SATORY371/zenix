"""
╔══════════════════════════════════════════════════════════════════╗
║   ZENIX v2.0 — Ventana de Configuración de Audio                 ║
║   Selección de micrófono, altavoz, motor STT y modo voz          ║
╚══════════════════════════════════════════════════════════════════╝
"""

import logging
import threading
import tkinter as tk
from tkinter import font, ttk, messagebox
from typing import Optional

from core.settings_manager import get_settings
import core.speech as speech_mod

log = logging.getLogger("zenix.audio_config")

# ── Paleta (misma que gui.py para coherencia visual) ─────────────────
C = {
    "bg":          "#080B14",
    "panel":       "#0D1117",
    "panel_light": "#161B27",
    "border":      "#1E2D45",
    "cyan":        "#00F5FF",
    "cyan_dim":    "#0A7E8A",
    "magenta":     "#FF2D78",
    "magenta_dim": "#7A1440",
    "purple":      "#BD00FF",
    "yellow":      "#FFD700",
    "green":       "#00FF88",
    "red":         "#FF4444",
    "text":        "#C8D6E5",
    "text_dim":    "#5A7080",
    "white":       "#F0F4FF",
}


class AudioConfigWindow(tk.Toplevel):
    """
    Ventana Toplevel de configuración de audio de Zenix.

    Secciones:
      1. Dispositivo de entrada  (micrófono + barra de nivel + prueba)
      2. Dispositivo de salida   (altavoz + prueba)
      3. Motor STT               (Google / Sphinx)
      4. Voz TTS                 (lista de voces del sistema)
      5. Modo de conversación    (manos libres / manual, umbrales VAD)
    """

    def __init__(self, parent: tk.Tk):
        super().__init__(parent)
        self.parent = parent
        self._settings = get_settings()
        self._audio_cfg = self._settings.get_audio()

        # Estado interno
        self._level_running = False
        self._test_mic_active = False

        self._configure_window()
        self._define_fonts()
        self._apply_style()
        self._build_ui()
        self._populate_devices()
        self._load_current_settings()

    # ── Configuración de la ventana ───────────────────────────────────

    def _configure_window(self):
        self.title("⚙  Configuración de Audio — Zenix v2.0")
        self.geometry("760x660")
        self.resizable(False, False)
        self.configure(bg=C["bg"])
        self.grab_set()          # Modal: bloquea la ventana principal
        self.focus_force()

    def _define_fonts(self):
        self.f_title   = font.Font(family="Consolas", size=13, weight="bold")
        self.f_section = font.Font(family="Consolas", size=10, weight="bold")
        self.f_label   = font.Font(family="Consolas", size=9)
        self.f_btn     = font.Font(family="Consolas", size=9, weight="bold")
        self.f_small   = font.Font(family="Consolas", size=8)

    def _apply_style(self):
        """Aplica tema oscuro al widget ttk.Combobox."""
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Dark.TCombobox",
                        fieldbackground=C["panel_light"],
                        background=C["panel"],
                        foreground=C["cyan"],
                        selectbackground=C["cyan_dim"],
                        selectforeground=C["bg"],
                        arrowcolor=C["cyan"])
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", C["panel_light"])],
                  foreground=[("readonly", C["cyan"])])

    # ── Construcción de la UI ─────────────────────────────────────────

    def _build_ui(self):
        # ── Título ───────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=C["panel"], height=44)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⚙  CONFIGURACIÓN DE AUDIO  //  ZENIX_OS",
                 font=self.f_title, bg=C["panel"], fg=C["cyan"]).pack(
                 side=tk.LEFT, padx=18, pady=10)

        # ── Contenido scrollable ──────────────────────────────────────
        canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self._scroll_frame = tk.Frame(canvas, bg=C["bg"])

        self._scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Permitir scroll con rueda del ratón
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        pad = {"padx": 18, "pady": 6}

        # ── Sección 1: Entrada (Micrófono) ────────────────────────────
        self._section_header("🎙  DISPOSITIVO DE ENTRADA  (Micrófono)")

        lf1 = self._make_frame()
        lf1.grid_columnconfigure(1, weight=1)
        tk.Label(lf1, text="Micrófono:", font=self.f_label,
                 bg=C["panel"], fg=C["text_dim"]).grid(
                 row=0, column=0, sticky="w", **pad)

        self._mic_var = tk.StringVar()
        self._mic_combo = ttk.Combobox(lf1, textvariable=self._mic_var,
                                       state="readonly", style="Dark.TCombobox",
                                       width=44, font=self.f_label)
        self._mic_combo.grid(row=0, column=1, columnspan=2, sticky="we", padx=(0, 18), pady=6)

        # Barra de nivel de micrófono
        tk.Label(lf1, text="Nivel:", font=self.f_label,
                 bg=C["panel"], fg=C["text_dim"]).grid(row=1, column=0, sticky="w", **pad)

        level_frame = tk.Frame(lf1, bg=C["panel_light"],
                               highlightbackground=C["border"], highlightthickness=1,
                               height=18, width=320)
        level_frame.grid(row=1, column=1, sticky="we", padx=(0, 8), pady=6)
        level_frame.pack_propagate(False)

        self._level_bar = tk.Frame(level_frame, bg=C["cyan_dim"], width=0, height=16)
        self._level_bar.place(x=0, y=1)

        self._level_label = tk.Label(lf1, text="—", font=self.f_small,
                                     bg=C["panel"], fg=C["cyan_dim"])
        self._level_label.grid(row=1, column=2, padx=(4, 18))

        # Botones de prueba de micrófono
        btn_row = tk.Frame(lf1, bg=C["panel"])
        btn_row.grid(row=2, column=0, columnspan=3, sticky="w", **pad)

        self._test_mic_btn = self._make_btn(btn_row, "▶ Probar Mic",
                                            C["cyan_dim"], C["cyan"],
                                            self._toggle_mic_test)
        self._test_mic_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._mic_status = tk.Label(btn_row, text="", font=self.f_small,
                                    bg=C["panel"], fg=C["green"])
        self._mic_status.pack(side=tk.LEFT)

        # ── Sección 2: Salida (Altavoces) ─────────────────────────────
        self._section_header("🔊  DISPOSITIVO DE SALIDA  (Altavoces)")

        lf2 = self._make_frame()
        lf2.grid_columnconfigure(1, weight=1)
        tk.Label(lf2, text="Altavoz:", font=self.f_label,
                 bg=C["panel"], fg=C["text_dim"]).grid(
                 row=0, column=0, sticky="w", **pad)

        self._out_var = tk.StringVar()
        self._out_combo = ttk.Combobox(lf2, textvariable=self._out_var,
                                       state="readonly", style="Dark.TCombobox",
                                       width=44, font=self.f_label)
        self._out_combo.grid(row=0, column=1, columnspan=2, sticky="we",
                             padx=(0, 18), pady=6)

        btn_row2 = tk.Frame(lf2, bg=C["panel"])
        btn_row2.grid(row=1, column=0, columnspan=3, sticky="w", **pad)

        self._make_btn(btn_row2, "▶ Probar Altavoz",
                       C["magenta_dim"], C["magenta"],
                       self._test_output).pack(side=tk.LEFT, padx=(0, 8))

        self._out_status = tk.Label(btn_row2, text="", font=self.f_small,
                                    bg=C["panel"], fg=C["green"])
        self._out_status.pack(side=tk.LEFT)

        tk.Label(lf2, text="ℹ  El dispositivo de salida para TTS\n"
                           "   se controla desde el sistema operativo.",
                 font=self.f_small, bg=C["panel"], fg=C["text_dim"],
                 justify=tk.LEFT).grid(row=2, column=0, columnspan=3,
                                        sticky="w", padx=18, pady=(0, 8))

        # ── Sección 3: Motor STT ──────────────────────────────────────
        self._section_header("🧠  MOTOR DE RECONOCIMIENTO DE VOZ  (STT)")

        lf3 = self._make_frame()
        lf3.grid_columnconfigure(0, weight=1)
        self._stt_var = tk.StringVar(value="google")

        stt_frame = tk.Frame(lf3, bg=C["panel"])
        stt_frame.grid(row=0, column=0, columnspan=3, sticky="we", padx=18, pady=8)

        for val, label, desc in [
            ("google", "Google Speech  (online, recomendado)",
             "Mayor precisión. Requiere conexión a internet."),
            ("sphinx", "PocketSphinx  (offline, local)",
             "Sin internet. Menor precisión. Ideal sin conexión."),
        ]:
            rb = tk.Radiobutton(stt_frame, text=label,
                                variable=self._stt_var, value=val,
                                font=self.f_label, bg=C["panel"], fg=C["text"],
                                activebackground=C["panel"],
                                activeforeground=C["cyan"],
                                selectcolor=C["panel_light"],
                                indicatoron=True)
            rb.pack(anchor="w", pady=2)
            tk.Label(stt_frame, text=f"   {desc}", font=self.f_small,
                     bg=C["panel"], fg=C["text_dim"]).pack(anchor="w")

        # ── Sección 4: Voz TTS ────────────────────────────────────────
        self._section_header("🗣  VOZ DE SÍNTESIS  (TTS)")

        lf4 = self._make_frame()
        lf4.grid_columnconfigure(1, weight=1)
        tk.Label(lf4, text="Voz:", font=self.f_label,
                 bg=C["panel"], fg=C["text_dim"]).grid(
                 row=0, column=0, sticky="w", **pad)

        self._voice_var = tk.StringVar()
        self._voice_combo = ttk.Combobox(lf4, textvariable=self._voice_var,
                                         state="readonly", style="Dark.TCombobox",
                                         width=40, font=self.f_label)
        self._voice_combo.grid(row=0, column=1, sticky="we", padx=(0, 8), pady=6)

        self._make_btn(lf4, "▶ Probar voz", C["purple"], C["purple"],
                       self._test_voice).grid(row=0, column=2, padx=(0, 18), pady=6)

        tk.Label(lf4, text="Velocidad:", font=self.f_label,
                 bg=C["panel"], fg=C["text_dim"]).grid(
                 row=1, column=0, sticky="w", **pad)

        self._rate_var = tk.IntVar(value=180)
        rate_scale = tk.Scale(lf4, from_=80, to=300, orient=tk.HORIZONTAL,
                              variable=self._rate_var, bg=C["panel"],
                              fg=C["cyan"], troughcolor=C["panel_light"],
                              highlightthickness=0, length=220)
        rate_scale.grid(row=1, column=1, sticky="we", padx=(0, 8), pady=4)

        self._rate_lbl = tk.Label(lf4, text="180 ppm",
                                  font=self.f_small, bg=C["panel"], fg=C["cyan_dim"])
        self._rate_lbl.grid(row=1, column=2, padx=(0, 18))
        self._rate_var.trace_add("write",
                                 lambda *_: self._rate_lbl.config(
                                     text=f"{self._rate_var.get()} ppm"))

        # ── Sección 5: Modo conversación ──────────────────────────────
        self._section_header("🔄  MODO DE CONVERSACIÓN")

        lf5 = self._make_frame()
        lf5.grid_columnconfigure(1, weight=1)
        self._continuous_var = tk.BooleanVar(value=False)
        tk.Checkbutton(lf5, text="Activar Modo Manos Libres  (conversación continua)",
                       variable=self._continuous_var,
                       font=self.f_label, bg=C["panel"], fg=C["text"],
                       activebackground=C["panel"], activeforeground=C["cyan"],
                       selectcolor=C["panel_light"],
                       command=self._on_continuous_toggle).grid(
                       row=0, column=0, columnspan=3, sticky="w", padx=18, pady=8)

        tk.Label(lf5, text="Umbral de ruido (VAD):", font=self.f_label,
                 bg=C["panel"], fg=C["text_dim"]).grid(
                 row=1, column=0, sticky="w", padx=18, pady=4)

        self._threshold_var = tk.IntVar(value=600)
        th_scale = tk.Scale(lf5, from_=100, to=3000, orient=tk.HORIZONTAL,
                            variable=self._threshold_var, bg=C["panel"],
                            fg=C["yellow"], troughcolor=C["panel_light"],
                            highlightthickness=0, length=220)
        th_scale.grid(row=1, column=1, sticky="we", padx=(0, 8), pady=4)

        self._th_lbl = tk.Label(lf5, text="600 RMS", font=self.f_small,
                                bg=C["panel"], fg=C["yellow"])
        self._th_lbl.grid(row=1, column=2, padx=(0, 18))
        self._threshold_var.trace_add("write",
                                      lambda *_: self._th_lbl.config(
                                          text=f"{self._threshold_var.get()} RMS"))

        tk.Label(lf5, text="Silencio para cortar frase (ms):", font=self.f_label,
                 bg=C["panel"], fg=C["text_dim"]).grid(
                 row=2, column=0, sticky="w", padx=18, pady=4)

        self._silence_var = tk.IntVar(value=1200)
        sil_scale = tk.Scale(lf5, from_=400, to=3000, resolution=100,
                             orient=tk.HORIZONTAL, variable=self._silence_var,
                             bg=C["panel"], fg=C["yellow"],
                             troughcolor=C["panel_light"], highlightthickness=0,
                             length=220)
        sil_scale.grid(row=2, column=1, sticky="we", padx=(0, 8), pady=4)

        self._sil_lbl = tk.Label(lf5, text="1200 ms", font=self.f_small,
                                 bg=C["panel"], fg=C["yellow"])
        self._sil_lbl.grid(row=2, column=2, padx=(0, 18))
        self._silence_var.trace_add("write",
                                    lambda *_: self._sil_lbl.config(
                                        text=f"{self._silence_var.get()} ms"))

        self._continuous_desc = tk.Label(
            lf5,
            text="ℹ  Habla libremente y Zenix te escuchará\n"
                 "   automáticamente tras cada respuesta.",
            font=self.f_small, bg=C["panel"], fg=C["text_dim"], justify=tk.LEFT)
        self._continuous_desc.grid(row=3, column=0, columnspan=3,
                                   sticky="w", padx=18, pady=(0, 8))

        # ── Botones inferiores ────────────────────────────────────────
        self._build_footer()

    def _build_footer(self):
        """Barra inferior con botones Guardar / Resetear / Cancelar."""
        footer = tk.Frame(self, bg=C["panel"],
                          highlightbackground=C["border"], highlightthickness=1)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        self._make_btn(footer, "↺  Restaurar Defaults",
                       C["panel_light"], C["text_dim"],
                       self._reset_defaults).pack(side=tk.LEFT, padx=12, pady=10,
                                                   ipady=4, ipadx=6)

        self._make_btn(footer, "✕  Cancelar",
                       C["panel_light"], C["text_dim"],
                       self._on_cancel).pack(side=tk.RIGHT, padx=12, pady=10,
                                             ipady=4, ipadx=6)

        self._make_btn(footer, "✔  Guardar Configuración",
                       C["magenta_dim"], C["magenta"],
                       self._on_save).pack(side=tk.RIGHT, padx=(0, 8), pady=10,
                                           ipady=4, ipadx=6)

    # ── Widgets helpers ───────────────────────────────────────────────

    def _section_header(self, title: str) -> tk.Label:
        """Crea un encabezado de sección con línea separadora."""
        sep = tk.Frame(self._scroll_frame, bg=C["border"], height=1)
        sep.pack(fill=tk.X, padx=18, pady=(12, 0))
        lbl = tk.Label(self._scroll_frame, text=title,
                       font=self.f_section, bg=C["bg"], fg=C["cyan"])
        lbl.pack(anchor="w", padx=18, pady=(4, 0))
        return lbl

    def _make_frame(self) -> tk.Frame:
        """Crea un frame de panel para una sección."""
        f = tk.Frame(self._scroll_frame, bg=C["panel"],
                     highlightbackground=C["border"], highlightthickness=1)
        f.pack(fill=tk.X, padx=18, pady=(4, 0))
        return f

    def _make_btn(self, parent, text, bg, fg, cmd) -> tk.Button:
        """Crea un botón con estilo cyberpunk."""
        btn = tk.Button(parent, text=text, bg=bg, fg=fg,
                        font=self.f_btn, relief=tk.FLAT, bd=0,
                        activebackground=fg, activeforeground=C["bg"],
                        cursor="hand2", command=cmd)
        btn.bind("<Enter>", lambda _e: btn.config(bg=fg, fg=C["bg"]))
        btn.bind("<Leave>", lambda _e: btn.config(bg=bg, fg=fg))
        return btn

    # ── Población de dispositivos ─────────────────────────────────────

    def _populate_devices(self):
        """Carga listas de dispositivos en los combos en un hilo separado."""
        threading.Thread(target=self._load_devices_async, daemon=True).start()

    def _load_devices_async(self):
        """Obtiene dispositivos del sistema y actualiza los combos."""
        # Micrófonos
        inputs = speech_mod.get_input_devices()
        self._input_devices = inputs
        input_names = [f"[{d['index']}] {d['name']}" for d in inputs]
        if not input_names:
            input_names = ["— No se detectaron micrófonos —"]
        self.after(0, lambda: self._mic_combo.config(values=input_names))

        # Altavoces
        outputs = speech_mod.get_output_devices()
        self._output_devices = outputs
        output_names = [f"[{d['index']}] {d['name']}" for d in outputs]
        if not output_names:
            output_names = ["— No se detectaron altavoces —"]
        self.after(0, lambda: self._out_combo.config(values=output_names))

        # Voces TTS
        voices = speech_mod.get_available_voices()
        self._tts_voices = voices
        voice_names = [v["name"] for v in voices]
        if not voice_names:
            voice_names = ["— Sin voces instaladas —"]
        self.after(0, lambda: self._voice_combo.config(values=voice_names))

    # ── Carga de configuración actual ────────────────────────────────

    def _load_current_settings(self):
        """Rellena los widgets con los valores guardados."""
        cfg = self._audio_cfg

        # STT engine
        self._stt_var.set(cfg.get("stt_engine", "google"))

        # Velocidad TTS
        self._rate_var.set(cfg.get("speech_rate", 180))

        # Modo continuo
        self._continuous_var.set(cfg.get("continuous_mode", False))

        # VAD thresholds
        self._threshold_var.set(cfg.get("noise_threshold", 600))
        self._silence_var.set(cfg.get("vad_silence_ms", 1200))

        # Los combos de dispositivo y voz se setean después de cargar la lista
        # usando after() para esperar a que _load_devices_async termine
        self.after(800, self._set_saved_device_selections)

    def _set_saved_device_selections(self):
        """Selecciona en los combos los dispositivos guardados previamente."""
        cfg = self._audio_cfg
        saved_mic  = cfg.get("mic_device_name", "")
        saved_out  = cfg.get("output_device_name", "")
        saved_voice = cfg.get("tts_voice", "Zira")

        # Micrófono
        for i, val in enumerate(self._mic_combo["values"]):
            if saved_mic and saved_mic in val:
                self._mic_combo.current(i)
                break
        else:
            if self._mic_combo["values"]:
                self._mic_combo.current(0)

        # Altavoz
        for i, val in enumerate(self._out_combo["values"]):
            if saved_out and saved_out in val:
                self._out_combo.current(i)
                break
        else:
            if self._out_combo["values"]:
                self._out_combo.current(0)

        # Voz TTS
        for i, val in enumerate(self._voice_combo["values"]):
            if saved_voice and saved_voice.lower() in val.lower():
                self._voice_combo.current(i)
                break
        else:
            if self._voice_combo["values"]:
                self._voice_combo.current(0)

    # ── Prueba de micrófono ───────────────────────────────────────────

    def _toggle_mic_test(self):
        """Activa o desactiva la prueba del micrófono (barra de nivel)."""
        if self._test_mic_active:
            self._stop_mic_test()
        else:
            self._start_mic_test()

    def _start_mic_test(self):
        """Inicia el stream de nivel de micrófono."""
        self._test_mic_active = True
        self._test_mic_btn.config(text="⏹ Detener Mic")
        self._mic_status.config(text="Escuchando nivel...", fg=C["green"])

        device_index = self._get_selected_mic_index()
        speech_mod.start_microphone_level(
            callback=self._update_level_bar,
            device_index=device_index,
        )

    def _stop_mic_test(self):
        """Detiene el stream de nivel de micrófono."""
        speech_mod.stop_microphone_level()
        self._test_mic_active = False
        self._test_mic_btn.config(text="▶ Probar Mic")
        self._mic_status.config(text="")
        self.after(0, lambda: self._level_bar.config(width=0))
        self._level_label.config(text="—")

    def _update_level_bar(self, level: float):
        """Callback thread-safe para actualizar la barra de nivel (0.0–1.0)."""
        width = int(level * 318)
        # Color dinámico: verde → amarillo → rojo según nivel
        if level < 0.5:
            color = C["green"]
        elif level < 0.8:
            color = C["yellow"]
        else:
            color = C["red"]
        pct = int(level * 100)
        self.after(0, lambda: (
            self._level_bar.config(width=width, bg=color),
            self._level_label.config(text=f"{pct}%")
        ))

    # ── Prueba de altavoz ─────────────────────────────────────────────

    def _test_output(self):
        """Reproduce una frase de prueba con la configuración actual."""
        self._out_status.config(text="Reproduciendo...", fg=C["yellow"])
        voice = self._get_selected_voice_name()

        def _play():
            try:
                speech_mod.set_output_device(self._get_selected_out_index())
                speech_mod.speak(
                    "¡Hola! Soy Zenix, tu asistente fox girl cyberpunk. ¡Nya~! 🦊",
                    voice_name=voice if voice else None,
                )
                self.after(0, lambda: self._out_status.config(
                    text="✔ Prueba completada", fg=C["green"]))
            except Exception as e:
                self.after(0, lambda: self._out_status.config(
                    text=f"✘ Error: {e}", fg=C["red"]))

        threading.Thread(target=_play, daemon=True).start()

    # ── Prueba de voz TTS ─────────────────────────────────────────────

    def _test_voice(self):
        """Reproduce prueba con la voz seleccionada en el combo."""
        voice = self._get_selected_voice_name()
        if not voice:
            return
        speech_mod.set_output_device(self._get_selected_out_index())
        threading.Thread(
            target=speech_mod.speak,
            args=("¡Probando la voz seleccionada! *mueve las orejas* 🦊",),
            kwargs={"voice_name": voice},
            daemon=True,
        ).start()

    # ── Toggle modo manos libres ──────────────────────────────────────

    def _on_continuous_toggle(self):
        """Muestra u oculta hint del modo manos libres."""
        if self._continuous_var.get():
            self._continuous_desc.config(
                text="✔  Zenix te escuchará automáticamente tras\n"
                     "   cada respuesta. Di «salir» para terminar.",
                fg=C["green"]
            )
        else:
            self._continuous_desc.config(
                text="ℹ  Habla libremente y Zenix te escuchará\n"
                     "   automáticamente tras cada respuesta.",
                fg=C["text_dim"]
            )

    # ── Getters de selección ──────────────────────────────────────────

    def _get_selected_mic_index(self) -> Optional[int]:
        """Extrae el índice de dispositivo del combo de micrófono."""
        sel = self._mic_var.get()
        if sel.startswith("["):
            try:
                return int(sel.split("]")[0].replace("[", "").strip())
            except ValueError:
                pass
        return None

    def _get_selected_mic_name(self) -> str:
        """Extrae el nombre (sin índice) del combo de micrófono."""
        sel = self._mic_var.get()
        if "]" in sel:
            return sel.split("]", 1)[1].strip()
        return sel

    def _get_selected_out_index(self) -> Optional[int]:
        """Extrae el índice del combo de altavoz."""
        sel = self._out_var.get()
        if sel.startswith("["):
            try:
                return int(sel.split("]")[0].replace("[", "").strip())
            except ValueError:
                pass
        return None

    def _get_selected_out_name(self) -> str:
        """Extrae el nombre (sin índice) del combo de altavoz."""
        sel = self._out_var.get()
        if "]" in sel:
            return sel.split("]", 1)[1].strip()
        return sel

    def _get_selected_voice_name(self) -> str:
        """Retorna el nombre de la voz TTS seleccionada."""
        return self._voice_var.get()

    # ── Guardar / Cancelar / Reset ────────────────────────────────────

    def _on_save(self):
        """Guarda toda la configuración de audio y cierra la ventana."""
        # Detener prueba de mic si estaba activa
        if self._test_mic_active:
            self._stop_mic_test()

        changes = {
            "mic_device_index":    self._get_selected_mic_index(),
            "mic_device_name":     self._get_selected_mic_name(),
            "output_device_index": self._get_selected_out_index(),
            "output_device_name":  self._get_selected_out_name(),
            "stt_engine":          self._stt_var.get(),
            "tts_voice":           self._get_selected_voice_name(),
            "speech_rate":         self._rate_var.get(),
            "continuous_mode":     self._continuous_var.get(),
            "noise_threshold":     self._threshold_var.get(),
            "vad_silence_ms":      self._silence_var.get(),
        }

        self._settings.update_audio(changes)
        log.info("Configuración de audio guardada: %s", changes)

        # Re-inicializar TTS con la nueva voz y velocidad
        threading.Thread(
            target=speech_mod.init_speech,
            kwargs={
                "voice_name": changes["tts_voice"],
                "rate":       changes["speech_rate"],
            },
            daemon=True,
        ).start()

        messagebox.showinfo(
            "Configuración guardada",
            "✔ Configuración de audio guardada correctamente.\n"
            "Los cambios se aplicarán de inmediato.",
            parent=self,
        )
        self.destroy()

    def _on_cancel(self):
        """Cierra sin guardar."""
        if self._test_mic_active:
            self._stop_mic_test()
        self.destroy()

    def _reset_defaults(self):
        """Restaura los valores por defecto en todos los controles."""
        self._stt_var.set("google")
        self._rate_var.set(180)
        self._continuous_var.set(False)
        self._threshold_var.set(600)
        self._silence_var.set(1200)
        self._on_continuous_toggle()
        log.info("Configuración de audio restaurada a defaults.")

    def destroy(self):
        """Limpieza al cerrar la ventana."""
        if self._test_mic_active:
            speech_mod.stop_microphone_level()
        super().destroy()
