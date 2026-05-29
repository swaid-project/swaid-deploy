"""
Interface.py — MainWindow for SWAID-ESIS.

Draws the radial note-selector, Chladni plate, animated waves, hand-tracking
overlay, and FEUP logo.  Waves and glow intensity are driven by embedded
Chladni configs (no external config folder).

Keyboard shortcuts (handled here via keyPressEvent):
    M  —  emit settings_requested signal (opens camera dialog in main.py)
    I  —  emit testing_toggle signal (shows/hides diagnostics overlay)
    F  —  hold for blue-hand / sharp mode (♯)
"""
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget


_DEFAULT_FREQUENCIES = [100, 150, 191, 220, 250, 300]


def _default_channels(freq):
    return [
        {"amplitude": 0.85, "channel": 1, "frequency_hz": freq, "phase_deg": 0, "x": 0.053, "y": 0.036},
        {"amplitude": 0.85, "channel": 2, "frequency_hz": freq, "phase_deg": 90, "x": 0.947, "y": 0.036},
        {"amplitude": 0.85, "channel": 3, "frequency_hz": freq, "phase_deg": 180, "x": 0.053, "y": 0.964},
        {"amplitude": 0.85, "channel": 4, "frequency_hz": freq, "phase_deg": 270, "x": 0.947, "y": 0.964},
    ]


def _load_configs():
    return [
        {
            "display_name": f"CHLADNI_{freq}",
            "hardware_config": {"channels": _default_channels(freq)},
            "id": idx,
        }
        for idx, freq in enumerate(_DEFAULT_FREQUENCIES)
    ]


def _config_channels(config):
    return config.get("hardware_config", {}).get("channels", []) if config else []


def _load_logo():
    path = Path(__file__).parent / "assets" / "LogoFeup.tif"
    if not path.exists():
        return None
    try:
        img = Image.open(path).convert("RGB")
        arr = np.array(img, dtype=np.uint8)
        h, w = arr.shape[:2]
        qimg = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888).copy()
        return QPixmap.fromImage(qimg)
    except Exception:
        return None


