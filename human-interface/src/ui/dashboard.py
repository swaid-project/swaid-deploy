import time
import psutil
from collections import deque
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

class WarningBanner(QWidget):
    """
    A persistent warning banner that appears at the top of the UI
    to signal hardware or connection failures.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.message = ""
        self.bg_color = QColor("#ff0038")
        self.setVisible(False)

    def show_warning(self, message, critical=True):
        self.message = message
        self.bg_color = QColor("#ff0038") if critical else QColor("#ff8500")
        self.setVisible(True)
        self.update()

    def hide_warning(self):
        self.setVisible(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw background
        painter.fillRect(self.rect(), self.bg_color)
        
        # Draw text
        painter.setPen(Qt.white)
        painter.setFont(QFont("Arial", 12, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, self.message)

class TestingOverlay(QWidget):
    """
    Semi-transparent diagnostics overlay for performance monitoring.
    Extracted from the legacy main.py.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.camera_fps = 0.0
        self.tracking_fps = 0.0
        self.live_fps = 0.0
        self.camera_to_ui_ms = 0.0
        self.detection_rate = 0.0
        self.hands_visible = 0
        self.ui_fps = 0.0

        self._ui_frame_times = deque(maxlen=60)
        self._cpu_percents = []
        self._ram_percent = 0.0
        self._proc_cpu = 0.0
        self._last_sys_update = 0.0
        self._process = psutil.Process()

    def update_stats(self, stats: dict):
        if self.parent():
            self.setGeometry(self.parent().rect())

        self.camera_fps = stats.get("camera_fps", self.camera_fps)
        self.tracking_fps = stats.get("tracking_fps", self.tracking_fps)
        self.live_fps = stats.get("live_fps", self.live_fps)
        self.camera_to_ui_ms = stats.get("camera_to_ui_ms", self.camera_to_ui_ms)
        self.detection_rate = stats.get("detection_rate", self.detection_rate)
        self.hands_visible = stats.get("hands_visible", self.hands_visible)

        now = time.monotonic()
        self._ui_frame_times.append(now)
        if len(self._ui_frame_times) >= 2:
            self.ui_fps = (len(self._ui_frame_times) - 1) / (self._ui_frame_times[-1] - self._ui_frame_times[0])

        if now - self._last_sys_update >= 0.5:
            self._last_sys_update = now
            self._cpu_percents = psutil.cpu_percent(percpu=True)
            self._ram_percent = psutil.virtual_memory().percent
            self._proc_cpu = self._process.cpu_percent()

        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        painter.fillRect(self.rect(), QColor(2, 2, 5, 180))

        painter.setPen(QColor("#00d9e8"))
        painter.setFont(QFont("Arial", 22, QFont.Bold))
        painter.drawText(QRectF(40, 20, w - 80, 40), Qt.AlignLeft, "SYSTEM DIAGNOSTICS")

        # Layout metrics in columns
        painter.setFont(QFont("Monospace", 12))
        painter.setPen(Qt.white)
        
        y = 80
        metrics = [
            f"Camera FPS: {self.camera_fps:.1f}",
            f"Tracking FPS: {self.tracking_fps:.1f}",
            f"UI FPS: {self.ui_fps:.1f}",
            f"Latency: {self.camera_to_ui_ms:.1f}ms",
            f"Detection: {self.detection_rate*100:.1f}%",
            f"CPU: {self._proc_cpu:.1f}%",
            f"RAM: {self._ram_percent:.1f}%"
        ]
        
        for m in metrics:
            painter.drawText(40, y, m)
            y += 25
