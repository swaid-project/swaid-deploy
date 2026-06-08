import json
import math
import os
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QImage, QPainter, QPainterPath,
                          QPen, QPixmap, QRadialGradient, QPolygonF, QLinearGradient)
from PySide6.QtWidgets import QWidget

from ui.dashboard import WarningBanner

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).parent.parent.parent / relative_path

# --- Constants & Configuration ---
NOTE_MAP = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}
IDLE_TIMEOUT_S = 5 * 60
CYCLE_INTERVAL_S = 60
_STANDBY_TIMEOUT_S = 5 * 60
_TOTAL_NOTES = 12

_WAVE_STEP_BG = 3

_GHOST_HAND_PTS = (
    ( 0.00,  0.00), (-0.30, -0.20), (-0.50, -0.38), (-0.63, -0.52), (-0.70, -0.63),
    (-0.12, -0.52), (-0.14, -0.70), (-0.15, -0.83), (-0.15, -0.93), ( 0.00, -0.56),
    ( 0.00, -0.76), ( 0.00, -0.90), ( 0.00, -1.00), ( 0.13, -0.52), ( 0.15, -0.70),
    ( 0.15, -0.83), ( 0.15, -0.93), ( 0.26, -0.43), ( 0.28, -0.58), ( 0.28, -0.68),
    ( 0.28, -0.76),
)

