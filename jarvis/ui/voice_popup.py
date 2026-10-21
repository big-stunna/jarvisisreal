"""
J.A.R.V.I.S. voice popup — top-right, stays open, loops until dismissed.
Close triggers: ESC, or saying "ok close" / "thanks" / "goodbye" / "that's all".
"""
from __future__ import annotations

import asyncio
import math
import sys

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)

_BG     = "#111111"
_BG2    = "#1a1a1a"
_BORDER = "#2a2a2a"
_TEXT   = "#eeeeee"
_SUB    = "#555555"
_MUTED  = "#333333"
_RED    = "#cc4444"

_W, _H  = 320, 110
_MARGIN = 20   # distance from screen edges

_CLOSE_PHRASES = {
    "ok close", "okay close", "close", "goodbye", "good bye",
    "thanks", "thank you", "that's all", "thats all",
    "stop listening", "dismiss", "go away", "exit",
}


def _is_close_phrase(text: str) -> bool:
    t = text.lower().strip().rstrip(".,!?")
    return t in _CLOSE_PHRASES or any(t.startswith(p) for p in _CLOSE_PHRASES)


class _Orb(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self._phase = 0.0
        self._state = "idle"
        self._t = QTimer()
        self._t.timeout.connect(self._tick)
        self._t.start(16)

    def set_state(self, s: str):
        self._state = s

    def _tick(self):
        speed = {"listening": 0.03, "thinking": 0.09, "speaking": 0.05, "idle": 0.015}.get(self._state, 0.03)
        self._phase = (self._phase + speed) % (2 * math.pi)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = 16, 16

        if self._state == "idle":
            r = 5
            c = QColor(_SUB); c.setAlpha(160)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(c)
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        elif self._state == "listening":
            scale = 1.0 + 0.22 * math.sin(self._phase)
            r = int(8 * scale)
            alpha = int(170 + 70 * math.sin(self._phase))
            c = QColor("#ffffff"); c.setAlpha(alpha)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(c)
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        elif self._state == "thinking":
            for i in range(3):
                angle = self._phase + i * (2 * math.pi / 3)
                x = cx + int(10 * math.cos(angle))
                y = cy + int(10 * math.sin(angle))
                fade = 0.35 + 0.65 * ((math.sin(self._phase * 2 + i) + 1) / 2)
                c = QColor("#ffffff"); c.setAlpha(int(190 * fade))
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(c)
                p.drawEllipse(x - 3, y - 3, 6, 6)

        elif self._state == "speaking":
            bw, gap = 4, 3
            total = 3 * bw + 2 * gap
            x0 = cx - total // 2
            for i in range(3):
                h = int(5 + 10 * abs(math.sin(self._phase * 1.6 + i * 1.2)))
                c = QColor("#ffffff"); c.setAlpha(200)
                p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
                bx = x0 + i * (bw + gap)
                p.drawRoundedRect(bx, cy - h // 2, bw, h, 2, 2)

        p.end()


class _VoiceWorker(QThread):
    transcribed = pyqtSignal(str)
    error       = pyqtSignal(str)
    def run(self):
        try:
            from jarvis.voice.stt import record_until_silence, transcribe
            self.transcribed.emit(transcribe(record_until_silence()).strip())
        except Exception as e:
            self.error.emit(str(e))


class _BrainWorker(QThread):
    answered = pyqtSignal(str)
    error    = pyqtSignal(str)
    def __init__(self, agent, text):
        super().__init__(); self._agent = agent; self._text = text
    def run(self):
        async def _c(): return (await self._agent.turn(self._text)).text
        try:    self.answered.emit(asyncio.run(_c()))
        except Exception as e: self.error.emit(str(e))


class _TTSWorker(QThread):
    done = pyqtSignal()
    def __init__(self, text, voice):
        super().__init__(); self._text = text; self._voice = voice
    def run(self):
        try:    asyncio.run(__import__('jarvis.voice.tts', fromlist=['speak_async']).speak_async(self._text, voice=self._voice))
        except: pass
        self.done.emit()


class VoicePopup(QWidget):
    def __init__(self, tts_voice="en-GB-RyanNeural"):
        super().__init__()
        self._voice = tts_voice
        self._closing = False
        from jarvis.core.engine import AgentLoop
        from jarvis.tools.registry import ToolRegistry
        from jarvis.tools.system import register_system_tools
        from jarvis.tools.hyprland import register_hyprland_tools
        r = ToolRegistry()
        register_system_tools(r); register_hyprland_tools(r)
        self._agent = AgentLoop(registry=r)
        self._build()
        self._position()
        self._fade_in()
        # start first listen after window is shown
        QTimer.singleShot(300, self._listen)

    def _build(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Don't steal focus from other windows
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setFixedSize(_W, _H)
        self.setStyleSheet("* { font-family: 'Inter', 'SF Pro Display', sans-serif; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # top row: orb + status
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)
        self._orb = _Orb()
        top.addWidget(self._orb, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._status = QLabel("Starting…")
        self._status.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: 500; background: transparent;")
        top.addWidget(self._status)
        top.addStretch()
        layout.addLayout(top)

        # last response
        self._reply = QLabel("")
        self._reply.setStyleSheet(f"color: {_SUB}; font-size: 11px; background: transparent;")
        self._reply.setWordWrap(True)
        self._reply.setMaximumHeight(40)
        layout.addWidget(self._reply)

        # ESC to close (even without focus, bind globally via shortcut on window)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._dismiss)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(_BG); c.setAlpha(240)
        p.setBrush(c)
        p.setPen(QPen(QColor(_BORDER), 1))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        p.end()

    def _position(self):
        s = QApplication.primaryScreen().availableGeometry()
        self.move(s.width() - _W - _MARGIN, _MARGIN + 40)

    def _fade_in(self):
        self._opacity = 0.0
        self.setWindowOpacity(0.0)
        t = QTimer(self)
        def _s():
            self._opacity = min(1.0, self._opacity + 0.1)
            self.setWindowOpacity(self._opacity)
            if self._opacity >= 1.0: t.stop()
        t.timeout.connect(_s)
        t.start(16)

    def _dismiss(self):
        if self._closing: return
        self._closing = True
        self._orb.set_state("idle")
        self._status.setText("Goodbye.")
        t = QTimer(self)
        def _s():
            self._opacity = max(0.0, self._opacity - 0.08)
            self.setWindowOpacity(self._opacity)
            if self._opacity <= 0.0: t.stop(); self.close(); QApplication.instance().quit()
        t.timeout.connect(_s)
        t.start(16)

    def _listen(self):
        if self._closing: return
        self._orb.set_state("listening")
        self._status.setText("Listening…")
        self._vw = _VoiceWorker()
        self._vw.transcribed.connect(self._on_transcribed)
        self._vw.error.connect(self._on_error)
        self._vw.start()

    def _on_transcribed(self, text: str):
        if self._closing: return
        if not text:
            self._status.setText("Didn't catch that.")
            QTimer.singleShot(800, self._listen)
            return
        if _is_close_phrase(text):
            self._dismiss()
            return
        self._reply.setText(f'"{text}"')
        self._orb.set_state("thinking")
        self._status.setText("Thinking…")
        self._bw = _BrainWorker(self._agent, text)
        self._bw.answered.connect(self._on_answered)
        self._bw.error.connect(self._on_error)
        self._bw.start()

    def _on_answered(self, reply: str):
        if self._closing: return
        display = reply if len(reply) <= 90 else reply[:87] + "…"
        self._status.setText(display)
        self._reply.setText("")
        self._orb.set_state("speaking")
        self._tw = _TTSWorker(reply, self._voice)
        self._tw.done.connect(self._after_speaking)
        self._tw.start()

    def _after_speaking(self):
        if self._closing: return
        # Brief pause then listen again
        QTimer.singleShot(600, self._listen)

    def _on_error(self, err: str):
        if self._closing: return
        self._status.setText("Error — try again")
        self._reply.setText(err[:60])
        self._orb.set_state("idle")
        QTimer.singleShot(2000, self._listen)


def launch():
    from jarvis.core.config import load_env, load_config
    load_env()
    voice = load_config().get("audio", {}).get("tts_voice", "en-GB-RyanNeural")
    app = QApplication.instance() or QApplication(sys.argv)
    p = VoicePopup(tts_voice=voice)
    p.show()
    sys.exit(app.exec())
