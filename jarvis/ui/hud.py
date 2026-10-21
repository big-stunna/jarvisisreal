"""
GTK3 layer-shell HUD — frosted-glass pill with Cairo arc-reactor ring.

States: IDLE (hidden) → LISTENING → THINKING → SPEAKING → ERROR
Thread-safe: external code calls set_state() from any thread.
"""
from __future__ import annotations

import enum
import math
import threading
import time
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

# ── colours ──────────────────────────────────────────────────────────────────

def _hex(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))


# These match the aamis palette; the HUD reads a live override from config.
_DEFAULTS = {
    "accent":     "#e2be8a",
    "background": "#0f0f0f",
    "error":      "#e25d6c",
    "text":       "#eadccc",
    "ring_blue":  "#7ec8e3",
}


class Colors:
    def __init__(self, overrides: dict | None = None):
        p = {**_DEFAULTS, **(overrides or {})}
        self.accent     = _hex(p["accent"])
        self.background = _hex(p["background"])
        self.error      = _hex(p["error"])
        self.text       = _hex(p["text"])
        self.ring       = _hex(p["ring_blue"])


# ── state machine ─────────────────────────────────────────────────────────────

class HUDState(enum.Enum):
    IDLE      = "idle"
    LISTENING = "listening"
    THINKING  = "thinking"
    SPEAKING  = "speaking"
    ERROR     = "error"


# ── GTK window ───────────────────────────────────────────────────────────────

_PILL_W = 560
_PILL_H = 72
_RING_R = 22          # arc-reactor ring radius
_RING_CX = 48         # ring centre x inside pill
_RING_CY = _PILL_H // 2
_FPS     = 60
_FRAME_MS = 1000 // _FPS


class JarvisHUD(Gtk.Window):
    def __init__(self, colors: Colors | None = None, margin_top: int = 24):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._colors = colors or Colors()
        self._state  = HUDState.IDLE
        self._text: str  = ""
        self._phase: float = 0.0          # animation clock (radians)
        self._ripples: list[float] = []   # list of phase values for active ripples

        # ── window setup ──────────────────────────────────────────────────
        self.set_title("jarvis-hud")
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(_PILL_W, _PILL_H)
        self.set_wmclass("jarvis-hud", "jarvis-hud")

        # transparent ARGB visual for true alpha
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # ── layer shell ───────────────────────────────────────────────────
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP,   True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT,  False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, margin_top)
        GtkLayerShell.set_namespace(self, "jarvis-hud")

        # ── drawing area ──────────────────────────────────────────────────
        self._da = Gtk.DrawingArea()
        self._da.set_size_request(_PILL_W, _PILL_H)
        self._da.connect("draw", self._on_draw)
        self.add(self._da)

        # ── animation ticker ──────────────────────────────────────────────
        GLib.timeout_add(_FRAME_MS, self._tick)

        # start hidden
        self.hide()

    # ── public thread-safe API ────────────────────────────────────────────

    def set_state(self, state: HUDState, text: str = "") -> None:
        """Call from any thread. Schedules the GTK update on the main loop."""
        GLib.idle_add(self._apply_state, state, text)

    def _apply_state(self, state: HUDState, text: str) -> bool:
        prev = self._state
        self._state = state
        self._text  = text

        if state == HUDState.IDLE:
            self.hide()
        else:
            self.show_all()
            if state == HUDState.SPEAKING and prev != HUDState.SPEAKING:
                self._ripples = [0.0]   # seed first ripple

        return False  # don't reschedule

    # ── animation ─────────────────────────────────────────────────────────

    def _tick(self) -> bool:
        self._phase = (self._phase + 0.07) % (2 * math.pi)

        # advance ripples; add a new one every ~0.8s while speaking
        if self._state == HUDState.SPEAKING:
            self._ripples = [r + 0.04 for r in self._ripples if r < 1.0]
            if not self._ripples or self._ripples[-1] > 0.35:
                self._ripples.append(0.0)
        else:
            self._ripples.clear()

        if self._state != HUDState.IDLE:
            self._da.queue_draw()
        return True  # keep ticking

    # ── Cairo drawing ─────────────────────────────────────────────────────

    def _on_draw(self, widget, cr) -> bool:
        w, h = widget.get_allocated_width(), widget.get_allocated_height()

        # clear to transparent
        cr.set_operator(1)  # OVER
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()

        # pill background (frosted-glass approximation)
        self._draw_pill(cr, w, h)

        # arc-reactor ring
        cx, cy = _RING_CX, _RING_CY
        if self._state == HUDState.LISTENING:
            self._draw_pulse(cr, cx, cy)
        elif self._state == HUDState.THINKING:
            self._draw_spin(cr, cx, cy)
        elif self._state == HUDState.SPEAKING:
            self._draw_ripple(cr, cx, cy)
        elif self._state == HUDState.ERROR:
            self._draw_amber(cr, cx, cy)

        # text label
        self._draw_label(cr, w, h)
        return False

    def _draw_pill(self, cr, w: int, h: int) -> None:
        r = h / 2
        bg = self._colors.background
        cr.set_source_rgba(*bg, 0.88)
        # rounded-rect path
        cr.arc(r, r, r, math.pi / 2, 3 * math.pi / 2)
        cr.arc(w - r, r, r, -math.pi / 2, math.pi / 2)
        cr.close_path()
        cr.fill()

        # subtle border
        cr.set_source_rgba(1, 1, 1, 0.06)
        cr.set_line_width(1)
        cr.arc(r, r, r, math.pi / 2, 3 * math.pi / 2)
        cr.arc(w - r, r, r, -math.pi / 2, math.pi / 2)
        cr.close_path()
        cr.stroke()

    def _draw_pulse(self, cr, cx: int, cy: int) -> None:
        """Three concentric rings that breathe in and out."""
        col = self._colors.ring
        for i, (base_r, speed, alpha_base) in enumerate([
            (_RING_R,      1.0,  0.9),
            (_RING_R + 7,  0.8,  0.55),
            (_RING_R + 14, 0.6,  0.25),
        ]):
            phase = self._phase * speed + i * math.pi / 3
            scale = 1.0 + 0.12 * math.sin(phase)
            alpha = alpha_base * (0.7 + 0.3 * math.sin(phase))
            cr.set_source_rgba(*col, alpha)
            cr.set_line_width(2.0 - i * 0.4)
            cr.arc(cx, cy, base_r * scale, 0, 2 * math.pi)
            cr.stroke()

    def _draw_spin(self, cr, cx: int, cy: int) -> None:
        """Three arc segments rotating at different speeds (thinking)."""
        col = self._colors.ring
        configs = [
            (_RING_R,      self._phase * 1.8,   1.2, 0.9),
            (_RING_R + 7,  -self._phase * 1.1,  0.8, 0.6),
            (_RING_R + 14, self._phase * 0.6,   0.5, 0.35),
        ]
        arc_len = math.pi * 0.6
        for radius, offset, lw, alpha in configs:
            cr.set_source_rgba(*col, alpha)
            cr.set_line_width(lw)
            cr.set_line_cap(1)  # ROUND
            cr.arc(cx, cy, radius, offset, offset + arc_len)
            cr.stroke()

    def _draw_ripple(self, cr, cx: int, cy: int) -> None:
        """Expanding rings from centre (speaking)."""
        col = self._colors.accent
        for t in self._ripples:
            r = _RING_R + t * 30
            alpha = (1.0 - t) * 0.85
            cr.set_source_rgba(*col, alpha)
            cr.set_line_width(max(0.5, 2.0 * (1.0 - t)))
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
        # static inner dot
        cr.set_source_rgba(*col, 0.8)
        cr.arc(cx, cy, 5, 0, 2 * math.pi)
        cr.fill()

    def _draw_amber(self, cr, cx: int, cy: int) -> None:
        """Static amber ring for error/confirmation states."""
        col = self._colors.accent  # warm gold = amber
        cr.set_source_rgba(*col, 0.9)
        cr.set_line_width(2.5)
        cr.arc(cx, cy, _RING_R, 0, 2 * math.pi)
        cr.stroke()
        # glow
        cr.set_source_rgba(*col, 0.25)
        cr.arc(cx, cy, _RING_R + 6, 0, 2 * math.pi)
        cr.stroke()

    def _draw_label(self, cr, w: int, h: int) -> None:
        if not self._text:
            return
        col = self._colors.text
        cr.set_source_rgba(*col, 0.92)
        cr.select_font_face("Sans", 0, 0)  # NORMAL weight
        cr.set_font_size(13)
        # clip label to right of ring area
        text_x = _RING_CX + _RING_R + 20
        max_w  = w - text_x - 16
        label  = self._clip_text(cr, self._text, max_w)
        ext = cr.text_extents(label)
        cr.move_to(text_x, h / 2 + ext.height / 2)
        cr.show_text(label)

    @staticmethod
    def _clip_text(cr, text: str, max_px: float) -> str:
        while text:
            ext = cr.text_extents(text + "…")
            if ext.width <= max_px:
                return text + "…" if len(text) < len(text) else text
            text = text[:-1]
        return ""