class MainWindow(QWidget):
    settings_requested = Signal()
    testing_toggle = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mockup Interativo - Controlo Vibroacustico")
        self.resize(1280, 720)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.BlankCursor)

        # Estados de animação e interação
        self.t = 0.0
        self.frequency = 2.7
        self.wave_amplitude = 0.0
        self.selected_section = 0
        self.hover_section = -1
        self.mouse_pos = QPointF(self.width() / 2, self.height() / 2)
        self.external_left_hand = None
        self.external_right_hand = None
        self.external_hands_time = 0.0
        # Tempo que a interface mantém a última mão recebida se a câmera falhar um frame.
        # Aumenta se a mão piscar/desaparecer; diminui se parecer atrasada.
        self.external_hands_hold = 0.30
        
        self.image_mode = False
        self.center_live_image = None
        self.blue_hand_closed = False
        self.sharp_mode_until = 0.0
        
        # Estados do seletor circular (dwell)
        self.dwell_section = -1
        self.dwell_started_at = 0.0
        self.dwell_progress = 0.0
        # Tempo em segundos para selecionar uma fatia quando o indicador fica parado nela.
        self.dwell_duration = 0.7

        # Estado do botão de imagem
        self.image_btn_hover = False
        self.image_btn_rect = QRectF()

        # Configurações visuais do seletor
        # Muda estes valores para aumentar/diminuir o círculo principal e o disco central.
        self.selector_radius_scale = 0.39
        self.center_plate_radius_scale = 0.265

        # Dados e Cores
        self.sector_labels = ["E", "D", "C", "B", "A", "F"]
        self.image_labels = ["D#", "F#", "G#", "A#", "G", "C#"]
        
        self.section_colors = [
            QColor("#00d9e8"), QColor("#7d3c98"), QColor("#00ff25"),
            QColor("#ff8500"), QColor("#ffe100"), QColor("#ff0038"),
        ]
        self.image_colors = [
            QColor("#00ff25"), QColor("#ff8500"), QColor("#ffe100"),
            QColor("#ff0038"), QColor("#00d9e8"), QColor("#7d3c98"),
        ]

        # Timer de Animação
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(16)

        self.configs = _load_configs()
        self._logo = _load_logo()

    def current_config(self):
        if not self.configs:
            return {}
        return self.configs[self.selected_section % len(self.configs)]

    def set_tracked_hands(self, left_hand=None, right_hand=None, blue_hand_closed=False, cursor_point=None):
        self.external_left_hand = left_hand
        self.external_right_hand = right_hand
        self.external_hands_time = time.monotonic()
        self.blue_hand_closed = blue_hand_closed

        if cursor_point is not None:
            self.mouse_pos = cursor_point
            self.hover_section = self.section_at(self.mouse_pos)
            self.image_btn_hover = self.image_btn_rect.contains(self.mouse_pos)

        self.update()

    def set_center_live_image(self, image):
        self.center_live_image = image
        self.update()

    def update_animation(self):
        self.t += 0.05
        channels = _config_channels(self.current_config())
        if channels:
            avg_amp = sum(ch["amplitude"] for ch in channels) / len(channels)
            avg_freq = sum(ch["frequency_hz"] for ch in channels) / len(channels)
        else:
            avg_amp = 1.0
            avg_freq = 200.0
        self.wave_amplitude = avg_amp * (0.50 + 0.45 * abs(math.sin(self.t * 0.9)))
        self.frequency = avg_freq
        self.update_dwell_selection()
        self.update()

    def update_dwell_selection(self):
        section = self.section_at(self.mouse_pos)
        now = time.monotonic()

        if section < 0:
            self.dwell_section = -1
            self.dwell_progress = 0.0
            return

        needs_selection = section != self.selected_section or (self.blue_hand_closed and not self.using_image_mode())
        if not needs_selection or section != self.dwell_section:
            self.dwell_section = section
            self.dwell_started_at = now
            self.dwell_progress = 0.0
            return

        self.dwell_progress = min(1.0, (now - self.dwell_started_at) / self.dwell_duration)
        if self.dwell_progress >= 1.0:
            self.selected_section = section
            channels = _config_channels(self.current_config())
            if channels:
                self.frequency = sum(ch["frequency_hz"] for ch in channels) / len(channels)
            if self.blue_hand_closed:
                self.sharp_mode_until = now + 1.5
            self.dwell_progress = 0.0

    def mouseMoveEvent(self, event):
        self.mouse_pos = QPointF(event.position())
        self.hover_section = self.section_at(self.mouse_pos)
        self.image_btn_hover = self.image_btn_rect.contains(self.mouse_pos)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.image_btn_rect.contains(event.position()):
            self.image_mode = not self.image_mode
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_M and not event.isAutoRepeat():
            self.settings_requested.emit()
            return
        if event.key() == Qt.Key_I and not event.isAutoRepeat():
            self.testing_toggle.emit()
            return
        if event.key() == Qt.Key_F and not event.isAutoRepeat():
            self.blue_hand_closed = True
            self.update()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_F and not event.isAutoRepeat():
            self.blue_hand_closed = False
            self.update()
            return
        super().keyReleaseEvent(event)

    def leaveEvent(self, event):
        self.hover_section = -1
        self.image_btn_hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        base_radius = min(w, h)

        painter.fillRect(self.rect(), QColor("#020203"))

        selector_radius = base_radius * self.selector_radius_scale
        center_radius = base_radius * self.center_plate_radius_scale
        preview_radius = max(100, min(58, base_radius * 0.07))

        # Image button → top-right corner
        image_button_width = 88
        image_button_x = w - image_button_width - 16
        image_button_y = 16

        # Preview disc (Chladni) → bottom-right corner
        preview_x = w - preview_radius - 20
        preview_y = h - preview_radius - 20

        # Waves at 30° from top-left corner, entering the circle
        channels = _config_channels(self.current_config())
        painter.save()
        painter.rotate(30)
        self.draw_wave(painter, 0, 0, length=600, channels=channels)
        painter.restore()

        self.draw_selector(painter, cx, cy, selector_radius)
        self.draw_reference_center(painter, cx, cy, center_radius)
        self.draw_reference_disc(painter, preview_x, preview_y, preview_radius)
        self.draw_hands(painter, 250, h - 150, w - 300, h - 150)
        self.draw_image_button(painter, image_button_x, image_button_y)

        # FEUP logo → bottom-left corner
        if self._logo and not self._logo.isNull():
            logo_h = 100
            logo_w = int(logo_h * self._logo.width() / self._logo.height())
            painter.drawPixmap(16, h - logo_h - 16, logo_w, logo_h, self._logo)

        # Keyboard shortcut hints — bottom centre
        hint_y = h - 22
        hints = [("[M]", "Câmeras"), ("[I]", "Diagnósticos"), ("[F]", "♯ Modo")]
        total_w = 0
        key_font = QFont("Arial", 11, QFont.Bold)
        lbl_font = QFont("Arial", 11)
        fm_key = painter.fontMetrics()
        painter.setFont(key_font)
        fm_key = painter.fontMetrics()
        painter.setFont(lbl_font)
        fm_lbl = painter.fontMetrics()
        sep_gap = 18
        parts = []
        for key, label in hints:
            kw = fm_key.horizontalAdvance(key)
            lw = fm_lbl.horizontalAdvance("  " + label)
            parts.append((key, label, kw, lw))
            total_w += kw + lw
        total_w += sep_gap * (len(hints) - 1)
        hx = (w - total_w) / 2
        for key, label, kw, lw in parts:
            painter.setFont(key_font)
            painter.setPen(QColor("#00d9e8"))
            painter.drawText(QRectF(hx, hint_y - 14, kw, 18), Qt.AlignLeft | Qt.AlignVCenter, key)
            hx += kw
            painter.setFont(lbl_font)
            painter.setPen(QColor("#3a4a5a"))
            painter.drawText(QRectF(hx, hint_y - 14, lw, 18), Qt.AlignLeft | Qt.AlignVCenter, "  " + label)
            hx += lw + sep_gap

    def section_at(self, pos):
        cx, cy = self.width() / 2, self.height() / 2
        size = min(self.width(), self.height())
        outer_r = size * 0.36 + 22
        inner_r = size * 0.235

        dx, dy = pos.x() - cx, pos.y() - cy
        distance = math.hypot(dx, dy)
        if distance < inner_r or distance > outer_r:
            return -1

        angle = (-math.degrees(math.atan2(dy, dx)) + 360) % 360
        return int(angle // 60) % 6

    def draw_wave(self, painter, x0, y0, length=485, channels=None):
        wave_count = 4
        spacing = 44
        speed = self.t * 4.0
        base_amplitude_px = 20 + 15 * self.wave_amplitude
        colors = [
            QColor("#ff3a9e"), QColor("#cde70b"),
            QColor("#00eaff"), QColor("#ff8500"),
        ]

        # Derive per-channel params from JSON config, or fall back to defaults
        if channels and len(channels) >= wave_count:
            ch_amplitudes = [ch["amplitude"] for ch in channels[:wave_count]]
            # Map audio frequency to visual spatial frequency
            ch_wave_numbers = [0.025 + 0.060 * (ch["frequency_hz"] / 500.0)
                               for ch in channels[:wave_count]]
            ch_phases = [math.radians(ch["phase_deg"]) for ch in channels[:wave_count]]
        else:
            ch_amplitudes = [1.0, 1.0, 1.0, 1.0]
            ch_wave_numbers = [0.055, 0.055, 0.055, 0.055]
            ch_phases = [0.0, math.pi / 2, math.pi, math.pi * 1.5]

        for wave_index in range(wave_count):
            baseline = y0 + (wave_index - 1.5) * spacing
            phase = ch_phases[wave_index]
            wave_number = ch_wave_numbers[wave_index]
            amplitude = base_amplitude_px * ch_amplitudes[wave_index]
            color = colors[wave_index]
            points = []

            for x in range(0, length, 3):
                y = math.sin(x * wave_number + speed + phase) * amplitude
                points.append(QPointF(x0 + x, baseline + y))

            glow = QColor(color)
            glow.setAlpha(42)
            painter.setPen(QPen(glow, 10, Qt.SolidLine, Qt.RoundCap))
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i + 1])

            line_color = QColor(color)
            line_color.setAlpha(210)
            painter.setPen(QPen(line_color, 3, Qt.SolidLine, Qt.RoundCap))
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i + 1])

            marker_x = (self.t * 68 + wave_index * 36) % length
            marker_y = baseline + math.sin(marker_x * wave_number + speed + phase) * amplitude
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawEllipse(QPointF(x0 + marker_x, marker_y), 6, 6)

            painter.setPen(QColor(255, 255, 255, 170))
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.drawText(QRectF(x0 - 38, baseline - 10, 32, 20), Qt.AlignRight, f"{wave_index * 90}")

    def draw_selector(self, painter, cx, cy, radius):
        channels = _config_channels(self.current_config())
        avg_amplitude = (sum(ch["amplitude"] for ch in channels) / len(channels)) if channels else 1.0
        glow_strength = int(45 + 205 * self.wave_amplitude * avg_amplitude)
        glow = QRadialGradient(QPointF(cx, cy), radius + 70)
        colors = self.image_colors if self.using_image_mode() else self.section_colors
        glow_color = QColor(colors[self.selected_section])
        glow_color.setAlpha(glow_strength)
        
        glow.setColorAt(0.45, QColor(0, 0, 0, 0))
        glow.setColorAt(0.76, glow_color)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setBrush(glow)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), radius + 70, radius + 70)

        start_angle = 0
        span = 60 * 16
        for i, color in enumerate(colors):
            outer_r = radius + 20 if i in (self.selected_section, self.hover_section) else radius
            rect = QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)

            fill = QColor(color)
            fill.setAlpha(245 if i == self.selected_section else 195)
            if i == self.hover_section:
                fill = fill.lighter(135)

            painter.setBrush(fill)
            painter.setPen(Qt.NoPen)
            painter.drawPie(rect, start_angle + i * span, span)

        painter.setBrush(QColor("#1b1b1d"))
        painter.setPen(QPen(QColor("#303035"), 4))
        inner = radius * 0.72
        painter.drawEllipse(QPointF(cx, cy), inner, inner)

        painter.setFont(QFont("Arial", 34, QFont.Bold))
        for i in range(6):
            label = self.image_labels[i] if self.using_image_mode() else self.sector_labels[i]
            angle = math.radians(-(i * 60 + 30))
            tx = cx + math.cos(angle) * radius * 0.86
            ty = cy + math.sin(angle) * radius * 0.86
            painter.setPen(QColor("#050505"))
            painter.drawText(QRectF(tx - 36, ty - 28, 72, 56), Qt.AlignCenter, label)

        self.draw_dwell_loader(painter, cx, cy, radius)

    def using_image_mode(self):
        return self.image_mode or self.blue_hand_closed or time.monotonic() < self.sharp_mode_until

    def draw_dwell_loader(self, painter, cx, cy, radius):
        if self.dwell_section < 0 or self.dwell_progress <= 0:
            return

        angle = math.radians(-(self.dwell_section * 60 + 30))
        tx = cx + math.cos(angle) * radius * 0.66
        ty = cy + math.sin(angle) * radius * 0.66
        loader_rect = QRectF(tx - 18, ty - 18, 36, 36)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 80), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawEllipse(loader_rect)
        painter.setPen(QPen(QColor("#ffffff"), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(loader_rect, 90 * 16, int(-360 * 16 * self.dwell_progress))

    def draw_reference_center(self, painter, cx, cy, radius):
        if self.center_live_image is not None and not self.center_live_image.isNull():
            self.draw_center_live_footage(painter, cx, cy, radius)
            return

        self.draw_chladni_plate(painter, cx, cy, radius, 7)

    def draw_center_live_footage(self, painter, cx, cy, radius):
        image = self.center_live_image
        target = QRectF(cx - radius * 0.86, cy - radius * 0.86, radius * 1.72, radius * 1.72)
        source = self.cover_source_rect(image.width(), image.height())

        clip = QPainterPath()
        clip.addEllipse(target)

        painter.save()
        painter.setClipPath(clip)
        painter.drawImage(target, image, source)
        painter.restore()

    def cover_source_rect(self, image_width, image_height):
        if image_width <= 0 or image_height <= 0:
            return QRectF()

        target_aspect = 1.0
        image_aspect = image_width / image_height

        if image_aspect > target_aspect:
            source_height = image_height
            source_width = image_height * target_aspect
            source_x = (image_width - source_width) / 2
            source_y = 0
        else:
            source_width = image_width
            source_height = image_width / target_aspect
            source_x = 0
            source_y = (image_height - source_height) / 2

        return QRectF(source_x, source_y, source_width, source_height)

    def draw_reference_disc(self, painter, cx, cy, radius):
        self.draw_chladni_plate(painter, cx, cy, radius, 4)

    def draw_chladni_plate(self, painter, cx, cy, radius, detail):
        painter.setBrush(QColor("#bf8a47"))
        painter.setPen(QPen(QColor("#f3cf8d"), max(2, int(radius * 0.03))))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        painter.setBrush(QColor(245, 218, 165, 58))
        painter.setPen(QPen(QColor("#6b3f1d"), max(1, int(radius * 0.015))))
        painter.drawEllipse(QPointF(cx, cy), radius * 0.9, radius * 0.9)

        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), radius * 0.86, radius * 0.86)
        painter.save()
        painter.setClipPath(clip)

        n = detail + self.selected_section % 3
        m = detail + 2 + (self.selected_section + 1) % 4
        scale = math.pi / radius
        step = max(3, int(radius / 34))

        painter.setPen(QPen(QColor("#2d1a0d"), max(2, int(radius * 0.018)), Qt.SolidLine, Qt.RoundCap))
        self.draw_chladni_contours(painter, cx, cy, radius * 0.83, n, m, scale, step)

        painter.restore()

        painter.setPen(QPen(QColor("#7c4a1f"), max(1, int(radius * 0.012))))
        for ring in (0.32, 0.58, 0.82):
            painter.drawEllipse(QPointF(cx, cy), radius * ring, radius * ring)

    def draw_chladni_contours(self, painter, cx, cy, radius, n, m, scale, step):
        x_start, x_end = int(cx - radius), int(cx + radius)
        y_start, y_end = int(cy - radius), int(cy + radius)

        def value_at(x, y):
            dx, dy = x - cx, y - cy
            return (math.sin(n * dx * scale) * math.sin(m * dy * scale) -
                    math.sin(m * dx * scale) * math.sin(n * dy * scale))

        def inside(x, y):
            return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2

        for y in range(y_start, y_end, step):
            for x in range(x_start, x_end, step):
                corners = [
                    (x, y, value_at(x, y)),
                    (x + step, y, value_at(x + step, y)),
                    (x + step, y + step, value_at(x + step, y + step)),
                    (x, y + step, value_at(x, y + step)),
                ]

                crossings = []
                for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
                    x1, y1, v1 = corners[a]
                    x2, y2, v2 = corners[b]
                    if v1 == 0:
                        crossings.append(QPointF(x1, y1))
                    elif v1 * v2 < 0:
                        t = abs(v1) / (abs(v1) + abs(v2))
                        px = x1 + (x2 - x1) * t
                        py = y1 + (y2 - y1) * t
                        if inside(px, py):
                            crossings.append(QPointF(px, py))

                if len(crossings) >= 2:
                    painter.drawLine(crossings[0], crossings[1])

    def draw_hands(self, painter, lx, ly, rx, ry):
        del lx, ly, rx, ry

        has_external_hand = self.external_left_hand or self.external_right_hand
        if has_external_hand and time.monotonic() - self.external_hands_time <= self.external_hands_hold:
            if self.external_left_hand:
                self.draw_real_hand_tracking(
                    painter,
                    self.external_left_hand,
                    QColor("#00eaff"),
                    self.blue_hand_closed,
                )
            if self.external_right_hand:
                self.draw_real_hand_tracking(
                    painter,
                    self.external_right_hand,
                    QColor("#ff3030"),
                    False,
                )
            return

        # Sem tracking real, nao desenha maos simuladas pelo mouse.
        return

    def draw_real_hand_tracking(self, painter, landmarks, color, closed):
        if len(landmarks) < 21:
            return

        bones = [
            (0, 1), (1, 2), (2, 3), (3, 4),
            (0, 5), (5, 6), (6, 7), (7, 8),
            (5, 9), (9, 10), (10, 11), (11, 12),
            (9, 13), (13, 14), (14, 15), (15, 16),
            (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
        ]

        line_color = QColor(color)
        line_color.setAlpha(210)
        point_color = QColor("#ffffff")
        point_color.setAlpha(235)

        # Espessura das linhas/pontos da mao real. Aumenta se estiver dificil de ver.
        bone_width = 9
        joint_radius = 8
        fingertip_radius = 11

        painter.setPen(QPen(line_color, bone_width, Qt.SolidLine, Qt.RoundCap))
        for a, b in bones:
            painter.drawLine(landmarks[a], landmarks[b])

        painter.setBrush(point_color)
        painter.setPen(QPen(color, 4))
        for index, point in enumerate(landmarks):
            radius = fingertip_radius if index in (4, 8, 12, 16, 20) else joint_radius
            painter.drawEllipse(point, radius, radius)

        painter.setBrush(QColor("#ffe100"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(landmarks[8], 7, 7)

        if color == QColor("#ff3030"):
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#ffe100"), 3))
            painter.drawEllipse(landmarks[8], 16, 16)

        if closed:
            painter.setBrush(QColor(255, 255, 255, 220))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(landmarks[0], 10, 10)

    def draw_hand_tracking(self, painter, origin, color, direction, closed, open_pose=False):
        landmarks = self.hand_landmarks(origin, direction, closed, open_pose)

        glow = QColor(color)
        glow.setAlpha(62)

        palm = [landmarks[0], landmarks[5], landmarks[9], landmarks[13], landmarks[17]]
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 28))
        painter.setPen(QPen(glow, 2))
        painter.drawPolygon(palm)

        bones = [
            (0, 1), (1, 2), (2, 3), (3, 4),
            (0, 5), (5, 6), (6, 7), (7, 8),
            (0, 9), (9, 10), (10, 11), (11, 12),
            (0, 13), (13, 14), (14, 15), (15, 16),
            (0, 17), (17, 18), (18, 19), (19, 20),
            (5, 9), (9, 13), (13, 17),
        ]

        painter.setPen(QPen(glow, 12, Qt.SolidLine, Qt.RoundCap))
        for a, b in bones:
            painter.drawLine(landmarks[a], landmarks[b])

        painter.setPen(QPen(color, 4, Qt.SolidLine, Qt.RoundCap))
        for a, b in bones:
            painter.drawLine(landmarks[a], landmarks[b])

        painter.setBrush(QColor("#05070a"))
        painter.setPen(QPen(color, 3))
        for index, point in enumerate(landmarks):
            radius = 6 if index in (0, 4, 8, 12, 16, 20) else 4
            painter.drawEllipse(point, radius, radius)

        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        for index in (4, 8, 12, 16, 20):
            painter.drawEllipse(landmarks[index], 3, 3)

    def hand_landmarks(self, origin, direction, closed=False, open_pose=False):
        if open_pose:
            return self.open_hand_landmarks(origin)

        spread = 1.0 + 0.18 * math.sin(self.t * 1.8)
        curl = 0.35 + 0.28 * math.sin(self.t * 2.2 + self.mouse_pos.x() * 0.01)
        if closed:
            spread = 0.45
            curl = 2.2

        wrist = QPointF(origin.x(), origin.y() + 28)
        bases = [
            QPointF(origin.x() - direction * 34, origin.y() + 6),
            QPointF(origin.x() - direction * 20, origin.y() - 20),
            QPointF(origin.x(), origin.y() - 28),
            QPointF(origin.x() + direction * 20, origin.y() - 20),
            QPointF(origin.x() + direction * 36, origin.y() - 8),
        ]
        angles = [-150 if direction > 0 else -30, -112, -90, -68, -48]
        lengths = [(26, 22, 18), (34, 28, 22), (42, 32, 24), (37, 28, 21), (30, 23, 18)]

        points = [wrist]
        for finger, base in enumerate(bases):
            points.append(base)
            current = base
            for joint, length in enumerate(lengths[finger]):
                if closed:
                    length *= 0.72
                bend = curl * (joint + 1) * (10 if finger > 0 else -8)
                wave = 0 if closed else math.sin(self.t * 2.4 + finger * 0.7 + joint) * 5
                angle = angles[finger] + direction * (finger - 2) * 4 * spread + bend + wave
                current = QPointF(
                    current.x() + math.cos(math.radians(angle)) * length,
                    current.y() + math.sin(math.radians(angle)) * length,
                )
                points.append(current)

        return points

    def open_hand_landmarks(self, origin):
        wrist = QPointF(origin.x(), origin.y())
        finger_specs = [
            ((-152, -159, -165), (34, 30, 26)),
            ((-121, -124, -127), (42, 35, 28)),
            ((-92, -92, -92), (46, 39, 32)),
            ((-64, -60, -56), (41, 34, 27)),
            ((-34, -28, -22), (35, 30, 25)),
        ]
        bases = [
            QPointF(origin.x() - 31, origin.y() - 8),
            QPointF(origin.x() - 17, origin.y() - 27),
            QPointF(origin.x(), origin.y() - 34),
            QPointF(origin.x() + 17, origin.y() - 27),
            QPointF(origin.x() + 31, origin.y() - 10),
        ]

        points = [wrist]
        for finger, base in enumerate(bases):
            points.append(base)
            current = base
            angles, lengths = finger_specs[finger]
            for angle_degrees, length in zip(angles, lengths):
                angle = math.radians(angle_degrees)
                current = QPointF(
                    current.x() + math.cos(angle) * length,
                    current.y() + math.sin(angle) * length,
                )
                points.append(current)

        return points

    def draw_image_button(self, painter, x, y):
        self.image_btn_rect = QRectF(x, y, 88, 64)

        base = QColor("#1d8dbf") if self.using_image_mode() else QColor("#24252b")
        if self.image_btn_hover:
            base = base.lighter(132)

        painter.setBrush(base)
        painter.setPen(QPen(QColor("#7adfff") if self.using_image_mode() else QColor("#4a4c55"), 3))
        painter.drawRoundedRect(self.image_btn_rect, 8, 8)

        painter.setPen(QPen(QColor("white"), 3, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(QColor(255, 255, 255, 42))

        c_x, c_y = self.image_btn_rect.center().x(), self.image_btn_rect.center().y()
        palm = QRectF(c_x - 18, c_y - 2, 36, 24)
        painter.drawRoundedRect(palm, 8, 8)
        
        for i in range(4):
            finger = QRectF(c_x - 22 + i * 11, self.image_btn_rect.top() + 16, 10, 24)
            painter.drawRoundedRect(finger, 5, 5)

        painter.drawLine(QPointF(c_x - 8, c_y + 20), QPointF(c_x - 18, c_y + 10))
        painter.drawLine(QPointF(c_x + 8, c_y + 20), QPointF(c_x + 18, c_y + 10))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
