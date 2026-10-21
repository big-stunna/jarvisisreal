"""
J.A.R.V.I.S. voice popup — minimal dark aesthetic.
"""
from __future__ import annotations

import asyncio
import math
import sys

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QFontMetrics
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel

_BG      = "#111111"
_ACCENT  = "#ffffff"
_SUB     = "#555555"
_TEXT    = "#eeeeee"
_MUTED   = "#444444"

_W, _H = 400, 120


class _Orb(QWidget):
    """Single breathing circle — smooth, no rings, just one dot."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self._phase = 0.0
        self._state = "listening"
        self._t = QTimer()
        self._t.timeout.connect(self._tick)
        self._t.start(16)

    def set_state(self, s: str):
        self._state = s

    def _tick(self):
        speed = {"listening": 0.03, "thinking": 0.08, "speaking": 0.05}.get(self._state, 0.03)
        self._phase = (self._phase + speed) % (2 * math.pi)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = 20, 20

        if self._state == "listening":
            # single soft pulse
            scale = 1.0 + 0.18 * math.sin(self._phase)
            r = int(10 * scale)
            alpha = int(180 + 60 * math.sin(self._phase))
            c = QColor(_ACCENT); c.setAlpha(alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        elif self._state == "thinking":
            # three small dots rotating
            for i in range(3):
                angle = self._phase + i * (2 * math.pi / 3)
                x = cx + int(12 * math.cos(angle))
                y = cy + int(12 * math.sin(angle))
                fade = 0.4 + 0.6 * ((math.sin(self._phase * 2 + i) + 1) / 2)
                c = QColor(_ACCENT); c.setAlpha(int(200 * fade))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawEllipse(x - 3, y - 3, 6, 6)

        elif self._state == "speaking":
            # bars equalizer style (3 bars)
            bar_w = 5
            gap   = 4
            total = 3 * bar_w + 2 * gap
            x0    = cx - total // 2
            for i in range(3):
                h = int(6 + 12 * abs(math.sin(self._phase * 1.5 + i * 1.1)))
                c = QColor(_ACCENT); c.setAlpha(200)
                p.setBrush(c)
                p.setPen(Qt.PenStyle.NoPen)
                bx = x0 + i * (bar_w + gap)
                p.drawRoundedRect(bx, cy - h // 2, bar_w, h, 2, 2)

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
    def __init__(self, text):
        super().__init__(); self._text = text
    def run(self):
        async def _c():
            from jarvis.core.engine import AgentLoop
            return (await AgentLoop().turn(self._text)).text
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
        self._opacity = 0.0
        self._fade_in()
        self._build()
        self._position()
        self._start_listening()

    def _build(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_W, _H)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(12)

        row = QWidget()
        from PyQt6.QtWidgets import QHBoxLayout
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(14)

        self._orb = _Orb()
        hl.addWidget(self._orb, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._label = QLabel("Listening…")
        self._label.setStyleSheet(f"color: {_TEXT}; font-size: 14px; font-family: 'Inter', 'SF Pro Display', sans-serif; background: transparent;")
        self._label.setWordWrap(True)
        hl.addWidget(self._label)

        layout.addWidget(row)

        self._sub = QLabel("")
        self._sub.setStyleSheet(f"color: {_SUB}; font-size: 11px; font-family: 'Inter', sans-serif; background: transparent;")
        self._sub.setWordWrap(True)
        layout.addWidget(self._sub)

    def _fade_in(self):
        self._opacity = 0.0
        self._ft = QTimer()
        def _step():
            self._opacity = min(1.0, self._opacity + 0.08)
            self.setWindowOpacity(self._opacity)
            if self._opacity >= 1.0:
                self._ft.stop()
        self._ft.timeout.connect(_step)
        self._ft.start(16)
        self.setWindowOpacity(0.0)

    def _fade_out(self):
        self._fo = QTimer()
        def _step():
            self._opacity = max(0.0, self._opacity - 0.06)
            self.setWindowOpacity(self._opacity)
            if self._opacity <= 0.0:
                self._fo.stop()
                self.close()
        self._fo.timeout.connect(_step)
        self._fo.start(16)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(_BG); c.setAlpha(245)
        p.setBrush(c)
        p.setPen(QPen(QColor(_MUTED), 0.5))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 14, 14)
        p.end()

    def _position(self):
        s = QApplication.primaryScreen().availableGeometry()
        self.move((s.width() - _W) // 2, s.height() - _H - 72)

    def _start_listening(self):
        self._orb.set_state("listening")
        self._label.setText("Listening…")
        self._vw = _VoiceWorker()
        self._vw.transcribed.connect(self._on_transcribed)
        self._vw.error.connect(self._on_error)
        self._vw.start()

    def _on_transcribed(self, text):
        if not text: self._fade_out(); return
        self._sub.setText(f'"{text}"')
        self._label.setText("Thinking…")
        self._orb.set_state("thinking")
        self._bw = _BrainWorker(text)
        self._bw.answered.connect(self._on_answered)
        self._bw.error.connect(self._on_error)
        self._bw.start()

    def _on_answered(self, reply):
        display = reply if len(reply) <= 100 else reply[:97] + "…"
        self._label.setText(display)
        self._sub.setText("")
        self._orb.set_state("speaking")
        self._tw = _TTSWorker(reply, self._voice)
        self._tw.done.connect(lambda: QTimer.singleShot(1200, self._fade_out))
        self._tw.start()

    def _on_error(self, err):
        self._label.setText(err)
        self._orb.set_state("listening")
        QTimer.singleShot(3000, self._fade_out)


def launch():
    from jarvis.core.config import load_env, load_config
    load_env()
    voice = load_config().get("audio", {}).get("tts_voice", "en-GB-RyanNeural")
    app = QApplication.instance() or QApplication(sys.argv)
    p = VoicePopup(tts_voice=voice)
    p.show()
    sys.exit(app.exec())
