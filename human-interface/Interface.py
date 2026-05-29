"""
Interface.py — MainWindow for SWAID-ESIS.

Sections
--------
1. Imports & Framework Setup
2. Configuration & Constants
3. Resonance SDK Native Bindings
4. State Management & Timers
5. UI Layout & Event Routines
"""

# ===========================================================================
# 1. IMPORTS & FRAMEWORK SETUP
# ===========================================================================

import ctypes
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image                          # robust asset loading (PNG/TIFF/etc.)
from PySide6.QtCore  import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui   import (QColor, QFont, QImage, QPainter, QPainterPath,
                              QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget


# ===========================================================================
# 2. CONFIGURATION & CONSTANTS
# ===========================================================================

# -- Asset paths -------------------------------------------------------------
_ASSETS_DIR = Path(__file__).parent / "assets"
_LOGO_FILE  = "FEUPLogo.png"          # PNG with alpha-channel support

# -- Local IPC endpoint ------------------------------------------------------
_ZMQ_ADDRESS = b"tcp://127.0.0.1:5555"

# -- SDK volume defaults (sent with every hardware packet) -------------------
_DEFAULT_LEFT_VOLUME  = 100.0   # Left_Volume  (0.0 – 100.0)
_DEFAULT_RIGHT_VOLUME = 100.0   # Right_volume (0.0 – 100.0)

# -- Heartbeat / ping-pong (HI ↔ PR link monitoring) ------------------------
_HEARTBEAT_INTERVAL_S     = 2   # seconds between pings
_HEARTBEAT_MISS_THRESHOLD = 3   # consecutive misses before comm-failure warning

# -- Chromatic note map: label → Music_note integer 0-11 (C=0 … B=11) -------
NOTE_MAP: dict[str, int] = {
    "C": 0, "C#": 1, "D": 2,  "D#": 3,
    "E": 4, "F":  5, "F#": 6, "G":  7,
    "G#": 8, "A": 9, "A#": 10, "B": 11,
}

# -- Idle / attract-cycle timing ---------------------------------------------
_IDLE_TIMEOUT_S   = 5 * 60   # seconds of inactivity → enter cycle mode
_CYCLE_INTERVAL_S = 60        # seconds per note step in cycle
_TOTAL_NOTES      = 12        # Music_note range: 0-11

# -- Embedded Chladni configs (no external JSON required) --------------------
_DEFAULT_FREQUENCIES = [100, 150, 191, 220, 250, 300]


def _default_channels(freq: float) -> list[dict]:
    return [
        {"amplitude": 0.85, "channel": 1, "frequency_hz": freq, "phase_deg": 0,   "x": 0.053, "y": 0.036},
        {"amplitude": 0.85, "channel": 2, "frequency_hz": freq, "phase_deg": 90,  "x": 0.947, "y": 0.036},
        {"amplitude": 0.85, "channel": 3, "frequency_hz": freq, "phase_deg": 180, "x": 0.053, "y": 0.964},
        {"amplitude": 0.85, "channel": 4, "frequency_hz": freq, "phase_deg": 270, "x": 0.947, "y": 0.964},
    ]


def _build_configs() -> list[dict]:
    return [
        {
            "display_name": f"CHLADNI_{freq}",
            "hardware_config": {"channels": _default_channels(freq)},
            "id": idx,
        }
        for idx, freq in enumerate(_DEFAULT_FREQUENCIES)
    ]


def _config_channels(config: dict) -> list[dict]:
    return config.get("hardware_config", {}).get("channels", []) if config else []


def _load_logo() -> "QPixmap | None":
    """
    Load FEUPLogo.png via Pillow preserving the alpha channel (RGBA),
    convert to QImage Format_RGBA8888, return as QPixmap.
    Falls back through legacy names so older assets still work.
    """
    candidates = [
        _LOGO_FILE,
        "FEUPLogo.tiff",
        "FEUPLogo.tif",
        "LogoFeup.png",
        "LogoFeup.tiff",
        "LogoFeup.tif",
    ]

    path: "Path | None" = None
    for name in candidates:
        p = _ASSETS_DIR / name
        if p.exists():
            path = p
            break

    if path is None:
        for p in _ASSETS_DIR.glob("Logo*.*"):
            path = p
            break

    if path is None:
        return None

    # Qt native loader (fast path for PNG)
    try:
        pix = QPixmap(str(path))
        if not pix.isNull():
            return pix
    except Exception:
        pass

    # Pillow fallback: RGBA → QImage → QPixmap
    # Using RGBA so PNG transparency is preserved correctly.
    try:
        pil_img = Image.open(path).convert("RGBA")
        arr = np.array(pil_img, dtype=np.uint8)
        h, w = arr.shape[:2]
        qimg = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
        return QPixmap.fromImage(qimg)
    except Exception:
        return None


# ===========================================================================
# 3. RESONANCE SDK NATIVE BINDINGS
# ===========================================================================

def _sdk_load() -> "ctypes.CDLL | None":
    """
    Load libresonance_sdk.so from the script's own directory.
    Returns None (simulated mode) if the library is absent or fails to load.
    """
    path = Path(__file__).parent / "libresonance_sdk.so"
    if not path.exists():
        print(f"[SDK] {path.name} not found — simulated mode active.")
        return None
    try:
        lib = ctypes.CDLL(str(path))
        print(f"[SDK] Loaded {path}")
        return lib
    except OSError as exc:
        print(f"[SDK] Load error: {exc} — simulated mode active.")
        return None


def _sdk_configure(lib: ctypes.CDLL) -> None:
    """Declare ctypes argtypes/restype for all SDK entry points."""
    lib.init_zmq.argtypes    = [ctypes.c_char_p]
    lib.init_zmq.restype     = None

    lib.close_zmq.argtypes   = []
    lib.close_zmq.restype    = None

    # 3-field payload ABI: Music_note, Left_Volume, Right_volume + buffer
    lib.format_json.argtypes = [
        ctypes.c_int,    # Music_note   — 0-11
        ctypes.c_float,  # Left_Volume  — 0.0 to 100.0
        ctypes.c_float,  # Right_volume — 0.0 to 100.0
        ctypes.c_char_p, # output buffer
        ctypes.c_int,    # buffer size
    ]
    lib.format_json.restype  = None

    lib.send_zmq.argtypes    = [ctypes.c_char_p]
    lib.send_zmq.restype     = ctypes.c_int


def _sdk_init() -> "ctypes.CDLL | None":
    """Load, configure, and connect the SDK.  Returns the lib handle or None."""
    lib = _sdk_load()
    if lib is None:
        return None
    _sdk_configure(lib)
    lib.init_zmq(_ZMQ_ADDRESS)
    print(f"[SDK] ZeroMQ connected → {_ZMQ_ADDRESS.decode()}")
    return lib


def _sdk_send(lib: "ctypes.CDLL | None",
              note_id: int,
              left_volume: float,
              right_volume: float) -> None:
    """Format and transmit a hardware packet for the given Music_note and volumes."""
    if lib is None:
        print(f"[SDK sim] Music_note={note_id}  "
              f"Left_Volume={left_volume:.1f}  Right_volume={right_volume:.1f}")
        return
    buf = ctypes.create_string_buffer(512)
    lib.format_json(
        ctypes.c_int(note_id),
        ctypes.c_float(left_volume),
        ctypes.c_float(right_volume),
        buf, 512,
    )
    result = lib.send_zmq(buf.value)
    if result == 1:
        print(f"[SDK] Sent Music_note={note_id}  "
              f"Left_Volume={left_volume:.1f}  Right_volume={right_volume:.1f}")
    elif result == 0:
        print(f"[SDK] ZMQ queue full — dropped (Music_note={note_id})")
    else:
        print(f"[SDK] Error result={result} (Music_note={note_id})")


# ===========================================================================
# 4. STATE MANAGEMENT & TIMERS  (housed inside MainWindow.__init__)
# ===========================================================================
# All mutable state lives on the MainWindow instance.  Five subsystems:
#
#   Heartbeat     — self._heartbeat_enabled  (bool, toggled by [H])
#                   self._heartbeat_warning  (bool, set after 3 missed pongs)
#                   self._hb_consecutive_misses  (int, reset on pong receipt)
#                   self._hb_timer  (QTimer, _HEARTBEAT_INTERVAL_S interval)
#                   Fires _heartbeat_tick(); call receive_pong() from outside.
#
#   Volumes       — self._left_volume  (float 0-100, Left_Volume)
#                   self._right_volume (float 0-100, Right_volume)
#                   Controlled via painted vertical sliders; included in
#                   every outgoing SDK packet.
#
#   Debounce      — self._last_note_change  (time.time float)
#                   Rejects manual note changes < 1 s apart.
#
#   Idle tracker  — self._last_interaction  (time.monotonic float)
#                   Checked every animation frame; triggers cycle after 5 min.
#
#   Cycle timer   — self._idle_timer        (QTimer, 60 s interval)
#                   Fires _advance_idle_cycle() while attract mode is active.
#
# See _init_state() for initialization and the subsystem methods below.
# ===========================================================================


# ===========================================================================
# 5. UI LAYOUT & EVENT ROUTINES
# ===========================================================================

class MainWindow(QWidget):
    # Qt signals
    settings_requested = Signal()
    testing_toggle     = Signal()

    # -----------------------------------------------------------------------
    # Construction
    # -----------------------------------------------------------------------

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mockup Interativo - Controlo Vibroacustico")
        self.resize(1280, 720)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.BlankCursor)

        self._init_animation_state()
        self._init_state()          # Section 4: all subsystems

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(16)        # ~60 fps

        self.configs = _build_configs()
        self._logo   = _load_logo()

    def _init_animation_state(self) -> None:
        """Visual / interaction variables."""
        self.t                   = 0.0
        self.frequency           = 2.7
        self.wave_amplitude      = 0.0
        self.selected_section    = 0
        self.hover_section       = -1
        self.mouse_pos           = QPointF(self.width() / 2, self.height() / 2)
        self.external_left_hand  = None
        self.external_right_hand = None
        self.external_hands_time = 0.0
        self.external_hands_hold = 0.30
        self.image_mode          = False
        self.center_live_image   = None
        self.blue_hand_closed    = False
        self.sharp_mode_until    = 0.0
        self.dwell_section       = -1
        self.dwell_started_at    = 0.0
        self.dwell_progress      = 0.0
        self.dwell_duration      = 0.7
        self.image_btn_hover     = False
        self.image_btn_rect      = QRectF()
        self.selector_radius_scale      = 0.39
        self.center_plate_radius_scale  = 0.265

        self.sector_labels = ["E", "D", "C", "B", "A", "F"]
        self.image_labels  = ["D#", "F#", "G#", "A#", "G", "C#"]

        self.section_colors = [
            QColor("#00d9e8"), QColor("#7d3c98"), QColor("#00ff25"),
            QColor("#ff8500"), QColor("#ffe100"), QColor("#ff0038"),
        ]
        self.image_colors = [
            QColor("#00ff25"), QColor("#ff8500"), QColor("#ffe100"),
            QColor("#ff0038"), QColor("#00d9e8"), QColor("#7d3c98"),
        ]

    def _init_state(self) -> None:
        """Section 4: all five subsystems."""

        # -- SDK (Section 3) -------------------------------------------------
        self._sdk = _sdk_init()

        # -- Heartbeat (HI ↔ PR ping-pong monitoring) -----------------------
        self._heartbeat_enabled:     bool = True
        self._heartbeat_warning:     bool = False
        self._hb_consecutive_misses: int  = 0

        self._hb_timer = QTimer(self)
        self._hb_timer.setInterval(_HEARTBEAT_INTERVAL_S * 1000)
        self._hb_timer.timeout.connect(self._heartbeat_tick)
        self._hb_timer.start()

        # -- Volumes (Left_Volume and Right_volume, sent with every packet) --
        self._left_volume:  float = _DEFAULT_LEFT_VOLUME
        self._right_volume: float = _DEFAULT_RIGHT_VOLUME

        # -- Volume slider interaction state ---------------------------------
        self._dragging_slider: "str | None" = None  # "left" or "right"
        self._vol_rect_left  = QRectF()
        self._vol_rect_right = QRectF()

        # -- Debounce (1-second rate limiter for manual note changes) --------
        self._last_note_change: float = 0.0   # wall-clock time.time()

        # -- Idle tracker (5-minute inactivity window) -----------------------
        self._last_interaction: float = time.monotonic()
        self._idle_active:      bool  = False
        self._idle_note:        int   = 0     # current note position in cycle

        # -- Cycle timer (advances note every 60 s while idle) ---------------
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(_CYCLE_INTERVAL_S * 1000)
        self._idle_timer.timeout.connect(self._advance_idle_cycle)

    # -----------------------------------------------------------------------
    # Section 4: Heartbeat (HI ↔ PR ping-pong)
    # -----------------------------------------------------------------------

    def _toggle_heartbeat(self) -> None:
        """Enable or disable the ping-pong heartbeat system ([H] key)."""
        self._heartbeat_enabled = not self._heartbeat_enabled
        ts = time.strftime("%H:%M:%S")
        if self._heartbeat_enabled:
            self._hb_consecutive_misses = 0
            self._heartbeat_warning     = False
            self._hb_timer.start()
            print(f"[{ts}] [Heartbeat] System ENABLED "
                  f"(interval {_HEARTBEAT_INTERVAL_S}s, "
                  f"threshold {_HEARTBEAT_MISS_THRESHOLD} misses)")
        else:
            self._hb_timer.stop()
            self._heartbeat_warning = False
            print(f"[{ts}] [Heartbeat] System DISABLED")
        self.update()

    def _heartbeat_tick(self) -> None:
        """Fires every _HEARTBEAT_INTERVAL_S seconds: send ping, track misses."""
        self._send_heartbeat_ping()
        self._hb_consecutive_misses += 1
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [Heartbeat] Ping dispatched "
              f"(consecutive misses: {self._hb_consecutive_misses})")
        if (self._hb_consecutive_misses >= _HEARTBEAT_MISS_THRESHOLD
                and not self._heartbeat_warning):
            self._heartbeat_warning = True
            print(f"[{ts}] [Heartbeat] WARNING — "
                  f"{self._hb_consecutive_misses} consecutive pings without pong")
        self.update()

    def _send_heartbeat_ping(self) -> None:
        """Transmit a raw ping JSON over the existing ZMQ PUSH socket."""
        if self._sdk is not None:
            self._sdk.send_zmq(b'{"message_type":"ping"}')

    def receive_pong(self) -> None:
        """Call this when a pong arrives from the PR driver (external entry point)."""
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [Heartbeat] Pong received — resetting miss counter")
        self._hb_consecutive_misses = 0
        if self._heartbeat_warning:
            self._heartbeat_warning = False
            print(f"[{ts}] [Heartbeat] Comm link restored")
        self.update()

    # -----------------------------------------------------------------------
    # Section 4: Idle / attract-cycle control
    # -----------------------------------------------------------------------

    def _enter_idle_mode(self) -> None:
        if self._idle_active:
            return
        self._idle_active = True
        self._idle_note   = 0
        print(f"[Idle] Entering cycle mode (no interaction for "
              f"{_IDLE_TIMEOUT_S // 60} min).")
        _sdk_send(self._sdk, self._idle_note, self._left_volume, self._right_volume)
        self._idle_timer.start()

    def _advance_idle_cycle(self) -> None:
        self._idle_note = (self._idle_note + 1) % _TOTAL_NOTES
        print(f"[Idle] Cycle → Music_note {self._idle_note}")
        _sdk_send(self._sdk, self._idle_note, self._left_volume, self._right_volume)

    def _exit_idle_mode(self) -> None:
        if not self._idle_active:
            return
        self._idle_active = False
        self._idle_timer.stop()
        print("[Idle] User detected — exiting cycle mode.")

    def _record_interaction(self) -> None:
        """Call on any user input to reset the idle countdown."""
        self._last_interaction = time.monotonic()
        self._exit_idle_mode()

    # -----------------------------------------------------------------------
    # Section 4: Note-ID resolution (Section 2 NOTE_MAP applied here)
    # -----------------------------------------------------------------------

    def _note_id_for_section(self, section: int) -> int:
        labels = self.image_labels if self.using_image_mode() else self.sector_labels
        return NOTE_MAP.get(labels[section % len(labels)], 0)

    # -----------------------------------------------------------------------
    # Section 4: Volume slider geometry and interaction helpers
    # -----------------------------------------------------------------------

    def _compute_vol_rects(self) -> None:
        """Recompute both slider rects from current window dimensions."""
        top = self.height() * 0.22
        ht  = self.height() * 0.56          # slider track height
        self._vol_rect_left  = QRectF(20,                    top, 26, ht)
        self._vol_rect_right = QRectF(self.width() - 46,     top, 26, ht)

    def _vol_from_mouse_y(self, rect: QRectF, y: float) -> float:
        """Map mouse y within a slider rect to 0.0–100.0 (top = 100, bottom = 0)."""
        rel = (y - rect.top()) / max(1.0, rect.height())
        return max(0.0, min(100.0, (1.0 - rel) * 100.0))

    def _hit_vol_slider(self, pos: QPointF) -> "str | None":
        """Return 'left', 'right', or None for which slider the point lands in."""
        if self._vol_rect_left.adjusted(-6, -6, 6, 6).contains(pos):
            return "left"
        if self._vol_rect_right.adjusted(-6, -6, 6, 6).contains(pos):
            return "right"
        return None

    def _apply_slider_drag(self, pos: QPointF) -> None:
        """Update the dragged volume and fire an SDK packet."""
        if self._dragging_slider == "left":
            self._left_volume  = self._vol_from_mouse_y(self._vol_rect_left,  pos.y())
        elif self._dragging_slider == "right":
            self._right_volume = self._vol_from_mouse_y(self._vol_rect_right, pos.y())
        else:
            return
        note_id = self._note_id_for_section(self.selected_section)
        _sdk_send(self._sdk, note_id, self._left_volume, self._right_volume)

    # -----------------------------------------------------------------------
    # Section 5: Core widget interface called by main.py
    # -----------------------------------------------------------------------

    def current_config(self) -> dict:
        if not self.configs:
            return {}
        return self.configs[self.selected_section % len(self.configs)]

    def set_tracked_hands(self, left_hand=None, right_hand=None,
                          blue_hand_closed: bool = False,
                          cursor_point=None) -> None:
        if left_hand is not None or right_hand is not None:
            self._record_interaction()

        self.external_left_hand  = left_hand
        self.external_right_hand = right_hand
        self.external_hands_time = time.monotonic()
        self.blue_hand_closed    = blue_hand_closed

        if cursor_point is not None:
            self.mouse_pos       = cursor_point
            self.hover_section   = self.section_at(self.mouse_pos)
            self.image_btn_hover = self.image_btn_rect.contains(self.mouse_pos)

        self.update()

    def set_center_live_image(self, image) -> None:
        self.center_live_image = image
        self.update()

    # -----------------------------------------------------------------------
    # Section 5: Animation loop
    # -----------------------------------------------------------------------

    def update_animation(self) -> None:
        self.t += 0.05
        channels = _config_channels(self.current_config())
        if channels:
            avg_amp  = sum(ch["amplitude"]    for ch in channels) / len(channels)
            avg_freq = sum(ch["frequency_hz"] for ch in channels) / len(channels)
        else:
            avg_amp, avg_freq = 1.0, 200.0

        self.wave_amplitude = avg_amp * (0.50 + 0.45 * abs(math.sin(self.t * 0.9)))
        self.frequency      = avg_freq

        # Idle threshold check (runs every ~16 ms)
        if not self._idle_active:
            elapsed = time.monotonic() - self._last_interaction
            if elapsed >= _IDLE_TIMEOUT_S:
                self._enter_idle_mode()

        self.update_dwell_selection()
        self.update()

    # -----------------------------------------------------------------------
    # Section 4: Dwell selection with debounce (1 s rate limiter)
    # -----------------------------------------------------------------------

    def update_dwell_selection(self) -> None:
        # Manual input is suppressed while the attract cycle runs
        if self._idle_active:
            return

        section = self.section_at(self.mouse_pos)
        now     = time.monotonic()

        if section < 0:
            self.dwell_section  = -1
            self.dwell_progress = 0.0
            return

        needs_selection = (
            section != self.selected_section
            or (self.blue_hand_closed and not self.using_image_mode())
        )
        if not needs_selection or section != self.dwell_section:
            self.dwell_section    = section
            self.dwell_started_at = now
            self.dwell_progress   = 0.0
            return

        self.dwell_progress = min(1.0, (now - self.dwell_started_at) / self.dwell_duration)
        if self.dwell_progress < 1.0:
            return

        # Debounce: reject if < 1 s since last accepted note change
        wall_now = time.time()
        if wall_now - self._last_note_change < 1.0:
            self.dwell_progress = 0.0
            return

        # Accept selection
        self.selected_section = section
        channels = _config_channels(self.current_config())
        if channels:
            self.frequency = sum(ch["frequency_hz"] for ch in channels) / len(channels)
        if self.blue_hand_closed:
            self.sharp_mode_until = now + 1.5

        # Resolve Music_note, transmit, update timestamps
        note_id = self._note_id_for_section(section)
        _sdk_send(self._sdk, note_id, self._left_volume, self._right_volume)

        self._last_note_change = wall_now   # debounce timestamp
        self._last_interaction = now        # reset idle countdown
        self.dwell_progress    = 0.0

    # -----------------------------------------------------------------------
    # Section 5: Qt event handlers
    # -----------------------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:
        pos = QPointF(event.position())
        self._record_interaction()

        # Volume slider drag takes priority over section hover
        if self._dragging_slider is not None:
            self._apply_slider_drag(pos)
            self.update()
            return

        self.mouse_pos       = pos
        self.hover_section   = self.section_at(pos)
        self.image_btn_hover = self.image_btn_rect.contains(pos)
        self.update()

    def mousePressEvent(self, event) -> None:
        self._record_interaction()
        pos = QPointF(event.position())

        if event.button() == Qt.LeftButton:
            slider = self._hit_vol_slider(pos)
            if slider is not None:
                self._dragging_slider = slider
                self._apply_slider_drag(pos)
                self.update()
                return

            if self.image_btn_rect.contains(pos):
                self.image_mode = not self.image_mode
                self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging_slider is not None:
            self._dragging_slider = None
            self.update()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.isAutoRepeat():
            return super().keyPressEvent(event)
        key = event.key()
        if key == Qt.Key_M:
            self.settings_requested.emit()
        elif key == Qt.Key_H:
            self._toggle_heartbeat()
        elif key == Qt.Key_I:
            self.testing_toggle.emit()
        elif key == Qt.Key_F:
            self.blue_hand_closed = True
            self._record_interaction()
            self.update()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if not event.isAutoRepeat() and event.key() == Qt.Key_F:
            self.blue_hand_closed = False
            self.update()
            return
        super().keyReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self.hover_section    = -1
        self.image_btn_hover  = False
        self._dragging_slider = None
        self.update()
        super().leaveEvent(event)

    def closeEvent(self, event) -> None:
        """Stop heartbeat timer and close ZMQ socket on window close."""
        self._hb_timer.stop()
        if self._sdk is not None:
            try:
                self._sdk.close_zmq()
            except Exception:
                pass
        super().closeEvent(event)

    # -----------------------------------------------------------------------
    # Section 5: Paint
    # -----------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy      = w / 2, h / 2
        base_radius = min(w, h)

        painter.fillRect(self.rect(), QColor("#020203"))

        selector_radius = base_radius * self.selector_radius_scale
        center_radius   = base_radius * self.center_plate_radius_scale
        preview_radius  = max(100, min(58, base_radius * 0.07))

        img_btn_x = w - 104
        img_btn_y = 16
        preview_x = w - preview_radius - 20
        preview_y = h - preview_radius - 20

        # Background wave (unchanged from original)
        channels = _config_channels(self.current_config())
        painter.save()
        painter.rotate(30)
        self._draw_wave(painter, 0, 0, length=600, channels=channels)
        painter.restore()

        self._draw_selector(painter, cx, cy, selector_radius)
        self._draw_reference_center(painter, cx, cy, center_radius)
        self._draw_reference_disc(painter, preview_x, preview_y, preview_radius)
        self._draw_hands(painter)
        self._draw_image_button(painter, img_btn_x, img_btn_y)
        self._draw_volume_sliders(painter)

        # Idle attract indicator
        if self._idle_active:
            pulse = 0.55 + 0.45 * abs(math.sin(self.t * 0.6))
            c = QColor(0, 217, 232, int(200 * pulse))
            painter.setPen(c)
            painter.setFont(QFont("Arial", 13, QFont.Bold))
            painter.drawText(QRectF(16, 16, 340, 24),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             f"● ATTRACT  Music_note {self._idle_note}")

        # FEUP logo — bottom-left
        if self._logo and not self._logo.isNull():
            lh = 100
            lw = int(lh * self._logo.width() / self._logo.height())
            painter.drawPixmap(16, h - lh - 16, lw, lh, self._logo)

        # Keyboard hint bar — bottom-centre
        self._draw_hints(painter, w, h)

        # Heartbeat status indicator (non-blocking, top-right, above image button)
        self._draw_heartbeat_indicator(painter, w)

    # -----------------------------------------------------------------------
    # Section 5: Heartbeat status indicator (non-blocking)
    # -----------------------------------------------------------------------

    def _draw_heartbeat_indicator(self, painter: QPainter, w: int) -> None:
        """
        Small status badge drawn above the image button (y < 14).
        Green pulse = healthy.  Static red = comm failure.
        Invisible when heartbeat is disabled.
        """
        if not self._heartbeat_enabled:
            return

        if self._heartbeat_warning:
            dot_color = QColor("#ff0038")
            label     = f"HB FAIL  ({self._hb_consecutive_misses} missed)"
        else:
            pulse     = 0.45 + 0.55 * abs(math.sin(self.t * 1.9))
            dot_color = QColor(0, 255, 37, int(210 * pulse))
            label     = "HB OK"

        # Dot
        dot_x = w - 168.0
        dot_y = 8.0
        painter.setBrush(dot_color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(dot_x, dot_y), 4, 4)

        # Label text
        painter.setPen(dot_color)
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.drawText(QRectF(dot_x + 10, dot_y - 7, 150, 15),
                         Qt.AlignLeft | Qt.AlignVCenter, label)

    # -----------------------------------------------------------------------
    # Section 5: Volume sliders
    # -----------------------------------------------------------------------

    def _draw_volume_sliders(self, painter: QPainter) -> None:
        self._compute_vol_rects()
        self._draw_one_slider(painter, self._vol_rect_left,  self._left_volume,
                              "LVol", active=self._dragging_slider == "left")
        self._draw_one_slider(painter, self._vol_rect_right, self._right_volume,
                              "RVol", active=self._dragging_slider == "right")

    def _draw_one_slider(self, painter: QPainter, rect: QRectF,
                         value: float, label: str, active: bool) -> None:
        fill_color = QColor("#7adfff") if active else QColor("#00d9e8")
        fill_h     = rect.height() * (value / 100.0)

        # Track
        painter.setBrush(QColor("#1a2030"))
        painter.setPen(QPen(QColor("#2a3a55"), 1))
        painter.drawRoundedRect(rect, 5, 5)

        # Filled portion (bottom-up)
        if fill_h > 0:
            fill_rect = QRectF(rect.x(), rect.bottom() - fill_h,
                               rect.width(), fill_h)
            painter.setBrush(fill_color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(fill_rect, 5, 5)

        # Thumb line
        thumb_y = rect.bottom() - fill_h
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(QPointF(rect.x(), thumb_y), QPointF(rect.right(), thumb_y))

        # Label above slider
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.setPen(QColor("#6677aa"))
        painter.drawText(QRectF(rect.x() - 4, rect.top() - 18, rect.width() + 8, 16),
                         Qt.AlignCenter, label)

        # Value below slider
        painter.setFont(QFont("Arial", 9))
        painter.setPen(fill_color if active else QColor("#445566"))
        painter.drawText(QRectF(rect.x() - 4, rect.bottom() + 2, rect.width() + 8, 16),
                         Qt.AlignCenter, f"{value:.0f}")

    # -----------------------------------------------------------------------
    # Section 5: Hint bar
    # -----------------------------------------------------------------------

    def _draw_hints(self, painter: QPainter, w: int, h: int) -> None:
        hb_label = "HB On" if self._heartbeat_enabled else "HB Off"
        hints    = [("[M]", "Câmeras"), ("[I]", "Diagnósticos"),
                    ("[F]", "♯ Modo"),  ("[H]", hb_label)]
        key_font = QFont("Arial", 11, QFont.Bold)
        lbl_font = QFont("Arial", 11)
        sep_gap  = 18
        hint_y   = h - 22

        painter.setFont(key_font)
        fm_key = painter.fontMetrics()
        painter.setFont(lbl_font)
        fm_lbl = painter.fontMetrics()

        parts   = []
        total_w = 0
        for key, label in hints:
            kw = fm_key.horizontalAdvance(key)
            lw = fm_lbl.horizontalAdvance("  " + label)
            parts.append((key, label, kw, lw))
            total_w += kw + lw
        total_w += sep_gap * (len(hints) - 1)

        hx = (w - total_w) / 2
        for i, (key, label, kw, lw) in enumerate(parts):
            # [H] key turns red when heartbeat is warning
            is_hb_key   = (i == len(hints) - 1)
            key_color   = (QColor("#ff0038") if is_hb_key and self._heartbeat_warning
                           else QColor("#00d9e8"))
            painter.setFont(key_font)
            painter.setPen(key_color)
            painter.drawText(QRectF(hx, hint_y - 14, kw, 18),
                             Qt.AlignLeft | Qt.AlignVCenter, key)
            hx += kw
            painter.setFont(lbl_font)
            painter.setPen(QColor("#3a4a5a"))
            painter.drawText(QRectF(hx, hint_y - 14, lw, 18),
                             Qt.AlignLeft | Qt.AlignVCenter, "  " + label)
            hx += lw + sep_gap

    # -----------------------------------------------------------------------
    # Section 5: Geometry helpers
    # -----------------------------------------------------------------------

    def section_at(self, pos: QPointF) -> int:
        cx, cy  = self.width() / 2, self.height() / 2
        size    = min(self.width(), self.height())
        outer_r = size * 0.36 + 22
        inner_r = size * 0.235
        dx, dy  = pos.x() - cx, pos.y() - cy
        dist    = math.hypot(dx, dy)
        if dist < inner_r or dist > outer_r:
            return -1
        angle = (-math.degrees(math.atan2(dy, dx)) + 360) % 360
        return int(angle // 60) % 6

    def using_image_mode(self) -> bool:
        return (self.image_mode or self.blue_hand_closed
                or time.monotonic() < self.sharp_mode_until)

    def cover_source_rect(self, iw: int, ih: int) -> QRectF:
        if iw <= 0 or ih <= 0:
            return QRectF()
        if iw / ih > 1.0:
            sw, sh = ih * 1.0, float(ih)
            return QRectF((iw - sw) / 2, 0, sw, sh)
        sw, sh = float(iw), iw / 1.0
        return QRectF(0, (ih - sh) / 2, sw, sh)

    # -----------------------------------------------------------------------
    # Section 5: Wave renderer (background, unchanged)
    # -----------------------------------------------------------------------

    def _draw_wave(self, painter: QPainter, x0: float, y0: float,
                   length: int = 485, channels: list | None = None) -> None:
        wave_count = 4
        spacing    = 44
        speed      = self.t * 4.0
        base_amp   = 20 + 15 * self.wave_amplitude
        colors     = [QColor("#ff3a9e"), QColor("#cde70b"),
                      QColor("#00eaff"), QColor("#ff8500")]

        if channels and len(channels) >= wave_count:
            amps    = [ch["amplitude"]   for ch in channels[:wave_count]]
            wknums  = [0.025 + 0.060 * (ch["frequency_hz"] / 500.0)
                       for ch in channels[:wave_count]]
            phases  = [math.radians(ch["phase_deg"]) for ch in channels[:wave_count]]
        else:
            amps   = [1.0] * 4
            wknums = [0.055] * 4
            phases = [0.0, math.pi / 2, math.pi, math.pi * 1.5]

        for wi in range(wave_count):
            baseline = y0 + (wi - 1.5) * spacing
            amp      = base_amp * amps[wi]
            ph       = phases[wi]
            wk       = wknums[wi]
            col      = colors[wi]
            pts      = [QPointF(x0 + x, baseline + math.sin(x * wk + speed + ph) * amp)
                        for x in range(0, length, 3)]

            glow = QColor(col); glow.setAlpha(42)
            painter.setPen(QPen(glow, 10, Qt.SolidLine, Qt.RoundCap))
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])

            lc = QColor(col); lc.setAlpha(210)
            painter.setPen(QPen(lc, 3, Qt.SolidLine, Qt.RoundCap))
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])

            mx = (self.t * 68 + wi * 36) % length
            my = baseline + math.sin(mx * wk + speed + ph) * amp
            painter.setBrush(col)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawEllipse(QPointF(x0 + mx, my), 6, 6)

            painter.setPen(QColor(255, 255, 255, 170))
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.drawText(QRectF(x0 - 38, baseline - 10, 32, 20),
                             Qt.AlignRight, f"{wi * 90}")

    # -----------------------------------------------------------------------
    # Section 5: Selector
    # -----------------------------------------------------------------------

    def _draw_selector(self, painter: QPainter,
                       cx: float, cy: float, radius: float) -> None:
        channels  = _config_channels(self.current_config())
        avg_amp   = (sum(ch["amplitude"] for ch in channels) / len(channels)
                     if channels else 1.0)
        glow_a    = int(45 + 205 * self.wave_amplitude * avg_amp)
        colors    = self.image_colors if self.using_image_mode() else self.section_colors
        gc        = QColor(colors[self.selected_section]); gc.setAlpha(glow_a)
        glow      = QRadialGradient(QPointF(cx, cy), radius + 70)
        glow.setColorAt(0.45, QColor(0, 0, 0, 0))
        glow.setColorAt(0.76, gc)
        glow.setColorAt(1.0,  QColor(0, 0, 0, 0))

        painter.setBrush(glow)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), radius + 70, radius + 70)

        span = 60 * 16
        for i, color in enumerate(colors):
            outer_r = radius + 20 if i in (self.selected_section, self.hover_section) else radius
            rect    = QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
            fill    = QColor(color)
            fill.setAlpha(245 if i == self.selected_section else 195)
            if i == self.hover_section:
                fill = fill.lighter(135)
            painter.setBrush(fill)
            painter.setPen(Qt.NoPen)
            painter.drawPie(rect, i * span, span)

        painter.setBrush(QColor("#1b1b1d"))
        painter.setPen(QPen(QColor("#303035"), 4))
        painter.drawEllipse(QPointF(cx, cy), radius * 0.72, radius * 0.72)

        painter.setFont(QFont("Arial", 34, QFont.Bold))
        for i in range(6):
            label = self.image_labels[i] if self.using_image_mode() else self.sector_labels[i]
            a     = math.radians(-(i * 60 + 30))
            tx    = cx + math.cos(a) * radius * 0.86
            ty    = cy + math.sin(a) * radius * 0.86
            painter.setPen(QColor("#050505"))
            painter.drawText(QRectF(tx - 36, ty - 28, 72, 56), Qt.AlignCenter, label)

        self._draw_dwell_loader(painter, cx, cy, radius)

    def _draw_dwell_loader(self, painter: QPainter,
                           cx: float, cy: float, radius: float) -> None:
        if self.dwell_section < 0 or self.dwell_progress <= 0:
            return
        a    = math.radians(-(self.dwell_section * 60 + 30))
        tx   = cx + math.cos(a) * radius * 0.66
        ty   = cy + math.sin(a) * radius * 0.66
        rect = QRectF(tx - 18, ty - 18, 36, 36)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 80), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor("#ffffff"), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect, 90 * 16, int(-360 * 16 * self.dwell_progress))

    # -----------------------------------------------------------------------
    # Section 5: Chladni plate
    # -----------------------------------------------------------------------

    def _draw_reference_center(self, painter: QPainter,
                                cx: float, cy: float, radius: float) -> None:
        if self.center_live_image is not None and not self.center_live_image.isNull():
            target = QRectF(cx - radius * 0.86, cy - radius * 0.86,
                            radius * 1.72, radius * 1.72)
            source = self.cover_source_rect(self.center_live_image.width(),
                                            self.center_live_image.height())
            clip = QPainterPath()
            clip.addEllipse(target)
            painter.save()
            painter.setClipPath(clip)
            painter.drawImage(target, self.center_live_image, source)
            painter.restore()
        else:
            self._draw_chladni_plate(painter, cx, cy, radius, 7)

    def _draw_reference_disc(self, painter: QPainter,
                              cx: float, cy: float, radius: float) -> None:
        self._draw_chladni_plate(painter, cx, cy, radius, 4)

    def _draw_chladni_plate(self, painter: QPainter,
                             cx: float, cy: float,
                             radius: float, detail: int) -> None:
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

        n     = detail + self.selected_section % 3
        m     = detail + 2 + (self.selected_section + 1) % 4
        scale = math.pi / radius
        step  = max(3, int(radius / 34))
        painter.setPen(QPen(QColor("#2d1a0d"),
                            max(2, int(radius * 0.018)),
                            Qt.SolidLine, Qt.RoundCap))
        self._draw_chladni_contours(painter, cx, cy, radius * 0.83, n, m, scale, step)
        painter.restore()

        painter.setPen(QPen(QColor("#7c4a1f"), max(1, int(radius * 0.012))))
        for ring in (0.32, 0.58, 0.82):
            painter.drawEllipse(QPointF(cx, cy), radius * ring, radius * ring)

    def _draw_chladni_contours(self, painter: QPainter,
                                cx: float, cy: float, radius: float,
                                n: int, m: int,
                                scale: float, step: int) -> None:
        xs, xe = int(cx - radius), int(cx + radius)
        ys, ye = int(cy - radius), int(cy + radius)

        def val(x: float, y: float) -> float:
            dx, dy = x - cx, y - cy
            return (math.sin(n * dx * scale) * math.sin(m * dy * scale) -
                    math.sin(m * dx * scale) * math.sin(n * dy * scale))

        def inside(x: float, y: float) -> bool:
            return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2

        for y in range(ys, ye, step):
            for x in range(xs, xe, step):
                corners = [
                    (x,        y,        val(x,        y)),
                    (x + step, y,        val(x + step, y)),
                    (x + step, y + step, val(x + step, y + step)),
                    (x,        y + step, val(x,        y + step)),
                ]
                crossings: list[QPointF] = []
                for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
                    x1, y1, v1 = corners[a]
                    x2, y2, v2 = corners[b]
                    if v1 == 0:
                        crossings.append(QPointF(x1, y1))
                    elif v1 * v2 < 0:
                        t  = abs(v1) / (abs(v1) + abs(v2))
                        px = x1 + (x2 - x1) * t
                        py = y1 + (y2 - y1) * t
                        if inside(px, py):
                            crossings.append(QPointF(px, py))
                if len(crossings) >= 2:
                    painter.drawLine(crossings[0], crossings[1])

    # -----------------------------------------------------------------------
    # Section 5: Hand tracking renderers
    # -----------------------------------------------------------------------

    def _draw_hands(self, painter: QPainter) -> None:
        has_hand = self.external_left_hand or self.external_right_hand
        if not has_hand:
            return
        if time.monotonic() - self.external_hands_time > self.external_hands_hold:
            return
        if self.external_left_hand:
            self._draw_real_hand(painter, self.external_left_hand,
                                 QColor("#00eaff"), self.blue_hand_closed)
        if self.external_right_hand:
            self._draw_real_hand(painter, self.external_right_hand,
                                 QColor("#ff3030"), False)

    def _draw_real_hand(self, painter: QPainter,
                        landmarks: list, color: QColor, closed: bool) -> None:
        if len(landmarks) < 21:
            return
        bones = [
            (0,1),(1,2),(2,3),(3,4),
            (0,5),(5,6),(6,7),(7,8),
            (5,9),(9,10),(10,11),(11,12),
            (9,13),(13,14),(14,15),(15,16),
            (13,17),(0,17),(17,18),(18,19),(19,20),
        ]
        lc = QColor(color); lc.setAlpha(210)
        pc = QColor("#ffffff"); pc.setAlpha(235)

        painter.setPen(QPen(lc, 9, Qt.SolidLine, Qt.RoundCap))
        for a, b in bones:
            painter.drawLine(landmarks[a], landmarks[b])

        painter.setBrush(pc)
        painter.setPen(QPen(color, 4))
        for idx, pt in enumerate(landmarks):
            r = 11 if idx in (4, 8, 12, 16, 20) else 8
            painter.drawEllipse(pt, r, r)

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

    # -----------------------------------------------------------------------
    # Section 5: Image-mode toggle button
    # -----------------------------------------------------------------------

    def _draw_image_button(self, painter: QPainter, x: float, y: float) -> None:
        self.image_btn_rect = QRectF(x, y, 88, 64)
        base = QColor("#1d8dbf") if self.using_image_mode() else QColor("#24252b")
        if self.image_btn_hover:
            base = base.lighter(132)

        painter.setBrush(base)
        border_col = QColor("#7adfff") if self.using_image_mode() else QColor("#4a4c55")
        painter.setPen(QPen(border_col, 3))
        painter.drawRoundedRect(self.image_btn_rect, 8, 8)

        painter.setPen(QPen(QColor("white"), 3, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(QColor(255, 255, 255, 42))

        cx = self.image_btn_rect.center().x()
        cy = self.image_btn_rect.center().y()
        painter.drawRoundedRect(QRectF(cx - 18, cy - 2, 36, 24), 8, 8)
        for i in range(4):
            painter.drawRoundedRect(
                QRectF(cx - 22 + i * 11, self.image_btn_rect.top() + 16, 10, 24), 5, 5)
        painter.drawLine(QPointF(cx - 8, cy + 20), QPointF(cx - 18, cy + 10))
        painter.drawLine(QPointF(cx + 8, cy + 20), QPointF(cx + 18, cy + 10))


# ===========================================================================
# Standalone entry point (dev/test — normally launched via main.py)
# ===========================================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w   = MainWindow()
    w.show()
    sys.exit(app.exec())