class MainWindow(QWidget):
    settings_requested = Signal()
    testing_toggle = Signal()
    heartbeat_toggled = Signal(bool)

    def __init__(self, client, catalogue):
        super().__init__()
        self.client = client
        self.catalogue = catalogue
        
        self.setWindowTitle("SWAID Human Interface")
        self.resize(1280, 720)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.BlankCursor)

        self._init_animation_state()
        self._init_ui_components()
        
        # 1. Primary Animation Timer (33ms ~30FPS as per legacy)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(33)

        # 2. Sync & Diagnostics Timer (2Hz)
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self._sync_and_diagnostics_loop)
        self.sync_timer.start(100)

        self._symbol_images = {}
        self._preload_images()
        self._status_icons = {}
        self._preload_status_icons()
        self._logo = self._load_logo()

        self.sys_server_ok = False
        self.sys_music_ok = False
        self.sys_plate_ok = False
        self.sys_led_ok = False
        self.server_ping_alpha = 255.0

        # State tracking
        self._rendered_chladni_id = "NONE"
        self._pattern_start_time = 0.0
        self._last_interaction = time.monotonic()
        self._last_hand_at = time.monotonic()
        self._idle_active = False
        self._idle_note = 0
        self._standby_active = True
        self._hints_visible = False
        self._heartbeat_enabled = True
        
        self.is_input_locked = False
        self._lockout_timer = QTimer(self)
        self._lockout_timer.setSingleShot(True)
        self._lockout_timer.timeout.connect(self._unlock_input)

    def _unlock_input(self):
        self.is_input_locked = False
        self.update()

    def _init_animation_state(self):
        self.t = 0.0
        self._anim_last_time = 0.0
        self.frequency = 2.7
        self.wave_amplitude = 0.0
        self.selected_section = 0
        self.hover_section = -1
        self.mouse_pos = QPointF(self.width() / 2, self.height() / 2)
        
        self.left_hand = self.right_hand = None
        self.hand_update_time = 0.0
        self.blue_hand_closed = False
        self.sharp_mode_until = 0.0
        
        self.image_mode = False
        self.center_live_image = None
        
        self.dwell_section = -1
        self.dwell_started_at = 0.0
        self.dwell_progress = 0.0
        self.dwell_duration = 1.0
        self._dwell_note_id = 0
        self._selected_note_id = 0
        self._dwell_armed = True
        self._last_note_change = 0.0

        self._camera_error = ""
        self._idle_last_cycle = 0.0

        self.selector_radius_scale = 0.39
        self.center_plate_radius_scale = 0.33
        
        self.sector_labels = ["E", "D", "C₄", "B", "A", "G"]
        self.image_labels = ["F", "D#", "C#", "C₅", "A#", "G#"]
        
        self.section_colors = [
            QColor("#00d9e8"), QColor("#7d3c98"), QColor("#00ff25"),
            QColor("#ff8500"), QColor("#ffe100"), QColor("#ff0038")
        ]
        self.image_colors = [
            QColor("#00ff25"), QColor("#ff8500"), QColor("#ffe100"),
            QColor("#ff0038"), QColor("#00d9e8"), QColor("#7d3c98")
        ]

        self.image_btn_hover = False
        self.image_btn_rect = QRectF()
        self._shuffle_btn_hover = False
        self._shuffle_btn_rect = QRectF()
        self._shuffle_dwell_start = None
        self._shuffle_locked = False
        self._chladni_cache = {}

    def _init_ui_components(self):
        self._active_warning_msg = ""
        self._active_warning_critical = False

    def _preload_status_icons(self):
        icon_names = ["server", "fist", "openhand"]
        colors = {"green": "#00E800", "red": "#FF0038", "white": "#FFFFFF"}
        for name in icon_names:
            self._status_icons[name] = {}
            path = get_resource_path(f"assets/{name}.svg")
            if not path.exists():
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    svg_content = f.read()
                
                for state, color in colors.items():
                    mod_svg = svg_content.replace("#1C274C", color).replace("#000000", color)
                    pixmap = QPixmap()
                    pixmap.loadFromData(mod_svg.encode('utf-8'))
                    if not pixmap.isNull():
                        self._status_icons[name][state] = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception: pass

    def _preload_images(self):
        for name, entry in self.catalogue.items():
            rel_path = entry.get("ui_metadata", {}).get("image_path", "")
            if not rel_path: continue
            img_path = get_resource_path(rel_path.lstrip("./"))
            if img_path.exists():
                try:
                    pil_img = Image.open(img_path).convert("RGBA")
                    arr = np.array(pil_img, dtype=np.uint8)
                    h, w = arr.shape[:2]
                    self._symbol_images[name] = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
                except Exception: pass

    def _load_logo(self):
        for ext in ["png", "tiff", "tif"]:
            path = get_resource_path(f"assets/LogoFeup.{ext}")
            if path.exists():
                try:
                    if ext == "png": return QPixmap(str(path))
                    pil_img = Image.open(path).convert("RGBA")
                    arr = np.array(pil_img, dtype=np.uint8)
                    h, w = arr.shape[:2]
                    qimg = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
                    return QPixmap.fromImage(qimg)
                except Exception: pass
        return None

    def cover_source_rect(self, iw: int, ih: int) -> QRectF:
        if iw <= 0 or ih <= 0: return QRectF()
        if iw / ih > 1.0:
            sw, sh = ih * 1.0, float(ih)
            return QRectF((iw - sw) / 2, 0, sw, sh)
        sw, sh = float(iw), iw / 1.0
        return QRectF(0, (ih - sh) / 2, sw, sh)

    def set_camera_error(self, msg):
        self._camera_error = msg

    def _sync_and_diagnostics_loop(self):
        self.sys_server_ok = self.client.is_connected
        if self.sys_server_ok:
            self.server_ping_alpha = 255.0
            
        self.sys_plate_ok = self.client.diagnostics.get("usb_audio", 0) != 0
        self.sys_led_ok = self.client.diagnostics.get("pico_serial", 0) != 0
        self.sys_music_ok = self.client.diagnostics.get("UDP_connection", 0) != 0

        if not self.sys_server_ok:
            self._active_warning_msg = "CRITICAL: Core Server Offline. Please restart the system."
            self._active_warning_critical = True
        elif self._camera_error:
            self._active_warning_msg = self._camera_error
            self._active_warning_critical = True
        else:
            disconnected = []
            if not self.sys_plate_ok:
                disconnected.append("USB Soundcard")
            if not self.sys_led_ok:
                disconnected.append("LED Controller")
                
            pd_offline = not self.sys_music_ok
            
            if disconnected or pd_offline:
                parts = []
                if disconnected:
                    if len(disconnected) == 1:
                        parts.append(f"{disconnected[0]} disconnected")
                    else:
                        parts.append(f"{' and '.join(disconnected)} disconnected")
                
                if pd_offline:
                    parts.append("PureData music link offline")
                    
                msg = "WARNING: " + ". ".join(parts) + "."
                if disconnected:
                    msg += " System attempting auto-recovery..."
                elif pd_offline:
                    msg += " Sound may be limited."
                    
                self._active_warning_msg = msg
                self._active_warning_critical = False
            else:
                self._active_warning_msg = ""

        server_active_id = self.client.active_state.get("current_chladni_id", "NONE")
        if server_active_id != self._rendered_chladni_id:
            self._rendered_chladni_id = server_active_id
            self._pattern_start_time = time.monotonic()
            if server_active_id != "NONE":
                self._last_played_chladni_id = server_active_id
            if server_active_id in self.catalogue:
                pattern = self.catalogue[server_active_id]
                self._selected_note_id = pattern.get("music_note", 0)
    
    def _calculate_visual_envelope(self):
        active_id = self._id_for_note(self._idle_note) if self._idle_active else self._rendered_chladni_id
        
        if active_id == "NONE" or active_id not in self.catalogue:
            return 0.0
            
        pattern = self.catalogue[active_id]
        fi = pattern.get("fade_in_ms", 100) / 1000.0
        du = pattern.get("symbol_duration_ms", 500) / 1000.0
        fo = pattern.get("fade_out_ms", 100) / 1000.0
        
        elapsed = time.monotonic() - self._pattern_start_time
        
        if elapsed < fi:
            return elapsed / fi if fi > 0 else 1.0
        elif elapsed < fi + du:
            return 1.0
        elif elapsed < fi + du + fo:
            return 1.0 - (elapsed - (fi + du)) / fo if fo > 0 else 0.0
        else:
            return 0.0

    def update_animation(self):
        now = time.monotonic()
        if self._anim_last_time == 0.0: self._anim_last_time = now
        dt = min(now - self._anim_last_time, 0.05)
        self._anim_last_time = now
        
        self.server_ping_alpha = max(100.0, self.server_ping_alpha - (dt * 1500.0))
        
        self.wave_amplitude = self._calculate_visual_envelope()
        
        # Always animate waves
        self.t += dt * 3.0
        
        channels = self._get_active_channels()
        if channels: 
            self.frequency = sum(ch["frequency_hz"] for ch in channels) / len(channels)
        else: 
            self.frequency = 200.0

        if not self._idle_active and (now - self._last_interaction >= IDLE_TIMEOUT_S):
            self._enter_idle_mode()
        elif self._idle_active and (now - self._idle_last_cycle >= CYCLE_INTERVAL_S):
            self._idle_note = (self._idle_note + 1) % _TOTAL_NOTES
            self._idle_last_cycle = now
            self._trigger_idle_note()

        if not self._standby_active and (now - self._last_hand_at >= _STANDBY_TIMEOUT_S):
            self._enter_standby()

        self.update_dwell_selection()
        self.update()

    def update_dwell_selection(self):
        if self._idle_active or self.is_input_locked: 
            self.dwell_progress = 0.0
            return
        
        section = self.section_at(self.mouse_pos)
        now = time.monotonic()
        if section < 0:
            self.dwell_section = -1; self.dwell_progress = 0.0; self._dwell_armed = True; return
        needs_sel = (section != self.selected_section) or self._dwell_armed
        if not needs_sel or section != self.dwell_section:
            self.dwell_section = section; self.dwell_started_at = now; self.dwell_progress = 0.0
            labels = self.image_labels if self.using_image_mode() else self.sector_labels
            self._dwell_note_id = NOTE_MAP.get(labels[section % len(labels)], 0); return
        self.dwell_progress = min(1.0, (now - self.dwell_started_at) / self.dwell_duration)
        if self.dwell_progress >= 1.0:
            self.selected_section = section; self._selected_note_id = self._dwell_note_id
            ch_id = self._id_for_note(self._dwell_note_id)
            if ch_id:
                pattern = self.catalogue[ch_id]
                fade_in = pattern.get("fade_in_ms", 100)
                sustain = pattern.get("symbol_duration_ms", 500)
                fade_out = pattern.get("fade_out_ms", 100)
                total_lockout = fade_in + sustain + fade_out
                
                self.client.trigger(self._dwell_note_id)
                self._unlock_shuffle()

                # Apply the Smart Lockout
                self.is_input_locked = True
                self._lockout_timer.start(total_lockout)
                
                self._last_note_change = now; self._record_interaction()
            self.dwell_progress = 0.0; self._dwell_armed = False

    def _unlock_shuffle(self):
        self._shuffle_locked = False

    def trigger_shuffle(self):
        if self.is_input_locked: return
        
        # Calculate total duration of all SHUFFLE_x steps
        total_lockout = 0
        for i in range(1, 100):
            sid = f"SHUFFLE_{i}"
            if sid in self.catalogue:
                p = self.catalogue[sid]
                total_lockout += p.get("fade_in_ms", 100) + p.get("symbol_duration_ms", 500) + p.get("fade_out_ms", 100)
            else:
                break
        
        if total_lockout > 0:
            self.client.shuffle()
            self.is_input_locked = True
            self._shuffle_locked = True
            self._lockout_timer.start(total_lockout)
            self._record_interaction()
            self.update()

    def _id_for_note(self, note_id):
        for name, entry in self.catalogue.items():
            if entry.get("music_note") == note_id: return name
        return None

    def _get_active_channels(self):
        id_ = self._idle_note if self._idle_active else self._rendered_chladni_id
        
        if id_ == "NONE" and not self._idle_active:
            id_ = getattr(self, '_last_played_chladni_id', "NONE")

        if id_ in self.catalogue:
            return self.catalogue[id_].get("hardware_config", {}).get("channels", [])
        
        # Fallback for note IDs (legacy)
        for entry in self.catalogue.values():
            if entry.get("music_note") == id_: return entry.get("hardware_config", {}).get("channels", [])
        return []

    def using_image_mode(self): return (self.image_mode or self.blue_hand_closed or time.monotonic() < self.sharp_mode_until)

    def section_at(self, pos):
        cx, cy = self.width() / 2, self.height() / 2
        size = min(self.width(), self.height())
        outer_r, inner_r = size * 0.36 + 22, size * 0.235
        dx, dy = pos.x() - cx, pos.y() - cy
        dist = math.hypot(dx, dy)
        if dist < inner_r or dist > outer_r: return -1
        angle = (-math.degrees(math.atan2(dy, dx)) + 360) % 360
        return int(angle // 60) % 6

    def _record_interaction(self): self._last_interaction = time.monotonic(); self._exit_idle_mode()
    def _enter_idle_mode(self):
        self._idle_active = True
        self._idle_last_cycle = time.monotonic()
        print(f"[UI] Idle mode entered — cycling every {CYCLE_INTERVAL_S}s")
        self._trigger_idle_note()
    def _exit_idle_mode(self):
        if self._idle_active:
            print("[UI] Idle mode exited")
        self._idle_active = False
        self._idle_note = 0
    def _trigger_idle_note(self):
        ch_id = self._id_for_note(self._idle_note)
        print(f"[UI] Idle cycle → note {self._idle_note} ({ch_id})")
        for use_image, labels in ((False, self.sector_labels), (True, self.image_labels)):
            for idx, label in enumerate(labels):
                if NOTE_MAP.get(label) == self._idle_note:
                    self.selected_section = idx
                    self.image_mode = use_image
                    break
        if ch_id:
            self.client.trigger(self._idle_note)
            self._unlock_shuffle()

    def trigger_standby_test(self): self._enter_standby(); self.update()
    def _enter_standby(self): self._standby_active = True
    def _exit_standby(self): self._standby_active = False

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height(); cx, cy = w/2, h/2
        p.fillRect(self.rect(), QColor("#020203"))
        
        note_id = self._idle_note if self._idle_active else self._selected_note_id
        channels = self._get_active_channels()
        
        p.save(); p.translate(cx, cy); p.rotate(30)
        self._draw_wave(p, -1000, 0, 2000, channels); p.restore()
        
        self._draw_ambient_warning(p, w, h)
        
        base_r = min(w, h); sel_r = base_r * self.selector_radius_scale
        center_r = base_r * self.center_plate_radius_scale; preview_r = max(150, base_r * 0.15)
        
        self._draw_actuation_ripple(p, cx, cy, sel_r)
        
        self._draw_selector(p, cx, cy, sel_r)
        self._draw_center_plate(p, cx, cy, center_r)
        self._draw_dwell_ring(p, cx, cy, sel_r)
        
        px, py = w - preview_r - 20, h - preview_r - 20
        self._draw_preview_disc(p, px, py, preview_r)
        
        self._draw_hands(p)
        
        if self._standby_active: self._draw_standby_overlay(p, cx, cy, center_r)
        
        if self._idle_active:
            pulse = 0.55 + 0.45 * abs(math.sin(self.t * 0.6))
            p.setPen(QColor(0, 217, 232, int(200 * pulse)))
            p.setFont(QFont("Arial", 13, QFont.Bold))
            sym = self._id_for_note(self._idle_note) or "—"
            p.drawText(QRectF(16, 16, 400, 24), Qt.AlignLeft | Qt.AlignVCenter, f"● ATTRACT  note {self._idle_note}  ({sym})")

        if self._logo:
            lh = 100; lw = int(lh * self._logo.width() / self._logo.height())
            p.drawPixmap(16, h - lh - 16, lw, lh, self._logo)
        
        if self._hints_visible: self._draw_hints(p, w, h)
        self._draw_heartbeat_indicator(p, w)
        self._draw_shuffle_button(p, w - 192, 16)
        self._draw_image_button(p, w - 104, 152)

    def _draw_wave(self, p, x0, y0, length, channels=None):
        wave_count = 4; spacing = 44; speed = self.t * 4.0;
        colors = [QColor("#ff3a9e"), QColor("#cde70b"), QColor("#00eaff"), QColor("#ff8500")]
        if channels:
            base_amp = 35
            padded_channels = [channels[i % len(channels)] for i in range(wave_count)]
            raw_amps = [ch.get("amplitude", 1.0) for ch in padded_channels]
            max_a = max(raw_amps) or 1.0; amps = [a/max_a for a in raw_amps]
            wk = [0.025 + 0.06*(ch.get("frequency_hz", 200)/500.0) for ch in padded_channels]
            ph = [math.radians(ch.get("phase_deg", 0)) + (math.pi/2 if i >= len(channels) else 0) for i, ch in enumerate(padded_channels)]
        else: 
            base_amp = 20 + 15 * self.wave_amplitude
            amps = [1.0]*4; wk = [0.055]*4; ph = [0, 1.57, 3.14, 4.71]
        for wi in range(wave_count):
            baseline = y0 + (wi - 1.5) * spacing; amp, pph, wwk, col = base_amp * amps[wi], ph[wi], wk[wi], colors[wi]
            pts = [QPointF(x0 + x, baseline + math.sin(x*wwk + speed + pph)*amp) for x in range(0, length, _WAVE_STEP_BG)]
            glow = QColor(col); glow.setAlpha(42); p.setPen(QPen(glow, 10, Qt.SolidLine, Qt.RoundCap))
            p.drawPolyline(QPolygonF(pts))
            lc = QColor(col); lc.setAlpha(210); p.setPen(QPen(lc, 3, Qt.SolidLine, Qt.RoundCap))
            p.drawPolyline(QPolygonF(pts))
            dot_off = (0.0, length/3.0, 2.0*length/3.0)
            p.setBrush(col); p.setPen(QPen(Qt.white, 2))
            for off in dot_off:
                mx = (self.t*68 + wi*36 + off)%length; my = baseline + math.sin(mx*wwk + speed + pph)*amp
                p.drawEllipse(QPointF(x0 + mx, my), 6, 6)

    def _draw_actuation_ripple(self, p, cx, cy, base_radius):
        if self._rendered_chladni_id == "NONE":
            return
            
        pattern = self.catalogue.get(self._rendered_chladni_id, {})
        fi = pattern.get("fade_in_ms", 100)
        du = pattern.get("symbol_duration_ms", 500)
        fo = pattern.get("fade_out_ms", 100)
        total_duration = (fi + du + fo) / 1000.0
        
        elapsed = time.monotonic() - self._pattern_start_time
        
        spawn_interval = 0.35
        ripple_lifetime = 1.2
        max_expansion = 700.0
        
        # Stop drawing if the last possible ripple has finished its lifetime
        if elapsed < 0 or elapsed >= total_duration + ripple_lifetime:
            return
            
        colors = self.image_colors if self.using_image_mode() else self.section_colors
        base_col = QColor(colors[self.selected_section])
        
        p.save()
        p.setBrush(Qt.NoBrush)
        
        for i in range(15):
            t_start = i * spawn_interval
            
            # The time window determines if a ripple is allowed to SPAWN
            if t_start >= total_duration:
                break
                
            ripple_age = elapsed - t_start
            if ripple_age < 0:
                break
                
            # If the ripple has spawned and is still within its lifetime, let it propagate naturally
            if ripple_age < ripple_lifetime:
                t = ripple_age / ripple_lifetime
                ease_out = 1.0 - math.pow(1.0 - t, 3)
                current_radius = base_radius + 20 + (max_expansion * ease_out)
                
                # Individual fade out over the ripple's lifetime
                alpha = int(255 * 0.40 * (1.0 - t))
                
                col = QColor(base_col)
                col.setAlpha(alpha)
                p.setPen(QPen(col, 2, Qt.SolidLine, Qt.RoundCap))
                p.drawEllipse(QPointF(cx, cy), current_radius, current_radius)
                
        p.restore()

    def _draw_selector(self, p, cx, cy, radius):
        glow_a = int(90 + 165 * self.wave_amplitude); colors = self.image_colors if self.using_image_mode() else self.section_colors
        
        # Draw glow if not locked
        if not self.is_input_locked:
            gc = QColor(colors[self.selected_section]); gc.setAlpha(glow_a)
            grad = QRadialGradient(QPointF(cx, cy), radius + 110); grad.setColorAt(0.40, QColor(0,0,0,0)); grad.setColorAt(0.70, gc); grad.setColorAt(1.0, QColor(0,0,0,0))
            p.setBrush(grad); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(cx, cy), radius + 110, radius + 110)
        
        span = 60 * 16
        for i, color in enumerate(colors):
            is_sel = (i == self.selected_section)
            is_hov = (i == self.hover_section and not self.is_input_locked)
            or_ = radius + 20 if (is_sel or is_hov) else radius
            rect = QRectF(cx-or_, cy-or_, or_*2, or_*2)
            
            fill = QColor(color)
            if self.is_input_locked:
                pulse_alpha = 110 + int(70 * math.sin(time.monotonic() * 6.0 - i * 1.047))
                fill.setAlpha(pulse_alpha)
            else:
                fill.setAlpha(245 if is_sel else 195)
                if is_hov: fill = fill.lighter(135)
            
            p.setBrush(fill); p.setPen(Qt.NoPen); p.drawPie(rect, i*span, span)
            
        p.setBrush(QColor("#1b1b1d")); p.setPen(QPen(QColor("#303035"), 4)); p.drawEllipse(QPointF(cx, cy), radius*0.72, radius*0.72)
        
        if self.is_input_locked:
            p.setPen(QColor("#ff0038"))
            p.setFont(QFont("Arial", 16, QFont.Bold))
            p.drawText(QRectF(cx-100, cy-20, 200, 40), Qt.AlignCenter, "SYSTEM BUSY")
        else:
            labels = self.image_labels if self.using_image_mode() else self.sector_labels
            p.setFont(QFont("Arial", 34, QFont.Bold))
            for i in range(6):
                a = math.radians(-(i*60 + 30)); tx, ty = cx + math.cos(a)*radius*0.86, cy + math.sin(a)*radius*0.86
                p.setPen(QColor("#050505")); p.drawText(QRectF(tx-36, ty-28, 72, 56), Qt.AlignCenter, labels[i])

    def _draw_dwell_ring(self, p, cx, cy, radius):
        if self.dwell_section < 0 or self.dwell_progress <= 0: return
        a = math.radians(-(self.dwell_section*60 + 30)); tx, ty = cx + math.cos(a)*radius*0.82, cy + math.sin(a)*radius*0.82
        rect = QRectF(tx-20, ty-20, 40, 40); p.setPen(QPen(QColor(255,255,255,60), 5, Qt.SolidLine, Qt.RoundCap)); p.drawEllipse(rect)
        p.setPen(QPen(Qt.white, 5, Qt.SolidLine, Qt.RoundCap)); p.drawArc(rect, 90*16, int(-360*16*self.dwell_progress))

    def _draw_center_plate(self, p, cx, cy, radius):
        inner_r = radius * 0.86; target = QRectF(cx-inner_r, cy-inner_r, inner_r*2, inner_r*2); clip = QPainterPath(); clip.addEllipse(target)
        p.save(); p.setClipPath(clip)
        if self.center_live_image: p.drawImage(target, self.center_live_image, self.cover_source_rect(self.center_live_image.width(), self.center_live_image.height()))
        else: p.fillRect(target, QColor("#0a0b0e"))
        p.restore()

    def _draw_preview_disc(self, p, cx, cy, radius):
        id_ = self._id_for_note(self._idle_note if self._idle_active else self._selected_note_id); img = self._symbol_images.get(id_)
        p.setBrush(QColor("#bf8a47")); p.setPen(QPen(QColor("#f3cf8d"), max(2, int(radius*0.03)))); p.drawEllipse(QPointF(cx, cy), radius, radius)
        p.setBrush(QColor(245,218,165,58)); p.setPen(QPen(QColor("#6b3f1d"), max(1, int(radius*0.015)))); p.drawEllipse(QPointF(cx, cy), radius*0.9, radius*0.9)
        if self._shuffle_locked: return
        inner_r = radius * 0.86; target = QRectF(cx-inner_r, cy-inner_r, inner_r*2, inner_r*2); clip = QPainterPath(); clip.addEllipse(target)
        p.save(); p.setClipPath(clip)
        if img: p.drawImage(target, img, self.cover_source_rect(img.width(), img.height()))
        else: self._draw_chladni_contours_engine(p, cx, cy, inner_r)
        p.restore()
        if not img:
            p.setPen(QPen(QColor("#7c4a1f"), max(1, int(radius*0.012))))
            for r in (0.32, 0.58, 0.82): p.drawEllipse(QPointF(cx, cy), radius*r, radius*r)

    def _draw_chladni_contours_engine(self, p, cx, cy, radius):
        cache_key = (self.selected_section, int(radius))
        if cache_key in self._chladni_cache:
            p.drawPixmap(cx - radius, cy - radius, self._chladni_cache[cache_key])
            return

        pixmap = QPixmap(int(radius * 2), int(radius * 2))
        pixmap.fill(Qt.transparent)
        px_p = QPainter(pixmap)
        px_p.setRenderHint(QPainter.Antialiasing)

        n = 4 + self.selected_section%3; m = 6 + (self.selected_section+1)%4; scale = math.pi/radius; step = max(3, int(radius/34))
        px_p.setPen(QPen(QColor("#2d1a0d"), max(2, int(radius*0.018)), Qt.SolidLine, Qt.RoundCap))
        def val(x, y): dx, dy = x-radius, y-radius; return (math.sin(n*dx*scale)*math.sin(m*dy*scale) - math.sin(m*dx*scale)*math.sin(n*dy*scale))
        def inside(x, y): return (x-radius)**2 + (y-radius)**2 <= radius**2
        xs, xe = 0, int(radius*2); ys, ye = 0, int(radius*2)
        for y in range(ys, ye, step):
            for x in range(xs, xe, step):
                corners = [(x,y,val(x,y)), (x+step,y,val(x+step,y)), (x+step,y+step,val(x+step,y+step)), (x,y+step,val(x,y+step))]
                crossings = []
                for a, b in ((0,1),(1,2),(2,3),(3,0)):
                    x1,y1,v1=corners[a]; x2,y2,v2=corners[b]
                    if v1==0: crossings.append(QPointF(x1,y1))
                    elif v1*v2 < 0:
                        t = abs(v1)/(abs(v1)+abs(v2)); px,py = x1+(x2-x1)*t, y1+(y2-y1)*t
                        if inside(px,py): crossings.append(QPointF(px,py))
                if len(crossings)>=2: px_p.drawLine(crossings[0], crossings[1])
        px_p.end()
        self._chladni_cache[cache_key] = pixmap
        p.drawPixmap(cx - radius, cy - radius, pixmap)

    def _draw_hands(self, p):
        if self.left_hand: self._draw_hand_skeleton(p, self.left_hand, QColor("#00eaff"), self.blue_hand_closed)
        if self.right_hand: self._draw_hand_skeleton(p, self.right_hand, QColor("#ff3030"), False)

    def _draw_hand_skeleton(self, p, lms, color, closed):
        bones = [(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(0,17),(17,18),(18,19),(19,20)]
        lc = QColor(color); lc.setAlpha(210); p.setPen(QPen(lc, 9, Qt.SolidLine, Qt.RoundCap))
        for a, b in bones: p.drawLine(lms[a], lms[b])
        p.setBrush(Qt.white); p.setPen(QPen(color, 4))
        for idx, pt in enumerate(lms): r = 11 if idx in (4,8,12,16,20) else 8; p.drawEllipse(pt, r, r)
        p.setBrush(QColor("#ffe100")); p.setPen(Qt.NoPen); p.drawEllipse(lms[8], 7, 7)
        if color == QColor("#ff3030"): p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor("#ffe100"), 3)); p.drawEllipse(lms[8], 16, 16)
        if closed: p.setBrush(QColor(255,255,255,220)); p.drawEllipse(lms[0], 10, 10)

    def _draw_standby_overlay(self, p, cx, cy, center_r):
        pulse = 0.60 + 0.40 * abs(math.sin(self.t * 1.2)); w = self.width(); scale = 300; alpha = int(210 * pulse)
        p.setOpacity(0.38 * pulse)
        l_pts = [QPointF(w*0.14 - dx*scale, cy+dy*scale) for dx,dy in _GHOST_HAND_PTS]
        r_pts = [QPointF(w*0.86 + dx*scale, cy+dy*scale) for dx,dy in _GHOST_HAND_PTS]
        self._draw_hand_skeleton(p, l_pts, QColor("#00eaff"), False)
        self._draw_hand_skeleton(p, r_pts, QColor("#ff3030"), False)
        p.setOpacity(1.0)
        fist_icon = self._status_icons.get("fist", {}).get("white")
        p.setFont(QFont("Arial", 13, QFont.Bold)); p.setPen(QColor(0, 234, 255, alpha))
        if fist_icon:
            p.setOpacity(alpha / 255.0)
            p.drawPixmap(w*0.14 - 44, cy+21, 32, 32, fist_icon)
            p.setOpacity(1.0)
            p.drawText(QRectF(w*0.14 - 8, cy+24, 100, 26), Qt.AlignLeft | Qt.AlignVCenter, "CLOSE")
        else:
            p.drawText(QRectF(w*0.14-90, cy+24, 180, 26), Qt.AlignCenter, "CLOSE")

        openhand_icon = self._status_icons.get("openhand", {}).get("white")
        p.setPen(QColor(180, 240, 255, alpha))
        if openhand_icon:
            p.setOpacity(alpha / 255.0)
            p.drawPixmap(w*0.14 - 44, cy+49, 32, 32, openhand_icon)
            p.setOpacity(1.0)
            p.drawText(QRectF(w*0.14 - 8, cy+52, 100, 26), Qt.AlignLeft | Qt.AlignVCenter, "OPEN")
        else:
            p.drawText(QRectF(w*0.14-90, cy+52, 180, 26), Qt.AlignCenter, "OPEN")

        p.setPen(QColor(255, 80, 80, alpha)); p.drawText(QRectF(w*0.86-110, cy+24, 220, 26), Qt.AlignCenter, "MOVE INTO A NOTE")
        p.setPen(QColor(0, 217, 232, alpha)); p.setFont(QFont("Arial", 15, QFont.Bold))
        p.drawText(QRectF(cx-340, cy+center_r+75, 680, 100), Qt.AlignCenter, "COME TRY!  SELECT A MUSIC NOTE")

    def _draw_hints(self, p, w, h):
        hints = [("[M]", "Câmeras"), ("[I]", "Diagnósticos"), ("[F]", "♯ Modo")]
        kf, lf = QFont("Arial", 11, QFont.Bold), QFont("Arial", 11); gap = 18; hy = h - 22
        
        tw = 0
        widths = []
        for k, l in hints:
            p.setFont(kf); kw = p.fontMetrics().horizontalAdvance(k)
            p.setFont(lf); lw = p.fontMetrics().horizontalAdvance("  "+l)
            widths.append((kw, lw))
            tw += kw + lw
        tw += gap * (len(hints) - 1)
        
        hx = (w - tw) / 2
        for i, (k, l) in enumerate(hints):
            kw, lw = widths[i]
            p.setFont(kf); p.setPen(QColor("#00d9e8"))
            p.drawText(QRectF(hx, hy-14, kw, 18), Qt.AlignLeft, k)
            hx += kw
            
            p.setFont(lf); p.setPen(QColor("#3a4a5a"))
            p.drawText(QRectF(hx, hy-14, lw, 18), Qt.AlignLeft, "  "+l)
            hx += lw + gap

    def _draw_ambient_warning(self, p, w, h):
        msg = getattr(self, '_active_warning_msg', "")
        if not msg: return
        
        critical = getattr(self, '_active_warning_critical', False)
        base_color = QColor("#ff0038") if critical else QColor("#ff8500")
        
        p.save()
        p.setPen(Qt.NoPen)
        grad = QLinearGradient(0, 0, w, 0)
        
        c_edge = QColor(base_color.red(), base_color.green(), base_color.blue(), 0)
        c_mid = QColor(base_color.red(), base_color.green(), base_color.blue(), 180)
        
        grad.setColorAt(0.0, c_edge)
        grad.setColorAt(0.2, c_mid)
        grad.setColorAt(0.8, c_mid)
        grad.setColorAt(1.0, c_edge)
        
        p.setBrush(grad)
        p.drawRect(0, 0, w, 60)
        
        p.setPen(Qt.white)
        p.setFont(QFont("Arial", 12, QFont.Bold))
        p.drawText(QRectF(0, 0, w, 60), Qt.AlignCenter, msg)
        p.restore()

    def _draw_heartbeat_indicator(self, p, w):
        if not self._heartbeat_enabled: return
        
        start_y = 96
        start_x = w - 76
        
        is_ok = self.sys_server_ok
        state_key = "green" if is_ok else "red"
        icon = self._status_icons.get("server", {}).get(state_key)
        
        if icon:
            if is_ok:
                p.setOpacity(self.server_ping_alpha / 255.0)
            else:
                p.setOpacity(1.0)
            p.drawPixmap(start_x, start_y, 32, 32, icon)
            
        p.setOpacity(1.0)

    def _draw_shuffle_button(self, p, x, y):
        self._shuffle_btn_rect = QRectF(x, y, 176, 128)
        base = QColor("#2a1e4a") if not self._shuffle_btn_hover else QColor("#3d2e6e")
        p.setBrush(base); p.setPen(QPen(QColor("#9b59f5"), 3)); p.drawRoundedRect(self._shuffle_btn_rect, 8, 8)
        p.setPen(QColor("#d4b8ff")); p.setFont(QFont("Arial", 18, QFont.Bold))
        p.drawText(self._shuffle_btn_rect, Qt.AlignCenter, "⟳  SHUFFLE")

    def _draw_image_button(self, p, x, y):
        self.image_btn_rect = QRectF(x, y, 88, 64); base = QColor("#1d8dbf") if self.using_image_mode() else QColor("#24252b")
        if self.image_btn_hover: base = base.lighter(132)
        p.setBrush(base); p.setPen(QPen(QColor("#7adfff") if self.using_image_mode() else QColor("#4a4c55"), 3)); p.drawRoundedRect(self.image_btn_rect, 8, 8)
        p.setPen(QPen(Qt.white, 3, Qt.SolidLine, Qt.RoundCap)); p.setBrush(QColor(255, 255, 255, 42))
        bx, by = self.image_btn_rect.center().x(), self.image_btn_rect.center().y()
        p.drawRoundedRect(QRectF(bx-18, by-2, 36, 24), 8, 8)
        for i in range(4): p.drawRoundedRect(QRectF(bx-22+i*11, self.image_btn_rect.top()+16, 10, 24), 5, 5)
        p.drawLine(QPointF(bx-8, by+20), QPointF(bx-18, by+10)); p.drawLine(QPointF(bx+8, by+20), QPointF(bx+18, by+10))

    def set_tracked_hands(self, left, right, closed, cursor):
        if left or right: self._last_hand_at = time.monotonic(); self._exit_standby(); self._record_interaction()
        self.left_hand, self.right_hand, self.blue_hand_closed = left, right, closed
        if cursor:
            self.mouse_pos = cursor
            self.hover_section = self.section_at(self.mouse_pos)
            self.image_btn_hover = self.image_btn_rect.contains(self.mouse_pos)
            over_shuffle = self._shuffle_btn_rect.contains(self.mouse_pos)
            self._shuffle_btn_hover = over_shuffle
            now = time.monotonic()
            if over_shuffle and not self._shuffle_locked and not self.is_input_locked:
                if self._shuffle_dwell_start is None:
                    self._shuffle_dwell_start = now
                elif now - self._shuffle_dwell_start >= 0.5:
                    self.trigger_shuffle()
                    self._shuffle_locked = True
                    self._shuffle_dwell_start = None
            else:
                self._shuffle_dwell_start = None
        else:
            self._shuffle_dwell_start = None
        self.update()

    def set_center_live_image(self, img): self.center_live_image = img; self.update()
    def keyPressEvent(self, e):
        if e.key()==Qt.Key_I: self.testing_toggle.emit()
        elif e.key()==Qt.Key_M: self.settings_requested.emit()
        elif e.key()==Qt.Key_S: self.trigger_shuffle()
        elif e.key()==Qt.Key_H: self._heartbeat_enabled = not self._heartbeat_enabled; self.heartbeat_toggled.emit(self._heartbeat_enabled)
        elif e.key()==Qt.Key_B: self._hints_visible = not self._hints_visible
        elif e.key()==Qt.Key_F: self.blue_hand_closed = True; self.sharp_mode_until = time.monotonic()+86400; self._record_interaction()
        super().keyPressEvent(e)
    def keyReleaseEvent(self, e):
        if e.key()==Qt.Key_F: self.blue_hand_closed = False; self.sharp_mode_until = 0.0; self.update()
        super().keyReleaseEvent(e)
    def mouseMoveEvent(self, e): self.mouse_pos = QPointF(e.position()); self.hover_section = self.section_at(self.mouse_pos); self.image_btn_hover = self.image_btn_rect.contains(self.mouse_pos); self._shuffle_btn_hover = self._shuffle_btn_rect.contains(self.mouse_pos); self._record_interaction(); self.update()
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self.image_btn_rect.contains(e.position()): self.image_mode = not self.image_mode; self._record_interaction(); self.update()
            elif self._shuffle_btn_rect.contains(e.position()): self.trigger_shuffle()
    def leaveEvent(self, e): self.hover_section = -1; self.image_btn_hover = False; self._shuffle_btn_hover = False; self.update(); super().leaveEvent(e)
    def resizeEvent(self, e):
        self._chladni_cache.clear()
        super().resizeEvent(e)
