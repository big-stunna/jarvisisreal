"""
J.A.R.V.I.S. HUD — Iron Man-style Wayland overlay.

States: IDLE (hidden) → LISTENING → THINKING → SPEAKING → ERROR
GTK3 layer-shell pill anchored top-centre.
Thread-safe: call set_state() from any thread.
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


# ── palette ───────────────────────────────────────────────────────────────────

def _hex(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))


_IRON_BLUE   = _hex("#00d4ff")   # arc reactor blue
_IRON_GOLD   = _hex("#e2be8a")   # Stark gold accent
_IRON_RED    = _hex("#e25d6c")   # error red
_IRON_BG     = _hex("#050e1a")   # near-black navy
_IRON_TEXT   = _hex("#c8eaf5")   # cool white


class HUDState(enum.Enum):
    IDLE      = "idle"
    LISTENING = "listening"
    THINKING  = "thinking"
    SPEAKING  = "speaking"
    ERROR     = "error"


# ── dimensions ────────────────────────────────────────────────────────────────

_PILL_W  = 620
_PILL_H  = 80
_RING_R  = 24
_RING_CX = 52
_RING_CY = _PILL_H // 2
_FPS     = 60
_FRAME_MS = 1000 // _FPS


# ── window ────────────────────────────────────────────────────────────────────

class JarvisHUD(Gtk.Window):
    def __init__(self, margin_top: int = 32):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._state  = HUDState.IDLE
        self._text   = ""
        self._phase  = 0.0
        self._ripples: list[float] = []

        self.set_title("jarvis-hud")
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(_PILL_W, _PILL_H)
        self.set_wmclass("jarvis-hud", "jarvis-hud")

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP,   True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT,  False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, margin_top)
        GtkLayerShell.set_namespace(self, "jarvis-hud")

        self._da = Gtk.DrawingArea()
        self._da.set_size_request(_PILL_W, _PILL_H)
        self._da.connect("draw", self._on_draw)
        self.add(self._da)

        GLib.timeout_add(_FRAME_MS, self._tick)
        self.hide()

    # ── public API ────────────────────────────────────────────────────────

    def set_state(self, state: HUDState, text: str = "") -> None:
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
                self._ripples = [0.0]
        return False

    # ── animation ─────────────────────────────────────────────────────────

    def _tick(self) -> bool:
        self._phase = (self._phase + 0.07) % (2 * math.pi)

        if self._state == HUDState.SPEAKING:
            self._ripples = [r + 0.035 for r in self._ripples if r < 1.0]
            if not self._ripples or self._ripples[-1] > 0.3:
                self._ripples.append(0.0)
        else:
            self._ripples.clear()

        if self._state != HUDState.IDLE:
            self._da.queue_draw()
        return True

    # ── drawing ───────────────────────────────────────────────────────────

    def _on_draw(self, widget, cr) -> bool:
        w, h = widget.get_allocated_width(), widget.get_allocated_height()

        cr.set_operator(1)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()

        self._draw_pill(cr, w, h)
        self._draw_scan_line(cr, w, h)

        cx, cy = _RING_CX, _RING_CY
        if self._state == HUDState.LISTENING:
            self._draw_pulse(cr, cx, cy)
        elif self._state == HUDState.THINKING:
            self._draw_spin(cr, cx, cy)
        elif self._state == HUDState.SPEAKING:
            self._draw_ripple(cr, cx, cy)
        elif self._state == HUDState.ERROR:
            self._draw_error_ring(cr, cx, cy)
        else:
            self._draw_idle_ring(cr, cx, cy)

        self._draw_label(cr, w, h)
        return False

    def _draw_pill(self, cr, w, h) -> None:
        r = h / 2
        bg = _IRON_BG
        cr.set_source_rgba(*bg, 0.92)
        cr.arc(r, r, r, math.pi / 2, 3 * math.pi / 2)
        cr.arc(w - r, r, r, -math.pi / 2, math.pi / 2)
        cr.close_path()
        cr.fill()

        # blue glow border
        col = _IRON_BLUE
        glow_alpha = 0.4 + 0.25 * math.sin(self._phase)
        cr.set_source_rgba(*col, glow_alpha)
        cr.set_line_width(1.5)
        cr.arc(r, r, r, math.pi / 2, 3 * math.pi / 2)
        cr.arc(w - r, r, r, -math.pi / 2, math.pi / 2)
        cr.close_path()
        cr.stroke()

    def _draw_scan_line(self, cr, w, h) -> None:
        """Subtle horizontal scan line that sweeps top-to-bottom."""
        if self._state not in (HUDState.LISTENING, HUDState.THINKING):
            return
        y = (h * ((self._phase / (2 * math.pi)) % 1.0))
        cr.set_source_rgba(*_IRON_BLUE, 0.12)
        cr.set_line_width(1)
        cr.move_to(40, y)
        cr.line_to(w - 40, y)
        cr.stroke()

    def _draw_idle_ring(self, cr, cx, cy) -> None:
        cr.set_source_rgba(*_IRON_BLUE, 0.3)
        cr.set_line_width(1.5)
        cr.arc(cx, cy, _RING_R, 0, 2 * math.pi)
        cr.stroke()

    def _draw_pulse(self, cr, cx, cy) -> None:
        """Breathing concentric rings — LISTENING."""
        for i, (base_r, speed, alpha_base) in enumerate([
            (_RING_R,      1.0,  0.95),
            (_RING_R + 8,  0.7,  0.55),
            (_RING_R + 16, 0.5,  0.25),
        ]):
            phase = self._phase * speed + i * math.pi / 3
            scale = 1.0 + 0.10 * math.sin(phase)
            alpha = alpha_base * (0.65 + 0.35 * math.sin(phase))
            cr.set_source_rgba(*_IRON_BLUE, alpha)
            cr.set_line_width(2.0 - i * 0.4)
            cr.arc(cx, cy, base_r * scale, 0, 2 * math.pi)
            cr.stroke()

    def _draw_spin(self, cr, cx, cy) -> None:
        """Rotating arc segments — THINKING."""
        configs = [
            (_RING_R,      self._phase * 2.0,   1.5, 0.95),
            (_RING_R + 8,  -self._phase * 1.2,  1.0, 0.6),
            (_RING_R + 16, self._phase * 0.7,   0.6, 0.3),
        ]
        arc_len = math.pi * 0.65
        for radius, offset, lw, alpha in configs:
            cr.set_source_rgba(*_IRON_BLUE, alpha)
            cr.set_line_width(lw)
            cr.set_line_cap(1)
            cr.arc(cx, cy, radius, offset, offset + arc_len)
            cr.stroke()
        # centre dot
        cr.set_source_rgba(*_IRON_BLUE, 0.8)
        cr.arc(cx, cy, 4, 0, 2 * math.pi)
        cr.fill()

    def _draw_ripple(self, cr, cx, cy) -> None:
        """Expanding gold rings — SPEAKING."""
        for t in self._ripples:
            r = _RING_R + t * 32
            alpha = (1.0 - t) * 0.85
            cr.set_source_rgba(*_IRON_GOLD, alpha)
            cr.set_line_width(max(0.5, 2.2 * (1.0 - t)))
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
        cr.set_source_rgba(*_IRON_GOLD, 0.9)
        cr.arc(cx, cy, 5, 0, 2 * math.pi)
        cr.fill()

    def _draw_error_ring(self, cr, cx, cy) -> None:
        cr.set_source_rgba(*_IRON_RED, 0.9)
        cr.set_line_width(2.5)
        cr.arc(cx, cy, _RING_R, 0, 2 * math.pi)
        cr.stroke()
        cr.set_source_rgba(*_IRON_RED, 0.2)
        cr.arc(cx, cy, _RING_R + 7, 0, 2 * math.pi)
        cr.stroke()

    def _draw_label(self, cr, w, h) -> None:
        state_labels = {
            HUDState.LISTENING: "LISTENING",
            HUDState.THINKING:  "PROCESSING",
            HUDState.SPEAKING:  "J.A.R.V.I.S.",
            HUDState.ERROR:     "ERROR",
        }
        # State tag (small, blue)
        tag = state_labels.get(self._state, "")
        if tag:
            cr.set_source_rgba(*_IRON_BLUE, 0.7)
            cr.select_font_face("Monospace", 0, 1)  # bold
            cr.set_font_size(9)
            text_x = _RING_CX + _RING_R + 16
            cr.move_to(text_x, h / 2 - 10)
            cr.show_text(tag)

        # Main text (bright white)
        if self._text:
            col = _IRON_RED if self._state == HUDState.ERROR else _IRON_TEXT
            cr.set_source_rgba(*col, 0.95)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(14)
            text_x = _RING_CX + _RING_R + 16
            max_w  = w - text_x - 20
            label  = self._clip_text(cr, self._text, max_w)
            cr.move_to(text_x, h / 2 + 8)
            cr.show_text(label)

    @staticmethod
    def _clip_text(cr, text: str, max_px: float) -> str:
        suffix = "…"
        while text:
            if cr.text_extents(text + suffix).width <= max_px:
                return text + (suffix if len(text) < 80 else "")
            text = text[:-1]
        return ""


# ── thread-safe controller ────────────────────────────────────────────────────

class HUDController:
    def __init__(self, colors=None):
        self._hud: Optional[JarvisHUD] = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-hud")
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def _run(self) -> None:
        GLib.threads_init()
        self._hud = JarvisHUD()
        self._ready.set()
        Gtk.main()

    def listening(self, text: str = "") -> None:
        self._hud and self._hud.set_state(HUDState.LISTENING, text)

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


def load_theme_colors(config: dict | None = None):
    return None  # colors now hardcoded as Iron Man palette
