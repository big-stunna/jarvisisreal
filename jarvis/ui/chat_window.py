"""
J.A.R.V.I.S. chat window — minimal dark aesthetic.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint
from PyQt6.QtGui import QColor, QPainter, QPen, QKeySequence, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QFrame,
)

_BG     = "#111111"
_BG2    = "#1a1a1a"
_BORDER = "#2a2a2a"
_TEXT   = "#eeeeee"
_SUB    = "#555555"
_ACCENT = "#ffffff"
_MUTED  = "#333333"
_RED    = "#cc4444"

_SS = f"""
* {{ font-family: 'Inter', 'SF Pro Display', sans-serif; }}
QWidget {{ background: {_BG}; color: {_TEXT}; font-size: 13px; }}
QFrame#container {{ background: {_BG}; border: 1px solid {_BORDER}; border-radius: 14px; }}
QTextEdit#history {{
    background: {_BG};
    border: none;
    padding: 8px 4px;
    color: {_TEXT};
    font-size: 13px;
    line-height: 1.6;
}}
QScrollBar:vertical {{ background: {_BG}; width: 4px; border-radius: 2px; }}
QScrollBar::handle:vertical {{ background: {_BORDER}; border-radius: 2px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QLineEdit#input {{
    background: {_BG2};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 10px 14px;
    color: {_TEXT};
    font-size: 13px;
}}
QLineEdit#input:focus {{ border-color: #444444; }}
QPushButton#send_btn {{
    background: {_ACCENT};
    border: none;
    border-radius: 8px;
    color: {_BG};
    font-weight: 600;
    padding: 10px 18px;
    font-size: 12px;
    min-width: 56px;
}}
QPushButton#send_btn:hover {{ background: #dddddd; }}
QPushButton#send_btn:disabled {{ background: {_MUTED}; color: {_SUB}; }}
QPushButton#mic_btn {{
    background: {_BG2};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    color: {_SUB};
    padding: 10px;
    font-size: 15px;
    min-width: 40px;
    max-width: 40px;
}}
QPushButton#mic_btn:hover {{ border-color: #444; color: {_TEXT}; }}
QPushButton#mic_btn[active="true"] {{ border-color: {_RED}; color: {_RED}; }}
QPushButton#close_btn {{
    background: transparent;
    border: none;
    color: {_SUB};
    font-size: 15px;
    padding: 0 4px;
}}
QPushButton#close_btn:hover {{ color: {_TEXT}; }}
QLabel#title {{ color: {_TEXT}; font-size: 13px; font-weight: 600; background: transparent; }}
QLabel#status {{ color: {_SUB}; font-size: 11px; background: transparent; }}
"""


class _Worker(QThread):
    response_ready = pyqtSignal(str)
    error_signal   = pyqtSignal(str)
    def __init__(self, agent, text):
        super().__init__(); self._agent = agent; self._text = text
    def run(self):
        async def _c(): return (await self._agent.turn(self._text)).text
        try:    self.response_ready.emit(asyncio.run(_c()))
        except Exception as e: self.error_signal.emit(str(e))


class _VoiceWorker(QThread):
    transcribed  = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    def run(self):
        try:
            from jarvis.voice.stt import record_until_silence, transcribe
            self.transcribed.emit(transcribe(record_until_silence()).strip())
        except Exception as e: self.error_signal.emit(str(e))


class JarvisWindow(QWidget):
    def __init__(self):
        super().__init__()
        from jarvis.core.engine import AgentLoop
        from jarvis.tools.registry import ToolRegistry
        from jarvis.tools.system import register_system_tools
        from jarvis.tools.hyprland import register_hyprland_tools
        r = ToolRegistry()
        register_system_tools(r); register_hyprland_tools(r)
        self._agent = AgentLoop(registry=r)
        self._worker = None
        self._voice_worker = None
        self._thinking_timer = QTimer()
        self._thinking_timer.timeout.connect(self._tick_thinking)
        self._thinking_dots = 0
        self._opacity = 0.0
        self._build()
        self._center()
        self._fade_in()

    def _build(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(540, 520)
        self.setStyleSheet(_SS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame(self)
        container.setObjectName("container")
        outer.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # title bar
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Jarvis")
        title.setObjectName("title")
        bar.addWidget(title)
        self._status = QLabel("ready")
        self._status.setObjectName("status")
        bar.addWidget(self._status)
        bar.addStretch()
        close = QPushButton("✕")
        close.setObjectName("close_btn")
        close.clicked.connect(self._fade_out)
        bar.addWidget(close)
        layout.addLayout(bar)

        # separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_BORDER};")
        layout.addWidget(sep)

        # history
        self._history = QTextEdit()
        self._history.setObjectName("history")
        self._history.setReadOnly(True)
        layout.addWidget(self._history)

        # input row
        row = QHBoxLayout()
        row.setSpacing(8)
        self._mic = QPushButton("🎙")
        self._mic.setObjectName("mic_btn")
        self._mic.setProperty("active", "false")
        self._mic.clicked.connect(self._toggle_voice)
        row.addWidget(self._mic)
        self._input = QLineEdit()
        self._input.setObjectName("input")
        self._input.setPlaceholderText("Ask anything…")
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("send_btn")
        self._send_btn.clicked.connect(self._send)
        row.addWidget(self._send_btn)
        layout.addLayout(row)

        from PyQt6.QtGui import QShortcut
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._fade_out)

        self._drag_pos: Optional[QPoint] = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(_BG); c.setAlpha(0)
        p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(self.rect())
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def _center(self):
        s = QApplication.primaryScreen().availableGeometry()
        self.move((s.width() - self.width()) // 2, (s.height() - self.height()) // 3)

    def _fade_in(self):
        self._opacity = 0.0
        self._fit = QTimer()
        def _s():
            self._opacity = min(1.0, self._opacity + 0.1)
            self.setWindowOpacity(self._opacity)
            if self._opacity >= 1.0: self._fit.stop()
        self._fit.timeout.connect(_s)
        self._fit.start(16)
        self.setWindowOpacity(0.0)

    def _fade_out(self):
        self._fot = QTimer()
        def _s():
            self._opacity = max(0.0, self._opacity - 0.08)
            self.setWindowOpacity(self._opacity)
            if self._opacity <= 0.0: self._fot.stop(); self.close()
        self._fot.timeout.connect(_s)
        self._fot.start(16)

    def _append(self, who: str, text: str, muted: bool = False):
        color = _SUB if muted else _TEXT
        who_color = _SUB if who == "you" else _ACCENT
        html = (
            f'<span style="color:{who_color};font-weight:600">{who}</span>'
            f'&nbsp;&nbsp;<span style="color:{color}">{text}</span>'
        )
        self._history.append(html)
        self._history.append("")
        self._history.verticalScrollBar().setValue(self._history.verticalScrollBar().maximum())

    def _send(self):
        text = self._input.text().strip()
        if not text or self._worker: return
        self._input.clear()
        self._send_btn.setEnabled(False)
        self._append("you", text)
        self._status.setText("thinking…")
        self._thinking_dots = 0
        self._thinking_timer.start(500)
        self._worker = _Worker(self._agent, text)
        self._worker.response_ready.connect(self._on_response)
        self._worker.error_signal.connect(self._on_error)
        self._worker.finished.connect(lambda: setattr(self, '_worker', None))
        self._worker.start()

    def _on_response(self, text):
        self._thinking_timer.stop()
        self._send_btn.setEnabled(True)
        self._status.setText("ready")
        self._append("jarvis", text)

    def _on_error(self, err):
        self._thinking_timer.stop()
        self._send_btn.setEnabled(True)
        self._status.setText("error")
        self._append("error", err, muted=True)

    def _tick_thinking(self):
        self._thinking_dots = (self._thinking_dots + 1) % 4
        self._status.setText("thinking" + "." * self._thinking_dots)

    def _toggle_voice(self):
        if self._voice_worker and self._voice_worker.isRunning(): return
        self._mic.setProperty("active", "true")
        self._mic.style().unpolish(self._mic); self._mic.style().polish(self._mic)
        self._status.setText("listening…")
        self._voice_worker = _VoiceWorker()
        self._voice_worker.transcribed.connect(self._on_transcribed)
        self._voice_worker.error_signal.connect(self._on_error)
        self._voice_worker.finished.connect(self._voice_done)
        self._voice_worker.start()

    def _on_transcribed(self, text):
        if text: self._input.setText(text); self._send()

    def _voice_done(self):
        self._mic.setProperty("active", "false")
        self._mic.style().unpolish(self._mic); self._mic.style().polish(self._mic)
        self._voice_worker = None
        if not self._worker: self._status.setText("ready")


def launch():
    from jarvis.core.config import load_env
    load_env()
    app = QApplication.instance() or QApplication(sys.argv)
    w = JarvisWindow()
    w.show()
    w._input.setFocus()
    sys.exit(app.exec())
