"""
J.A.R.V.I.S. Siri-style voice popup.
Launched by SUPER+SHIFT+V. Listens, shows answer, speaks TTS, auto-closes.
"""
from __future__ import annotations

import asyncio
import math
import sys
import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QRect
from PyQt6.QtGui import QColor, QPainter, QPen, QFont
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel

_BG    = "#050e1a"
_BLUE  = "#00d4ff"
_GOLD  = "#e2be8a"
_TEXT  = "#c8eaf5"
_DIM   = "#4a7a8a"
_RED   = "#e25d6c"

_W, _H = 480, 140


# ── ring animation widget ─────────────────────────────────────────────────────

class _RingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self._phase = 0.0
        self._state = "listening"  # listening | thinking | speaking
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_state(self, state: str):
        self._state = state
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.07) % (2 * math.pi)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = 32, 32, 20

        if self._state == "listening":
            for i, (base, speed, alpha) in enumerate([
                (r,      1.0, 220),
                (r+7,    0.7, 130),
                (r+14,   0.5, 60),
            ]):
                phase = self._phase * speed + i * math.pi / 3
                scale = 1.0 + 0.12 * math.sin(phase)
                a = int(alpha * (0.65 + 0.35 * math.sin(phase)))
                col = QColor(_BLUE); col.setAlpha(a)
                pen = QPen(col, 2.0 - i * 0.4)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                rad = int(base * scale)
                p.drawEllipse(cx - rad, cy - rad, rad * 2, rad * 2)

        elif self._state == "thinking":
            arc_len = int(0.65 * 180 * 16)
            for i, (base, speed, alpha, lw) in enumerate([
                (r,    2.0, 240, 2.5),
                (r+7,  1.2, 150, 1.5),
                (r+14, 0.7, 80,  1.0),
            ]):
                offset = int((self._phase * speed) * 180 / math.pi * 16)
                col = QColor(_BLUE); col.setAlpha(alpha)
                p.setPen(QPen(col, lw))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(cx - base, cy - base, base * 2, base * 2, offset, arc_len)

        elif self._state == "speaking":
            # gold ripple
            for t_val in [self._phase % 1.0, (self._phase + 0.3) % 1.0]:
                rad = int(r + t_val * 24)
                a = int((1.0 - t_val) * 200)
                col = QColor(_GOLD); col.setAlpha(a)
                p.setPen(QPen(col, max(0.5, 2.0 * (1.0 - t_val))))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(cx - rad, cy - rad, rad * 2, rad * 2)
            col = QColor(_GOLD); col.setAlpha(200)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(cx - 5, cy - 5, 10, 10)

        p.end()


# ── worker threads ────────────────────────────────────────────────────────────

class _VoiceWorker(QThread):
    transcribed = pyqtSignal(str)
    error       = pyqtSignal(str)

    def run(self):
        try:
            from jarvis.voice.stt import record_until_silence, transcribe
            wav = record_until_silence()
            text = transcribe(wav).strip()
            self.transcribed.emit(text or "")
        except Exception as e:
            self.error.emit(str(e))


class _BrainWorker(QThread):
    answered = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, text: str):
        super().__init__()
        self._text = text

    def run(self):
        async def _call():
            from jarvis.core.engine import AgentLoop
            loop = AgentLoop()
            r = await loop.turn(self._text)
            return r.text
        try:
            self.answered.emit(asyncio.run(_call()))
        except Exception as e:
            self.error.emit(str(e))


class _TTSWorker(QThread):
    done = pyqtSignal()

    def __init__(self, text: str, voice: str):
        super().__init__()
        self._text = text
        self._voice = voice

    def run(self):
        try:
            asyncio.run(self._speak())
        except Exception:
            pass
        self.done.emit()

    async def _speak(self):
        from jarvis.voice.tts import speak_async
        await speak_async(self._text, voice=self._voice)


# ── popup window ──────────────────────────────────────────────────────────────

class VoicePopup(QWidget):
    def __init__(self, tts_voice: str = "en-GB-RyanNeural"):
        super().__init__()
        self._voice = tts_voice
        self._build_ui()
        self._position()
        self._start_listening()

    def _build_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_W, _H)

        self.setStyleSheet(f"""
            QWidget {{ background: transparent; }}
            QLabel#status_label {{
                color: {_BLUE};
                font-family: 'JetBrains Mono', Monospace;
                font-size: 10px;
                letter-spacing: 2px;
                background: transparent;
            }}
            QLabel#text_label {{
                color: {_TEXT};
                font-family: 'JetBrains Mono', Monospace;
                font-size: 13px;
                background: transparent;
                qproperty-wordWrap: true;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(8)

        top_row = QVBoxLayout()

        self._ring = _RingWidget()
        top_row.addWidget(self._ring, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._status_label = QLabel("LISTENING")
        self._status_label.setObjectName("status_label")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self._status_label)

        layout.addLayout(top_row)

        self._text_label = QLabel("")
        self._text_label.setObjectName("text_label")
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setWordWrap(True)
        layout.addWidget(self._text_label)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(_BG)
        col.setAlpha(230)
        p.setBrush(col)
        pen = QPen(QColor(_BLUE), 1)
        pen.setColor(QColor(0, 212, 255, 80))
        p.setPen(pen)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 16, 16)
        p.end()

    def _position(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - _W) // 2,
            screen.height() - _H - 80,
        )

    def _start_listening(self):
        self._ring.set_state("listening")
        self._status_label.setText("LISTENING")
        self._vw = _VoiceWorker()
        self._vw.transcribed.connect(self._on_transcribed)
        self._vw.error.connect(self._on_error)
        self._vw.start()

    def _on_transcribed(self, text: str):
        if not text:
            self.close()
            return
        self._text_label.setText(f'"{text}"')
        self._ring.set_state("thinking")
        self._status_label.setText("THINKING")
        self._bw = _BrainWorker(text)
        self._bw.answered.connect(self._on_answered)
        self._bw.error.connect(self._on_error)
        self._bw.start()

    def _on_answered(self, reply: str):
        # Clip for display
        display = reply if len(reply) <= 120 else reply[:117] + "…"
        self._text_label.setText(display)
        self._ring.set_state("speaking")
        self._status_label.setText("J.A.R.V.I.S.")
        self._tw = _TTSWorker(reply, self._voice)
        self._tw.done.connect(self._on_spoken)
        self._tw.start()

    def _on_spoken(self):
        # Linger 1.5s after speaking then close
        QTimer.singleShot(1500, self.close)

    def _on_error(self, err: str):
        self._text_label.setText(err)
        self._status_label.setText("ERROR")
        self._ring.set_state("listening")
        QTimer.singleShot(3000, self.close)


# ── entry ─────────────────────────────────────────────────────────────────────

def launch():
    from jarvis.core.config import load_env, load_config
    load_env()
    cfg = load_config().get("audio", {})
    voice = cfg.get("tts_voice", "en-GB-RyanNeural")

    app = QApplication.instance() or QApplication(sys.argv)
    popup = VoicePopup(tts_voice=voice)
    popup.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    launch()