# ── controller (thread-safe facade) ──────────────────────────────────────────

class HUDController:
    """
    Runs the GTK main loop in a daemon thread.
    All public methods are safe to call from any thread.
    """
    def __init__(self, colors: Colors | None = None):
        self._hud: Optional[JarvisHUD] = None
        self._ready = threading.Event()
        self._colors = colors
        self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-hud")
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def _run(self) -> None:
        GLib.threads_init()
        self._hud = JarvisHUD(colors=self._colors)
        self._ready.set()
        Gtk.main()

    # ── public API ────────────────────────────────────────────────────────

    def listening(self) -> None:
        self._hud and self._hud.set_state(HUDState.LISTENING)

    def thinking(self, text: str = "") -> None:
        self._hud and self._hud.set_state(HUDState.THINKING, text)

    def speaking(self, text: str = "") -> None:
        self._hud and self._hud.set_state(HUDState.SPEAKING, text)

    def error(self, text: str = "") -> None:
        self._hud and self._hud.set_state(HUDState.ERROR, text)

    def idle(self) -> None:
        self._hud and self._hud.set_state(HUDState.IDLE)

    def stop(self) -> None:
        GLib.idle_add(Gtk.main_quit)


def load_theme_colors(config: dict | None = None) -> Colors:
    """Read accent/background/etc from config or Omarchy theme file."""
    import tomllib
    from pathlib import Path

    overrides: dict = {}

    theme_dir = Path.home() / ".config" / "omarchy" / "themes"
    current_path = Path.home() / ".config" / "omarchy" / "current"

    try:
        theme_name = current_path.read_text().strip()
        colors_path = theme_dir / theme_name / "colors.toml"
        if colors_path.exists():
            data = tomllib.loads(colors_path.read_text())
            overrides["accent"]     = data.get("accent", _DEFAULTS["accent"])
            overrides["background"] = data.get("background", _DEFAULTS["background"])
            overrides["text"]       = data.get("foreground", _DEFAULTS["text"])
    except Exception:
        pass

    return Colors(overrides)
