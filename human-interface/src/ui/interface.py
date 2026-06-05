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
                          QPen, QPixmap, QRadialGradient, QPolygonF)
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
_WAVE_STEP_CIRCLE = 3

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
        self.sync_timer.start(500)

        self._symbol_images = {}
        self._preload_images()
        self._logo = self._load_logo()

        # State tracking
        self._rendered_chladni_id = "NONE"
        self._last_interaction = time.monotonic()
        self._last_hand_at = time.monotonic()
        self._idle_active = False
        self._idle_note = 0
        self._standby_active = False
        self._hints_visible = True
        self._heartbeat_enabled = True

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

        self.selector_radius_scale = 0.39
        self.center_plate_radius_scale = 0.33
        
        self.sector_labels = ["E", "D", "C", "B", "A", "F"]
        self.image_labels = ["D#", "F#", "G#", "A#", "G", "C#"]
        
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
        self._chladni_cache = {}

    def _init_ui_components(self):
        self.warning_banner = WarningBanner(self)
        self.warning_banner.move(0, 0)
        self.warning_banner.setFixedWidth(1280)

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

    def _sync_and_diagnostics_loop(self):
        if not self.client.is_connected:
            self.warning_banner.show_warning("CRITICAL: Plate Resonance Server Offline", critical=True)
        elif self.client.diagnostics.get("usb_audio") == 0:
            self.warning_banner.show_warning("WARNING: USB Soundcard Disconnected. Attempting recovery...", critical=False)
        elif self.client.diagnostics.get("pico_serial") == 0:
            self.warning_banner.show_warning("WARNING: LED Controller Disconnected. Attempting recovery...", critical=False)
        else:
            self.warning_banner.hide_warning()

        server_active_id = self.client.active_state.get("current_chladni_id")
        if server_active_id and server_active_id != self._rendered_chladni_id:
            self._rendered_chladni_id = server_active_id
            if server_active_id in self.catalogue:
                pattern = self.catalogue[server_active_id]
                self._selected_note_id = pattern.get("music_note", 0)

    def update_animation(self):
        now = time.monotonic()
        if self._anim_last_time == 0.0: self._anim_last_time = now
        dt = min(now - self._anim_last_time, 0.05)
        self._anim_last_time = now
        self.t += dt * 3.0
        
        channels = self._get_active_channels()
        if channels: self.frequency = sum(ch["frequency_hz"] for ch in channels) / len(channels)
        else: self.frequency = 200.0

        self.wave_amplitude = 0.50 + 0.45 * abs(math.sin(self.t * 0.9))

        if not self._idle_active and (now - self._last_interaction >= IDLE_TIMEOUT_S):
            self._enter_idle_mode()
        
        if not self._standby_active and (now - self._last_hand_at >= _STANDBY_TIMEOUT_S):
            self._enter_standby()

        self.update_dwell_selection()
        self.update()

    def update_dwell_selection(self):
        if self._idle_active: return
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
            if time.time() - self._last_note_change < 1.0: return
            self.selected_section = section; self._selected_note_id = self._dwell_note_id
            ch_id = self._id_for_note(self._dwell_note_id)
            if ch_id:
                led = self.catalogue[ch_id].get("LED_effect", 0)
                self.client.trigger(ch_id, self._dwell_note_id, led)
                self._last_note_change = time.time(); self._record_interaction()
            self.dwell_progress = 0.0; self._dwell_armed = False

    def _id_for_note(self, note_id):
        for name, entry in self.catalogue.items():
            if entry.get("music_note") == note_id: return name
        return None

    def _get_active_channels(self):
        note_id = self._idle_note if self._idle_active else self._selected_note_id
        for entry in self.catalogue.values():
            if entry.get("music_note") == note_id: return entry.get("hardware_config", {}).get("channels", [])
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
    def _enter_idle_mode(self): self._idle_active = True
    def _exit_idle_mode(self): self._idle_active = False
    
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
        
        base_r = min(w, h); sel_r = base_r * self.selector_radius_scale
        center_r = base_r * self.center_plate_radius_scale; preview_r = max(150, base_r * 0.15)
        
        self._draw_selector(p, cx, cy, sel_r)
        self._draw_center_plate(p, cx, cy, center_r)
        self._draw_dwell_ring(p, cx, cy, sel_r)
        
        px, py = w - preview_r - 20, h - preview_r - 20
        self._draw_preview_disc(p, px, py, preview_r)
        
        self._draw_hands(p)
        self._draw_image_button(p, w - 104, 16)
        
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

    def _draw_wave(self, p, x0, y0, length, channels=None):
        wave_count = 4; spacing = 44; speed = self.t * 4.0; base_amp = 20 + 15 * self.wave_amplitude
        colors = [QColor("#ff3a9e"), QColor("#cde70b"), QColor("#00eaff"), QColor("#ff8500")]
        if channels and len(channels) >= wave_count:
            raw_amps = [ch["amplitude"] for ch in channels[:wave_count]]
            max_a = max(raw_amps) or 1.0; amps = [a/max_a for a in raw_amps]
            wk = [0.025 + 0.06*(ch["frequency_hz"]/500.0) for ch in channels[:wave_count]]
            ph = [math.radians(ch["phase_deg"]) for ch in channels[:wave_count]]
        else: amps = [1.0]*4; wk = [0.055]*4; ph = [0, 1.57, 3.14, 4.71]
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

    def _draw_selector(self, p, cx, cy, radius):
        glow_a = int(45 + 205 * self.wave_amplitude); colors = self.image_colors if self.using_image_mode() else self.section_colors
        gc = QColor(colors[self.selected_section]); gc.setAlpha(glow_a)
        grad = QRadialGradient(QPointF(cx, cy), radius + 70); grad.setColorAt(0.45, QColor(0,0,0,0)); grad.setColorAt(0.76, gc); grad.setColorAt(1.0, QColor(0,0,0,0))
        p.setBrush(grad); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(cx, cy), radius + 70, radius + 70)
        span = 60 * 16
        for i, color in enumerate(colors):
            or_ = radius + 20 if i in (self.selected_section, self.hover_section) else radius
            rect = QRectF(cx-or_, cy-or_, or_*2, or_*2); fill = QColor(color); fill.setAlpha(245 if i == self.selected_section else 195)
            if i == self.hover_section: fill = fill.lighter(135)
            p.setBrush(fill); p.setPen(Qt.NoPen); p.drawPie(rect, i*span, span)
        p.setBrush(QColor("#1b1b1d")); p.setPen(QPen(QColor("#303035"), 4)); p.drawEllipse(QPointF(cx, cy), radius*0.72, radius*0.72)
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
        inner_r = radius * 0.86; target = QRectF(cx-inner_r, cy-inner_r, inner_r*2, inner_r*2); clip = QPainterPath(); clip.addEllipse(target)
        p.save(); p.setClipPath(clip)
        if img: p.drawImage(target, img, self.cover_source_rect(img.width(), img.height()))
        else: self._draw_chladni_contours_engine(p, cx, cy, inner_r)
        p.restore()
        p.setPen(QPen(QColor("#7c4a1f"), max(1, int(radius*0.012))))
        for r in (0.32, 0.58, 0.82): p.drawEllipse(QPointF(cx, cy), radius*r, radius*r)

    def _draw_chladni_contours_engine(self, p, cx, cy, radius):
        n = 4 + self.selected_section%3; m = 6 + (self.selected_section+1)%4; scale = math.pi/radius; step = max(3, int(radius/34))
        p.setPen(QPen(QColor("#2d1a0d"), max(2, int(radius*0.018)), Qt.SolidLine, Qt.RoundCap))
        def val(x, y): dx, dy = x-cx, y-cy; return (math.sin(n*dx*scale)*math.sin(m*dy*scale) - math.sin(m*dx*scale)*math.sin(n*dy*scale))
        def inside(x, y): return (x-cx)**2 + (y-cy)**2 <= radius**2
        xs, xe = int(cx-radius), int(cx+radius); ys, ye = int(cy-radius), int(cy+radius)
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
                if len(crossings)>=2: p.drawLine(crossings[0], crossings[1])

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
        p.setFont(QFont("Arial", 13, QFont.Bold)); p.setPen(QColor(0, 234, 255, alpha))
        p.drawText(QRectF(w*0.14-90, cy+24, 180, 26), Qt.AlignCenter, "✊  CLOSE")
        p.setPen(QColor(180, 240, 255, alpha)); p.drawText(QRectF(w*0.14-90, cy+52, 180, 26), Qt.AlignCenter, "✋  OPEN")
        p.setPen(QColor(255, 80, 80, alpha)); p.drawText(QRectF(w*0.86-110, cy+24, 220, 26), Qt.AlignCenter, "MOVE INTO A NOTE")
        p.setPen(QColor(0, 217, 232, alpha)); p.setFont(QFont("Arial", 15, QFont.Bold))
        p.drawText(QRectF(cx-340, cy+center_r+75, 680, 100), Qt.AlignCenter, "COME TRY!  SELECT A MUSIC NOTE")

    def _draw_hints(self, p, w, h):
        hb_label = "HB On" if self._heartbeat_enabled else "HB Off"
        hints = [("[M]", "Câmeras"), ("[I]", "Diagnósticos"), ("[F]", "♯ Modo"), ("[H]", hb_label)]
        kf, lf = QFont("Arial", 11, QFont.Bold), QFont("Arial", 11); gap = 18; hy = h - 22; fm = p.fontMetrics()
        tw = sum(fm.horizontalAdvance(k)+fm.horizontalAdvance("  "+l) for k,l in hints) + gap*(len(hints)-1); hx = (w-tw)/2
        for k, l in hints:
            p.setFont(kf); p.setPen(QColor("#00d9e8")); p.drawText(QRectF(hx, hy-14, fm.horizontalAdvance(k), 18), Qt.AlignLeft, k); hx += fm.horizontalAdvance(k)
            p.setFont(lf); p.setPen(QColor("#3a4a5a")); p.drawText(QRectF(hx, hy-14, fm.horizontalAdvance("  "+l), 18), Qt.AlignLeft, "  "+l); hx += fm.horizontalAdvance("  "+l)+gap

    def _draw_heartbeat_indicator(self, p, w):
        if not self._heartbeat_enabled: return
        if self.client.is_connected: pulse = 0.45+0.55*abs(math.sin(self.t*1.9)); col = QColor(0,255,37,int(210*pulse)); lbl = "HB OK"
        else: col = QColor("#ff0038"); lbl = "HB FAIL"
        dx, dy = w-168.0, 8.0; p.setBrush(col); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(dx, dy), 4, 4)
        p.setPen(col); p.setFont(QFont("Arial", 9, QFont.Bold)); p.drawText(QRectF(dx+10, dy-7, 150, 15), Qt.AlignLeft|Qt.AlignVCenter, lbl)

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
        if cursor: self.mouse_pos = cursor; self.hover_section = self.section_at(self.mouse_pos); self.image_btn_hover = self.image_btn_rect.contains(self.mouse_pos)
        self.update()

    def set_center_live_image(self, img): self.center_live_image = img; self.update()
    def keyPressEvent(self, e):
        if e.key()==Qt.Key_I: self.testing_toggle.emit()
        elif e.key()==Qt.Key_M: self.settings_requested.emit()
        elif e.key()==Qt.Key_H: self._heartbeat_enabled = not self._heartbeat_enabled; self.heartbeat_toggled.emit(self._heartbeat_enabled)
        elif e.key()==Qt.Key_B: self._hints_visible = not self._hints_visible
        elif e.key()==Qt.Key_F: self.blue_hand_closed = True; self.sharp_mode_until = time.monotonic()+86400; self._record_interaction()
        super().keyPressEvent(e)
    def keyReleaseEvent(self, e):
        if e.key()==Qt.Key_F: self.blue_hand_closed = False; self.sharp_mode_until = 0.0; self.update()
        super().keyReleaseEvent(e)
    def mouseMoveEvent(self, e): self.mouse_pos = QPointF(e.position()); self.hover_section = self.section_at(self.mouse_pos); self.image_btn_hover = self.image_btn_rect.contains(self.mouse_pos); self._record_interaction(); self.update()
    def mousePressEvent(self, e):
        if e.button()==Qt.LeftButton and self.image_btn_rect.contains(e.position()): self.image_mode = not self.image_mode; self._record_interaction(); self.update()
    def leaveEvent(self, e): self.hover_section = -1; self.image_btn_hover = False; self.update(); super().leaveEvent(e)
