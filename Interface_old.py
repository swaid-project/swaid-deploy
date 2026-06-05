"""
Interface.py — MainWindow for SWAID-ESIS.

Sections
--------
1. Imports & Framework Setup
2. Configuration & Constants
3. ResonanceClient Integration (replaces raw ctypes)
4. State Management & Timers
5. UI Layout & Event Routines
"""

# ===========================================================================
# 1. IMPORTS & FRAMEWORK SETUP
# ===========================================================================

import json
import math
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore  import QPointF, QRectF, Qt, QThread, QTimer, Signal
# DIFF 9: Added QPolygonF (was missing from HI-Integration import)
from PySide6.QtGui   import (QColor, QFont, QImage, QPainter, QPainterPath,
                              QPen, QPixmap, QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

# Add resonance_sdk to the Python path so ResonanceClient can be imported
# regardless of the working directory the app is launched from.
_SDK_DIR = Path(__file__).parent.parent / "plate-resonance" / "resonance_sdk"
if str(_SDK_DIR) not in sys.path:
    sys.path.insert(0, str(_SDK_DIR))

try:
    from resonance_client import ResonanceClient
    _RESONANCE_CLIENT_AVAILABLE = True
except ImportError as _rc_err:
    print(f"[ResonanceClient] Import failed: {_rc_err} — simulated mode active.")
    ResonanceClient             = None
    _RESONANCE_CLIENT_AVAILABLE = False


# ===========================================================================
# 2. CONFIGURATION & CONSTANTS
# ===========================================================================

# -- Asset paths -------------------------------------------------------------
_ASSETS_DIR          = Path(__file__).parent / "assets"
_LOGO_FILE           = "FEUPLogo.png"
_MASTER_SYMBOLS_PATH = Path(__file__).parent.parent / "master_symbols.json"

# -- ResonanceClient endpoint ------------------------------------------------
_RESONANCE_ENDPOINT = "ipc:///tmp/swaid.sock"

# -- SDK volume defaults (0 – 100 integer scale) ----------------------------
_DEFAULT_LEFT_VOLUME  = 100
_DEFAULT_RIGHT_VOLUME = 100

# -- Heartbeat ---------------------------------------------------------------
_HEARTBEAT_INTERVAL_S     = 2
_HEARTBEAT_MISS_THRESHOLD = 3

# -- Chromatic note map: label → music_note 0-11 (C=0 … B=11) ---------------
NOTE_MAP: dict[str, int] = {
    "C": 0, "C#": 1, "D": 2,  "D#": 3,
    "E": 4, "F":  5, "F#": 6, "G":  7,
    "G#": 8, "A": 9, "A#": 10, "B": 11,
}

# -- Idle / attract-cycle timing ---------------------------------------------
_IDLE_TIMEOUT_S   = 5 * 60
_CYCLE_INTERVAL_S = 60
_TOTAL_NOTES      = 12

# DIFF 10: Added _STANDBY_TIMEOUT_S (was missing from HI-Integration)
# -- Standby attract mode ----------------------------------------------------
_STANDBY_TIMEOUT_S = 5 * 60   # seconds without hand detection → show standby

# DIFF 11: Added _GHOST_HAND_PTS (was missing from HI-Integration)
# Normalized open-palm hand shape (21 MediaPipe-order points).
# Thumb points LEFT (−x) = right hand frontal view.
# Flip x for left hand.
_GHOST_HAND_PTS = (
    ( 0.00,  0.00),  # 0  wrist
    (-0.30, -0.20),  # 1  thumb cmc
    (-0.50, -0.38),  # 2  thumb mcp
    (-0.63, -0.52),  # 3  thumb ip
    (-0.70, -0.63),  # 4  thumb tip
    (-0.12, -0.52),  # 5  index mcp
    (-0.14, -0.70),  # 6  index pip
    (-0.15, -0.83),  # 7  index dip
    (-0.15, -0.93),  # 8  index tip
    ( 0.00, -0.56),  # 9  middle mcp
    ( 0.00, -0.76),  # 10 middle pip
    ( 0.00, -0.90),  # 11 middle dip
    ( 0.00, -1.00),  # 12 middle tip
    ( 0.13, -0.52),  # 13 ring mcp
    ( 0.15, -0.70),  # 14 ring pip
    ( 0.15, -0.83),  # 15 ring dip
    ( 0.15, -0.93),  # 16 ring tip
    ( 0.26, -0.43),  # 17 pinky mcp
    ( 0.28, -0.58),  # 18 pinky pip
    ( 0.28, -0.68),  # 19 pinky dip
    ( 0.28, -0.76),  # 20 pinky tip
)

# DIFF 12: Added _WAVE_STEP_BG / _WAVE_STEP_CIRCLE (were missing from HI-Integration)
# -- Render quality (bigger step = fewer points = better FPS) ----------------
_WAVE_STEP_BG     = 3
_WAVE_STEP_CIRCLE = 3


# ===========================================================================
# 2b. MASTER SYMBOLS PARSER  (Spec 3 — zero hardcoded symbol data)
# ===========================================================================

def _load_master_symbols() -> "dict[str, dict]":
    """
    Parse master_symbols.json into {display_name: {music_note, led_effect,
    channels, image_path}}.

    Searched in order:
      swaid-deploy/master_symbols.json  (canonical shared path)
      swaid-deploy/master_symbol.json   (legacy singular name)
      human-interface/master_symbols.json

    Returns an empty dict on absence or parse failure — all callers must
    treat an empty SYMBOLS as a valid (unconfigured) state.
    """
    candidates = [
        Path(__file__).parent.parent / "master_symbols.json",
        Path(__file__).parent.parent / "master_symbol.json",
        Path(__file__).parent / "master_symbols.json",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        print("[Symbols] master_symbols.json not found — no symbol data loaded.")
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        print(f"[Symbols] Parse error: {exc}")
        return {}

    entries: list = raw if isinstance(raw, list) else raw.get("symbols", [])
    result: dict[str, dict] = {}
    for entry in entries:
        name = entry.get("display_name")
        if not name:
            continue
        result[name] = {
            "music_note": int(entry.get("music_note", 0)),
            "led_effect": int(entry.get("LED_effect", 0)),
            "channels":   entry.get("hardware_config", {}).get("channels", []),
            "image_path": entry.get("ui_metadata", {}).get("image_path", ""),
        }

    print(f"[Symbols] Loaded {len(result)} symbols from {path.name}: "
          f"{', '.join(result)}")
    return result


# Module-level symbol map — populated once at import time.
SYMBOLS: dict[str, dict] = _load_master_symbols()


def _load_logo() -> "QPixmap | None":
    candidates = [_LOGO_FILE, "FEUPLogo.tiff", "FEUPLogo.tif",
                  "LogoFeup.png", "LogoFeup.tiff", "LogoFeup.tif"]
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

    try:
        pix = QPixmap(str(path))
        if not pix.isNull():
            return pix
    except Exception:
        pass
    try:
        pil_img = Image.open(path).convert("RGBA")
        arr = np.array(pil_img, dtype=np.uint8)
        h, w = arr.shape[:2]
        qimg = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
        return QPixmap.fromImage(qimg)
    except Exception:
        return None


# ===========================================================================
# 3. RESONANCECLIENT INTEGRATION
# ===========================================================================
# All ZMQ communication is owned by ResonanceThread, a QThread with a
# lock-protected command queue.  The main thread enqueues work non-blocking
# and receives results via Qt signals — zero blocking on the paint/event loop.
#
# ResonanceClient uses zmq.REQ/REP (not ctypes/PUSH-PULL).
# Key method: trigger_symbol(chladni_id, music_note, led_effect_id, vol_l, vol_r)
# Returns bool: True = server ACK received, False = timeout / error.
# ===========================================================================

class ResonanceThread(QThread):
    """
    Background thread that owns the ResonanceClient REQ/REP socket.
    Dequeues 'trigger' and 'ping' commands and emits results as signals.
    The 1-second socket timeout lives here, not on the UI thread.
    """
    trigger_result = Signal(bool, str, int)   # (ok, chladni_id, note_id)
    ping_result    = Signal(bool)             # True = pong received

    def __init__(self, endpoint: str, parent=None):
        super().__init__(parent)
        self._endpoint = endpoint
        self._client: "ResonanceClient | None" = None
        self._lock    = threading.Lock()
        self._queue: list = []
        self._running = True

    # -- Public API (safe to call from any thread) ---------------------------

    def enqueue_trigger(self, chladni_id: str, note_id: int,
                        led_effect: int, vol_l: int, vol_r: int) -> None:
        with self._lock:
            self._queue.append(("trigger", chladni_id, note_id,
                                led_effect, vol_l, vol_r))

    def enqueue_ping(self) -> None:
        with self._lock:
            self._queue.append(("ping",))

    def stop(self) -> None:
        self._running = False

    # -- Thread body ---------------------------------------------------------

    def run(self) -> None:
        if ResonanceClient is not None:
            try:
                self._client = ResonanceClient(self._endpoint)
                print(f"[ResonanceClient] Connected → {self._endpoint}")
            except Exception as exc:
                print(f"[ResonanceClient] Init error: {exc} — simulated mode.")

        while self._running:
            with self._lock:
                msg = self._queue.pop(0) if self._queue else None

            if msg is None:
                self.msleep(10)
                continue

            kind = msg[0]
            if kind == "trigger":
                _, chladni_id, note_id, led_effect, vol_l, vol_r = msg
                if self._client is not None:
                    ok = self._client.trigger_symbol(
                        chladni_id, note_id, led_effect, vol_l, vol_r)
                else:
                    print(f"[ResonanceClient sim] trigger_symbol({chladni_id!r}, "
                          f"note={note_id}, led={led_effect}, "
                          f"L={vol_l}, R={vol_r})")
                    ok = True
                self.trigger_result.emit(ok, chladni_id, note_id)

            elif kind == "ping":
                if self._client is not None:
                    ok = self._client.ping()
                else:
                    ok = False  # simulated: always offline
                self.ping_result.emit(ok)


# ===========================================================================
# 4. STATE MANAGEMENT & TIMERS
# ===========================================================================
# MainWindow subsystems:
#
#   ResonanceThread — self._resonance
#                     All trigger_symbol / ping calls dispatched through it.
#
#   Heartbeat       — _heartbeat_enabled / _heartbeat_warning /
#                     _hb_consecutive_misses / _hb_timer (QTimer 2 s).
#                     [H] key toggles.  Pong comes back via ping_result signal.
#
#   Volumes         — _left_volume / _right_volume (int 0-100).
#
#   Debounce        — _last_note_change (time.time float, 1 s gate).
#
#   Idle            — _last_interaction / _idle_timer (QTimer 60 s).
#
# Symbol images:     _symbol_images (dict[str, QImage]) — preloaded in __init__.
# ===========================================================================


# ===========================================================================
# 5. UI LAYOUT & EVENT ROUTINES
# ===========================================================================

class MainWindow(QWidget):
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
        self._init_state()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        # DIFF 13: Changed from 16 ms to 33 ms to match main branch
        self.timer.start(33)

        self._logo = _load_logo()

        # Preload dictionary symbol images into cache
        self._symbol_images: dict[str, QImage] = {}
        self._preload_symbol_images()

    def _preload_symbol_images(self) -> None:
        """Load ui_metadata.image_path for every SYMBOLS entry into QImage cache."""
        base = _MASTER_SYMBOLS_PATH.parent
        for name, entry in SYMBOLS.items():
            raw = entry.get("image_path", "")
            if not raw:
                continue
            img_path = (base / raw.lstrip("./")).resolve()
            if not img_path.exists():
                continue
            try:
                pil_img = Image.open(img_path).convert("RGBA")
                arr     = np.array(pil_img, dtype=np.uint8)
                h, w    = arr.shape[:2]
                qimg    = QImage(arr.data, w, h, w * 4,
                                 QImage.Format_RGBA8888).copy()
                self._symbol_images[name] = qimg
                print(f"[Symbols] Image loaded: {name}")
            except Exception as exc:
                print(f"[Symbols] Image load failed for {name}: {exc}")

    def _init_animation_state(self) -> None:
        # DIFF 14: Added _anim_last_time (for dt-based animation)
        self.t                   = 0.0
        self._anim_last_time     = 0.0
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
        self.dwell_duration      = 1 # tempo lock utilizador para selecionar nota
        self._dwell_note_id      = 0    # note locked when dwell begins, immune to mode changes
        self._selected_note_id   = 0    # committed note — drives preview/waves, NOT using_image_mode
        self._dwell_armed        = True # cursor must leave ring before the SAME note can re-fire
        self.image_btn_hover     = False
        self.image_btn_rect      = QRectF()

        # Spec 1: center circle enlarged (0.265 → 0.33)
        self.selector_radius_scale     = 0.39
        self.center_plate_radius_scale = 0.33
        # DIFF 14: Added _chladni_cache, _standby_active, _last_hand_at, _hints_visible
        self._chladni_cache: "dict[tuple, QPixmap]" = {}
        self._standby_active           = False
        self._last_hand_at             = time.monotonic()
        self._hints_visible            = True

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

        # -- ResonanceThread (Section 3) -------------------------------------
        self._resonance = ResonanceThread(_RESONANCE_ENDPOINT, self)
        self._resonance.trigger_result.connect(self._on_trigger_result)
        self._resonance.ping_result.connect(self._on_ping_result)
        self._resonance.start()

        # -- Heartbeat -------------------------------------------------------
        self._heartbeat_enabled:     bool = True
        self._heartbeat_warning:     bool = False
        self._hb_consecutive_misses: int  = 0

        self._hb_timer = QTimer(self)
        self._hb_timer.setInterval(_HEARTBEAT_INTERVAL_S * 1000)
        self._hb_timer.timeout.connect(self._heartbeat_tick)
        self._hb_timer.start()

        # -- Volumes ---------------------------------------------------------
        self._left_volume:  int = _DEFAULT_LEFT_VOLUME
        self._right_volume: int = _DEFAULT_RIGHT_VOLUME

        # -- Debounce --------------------------------------------------------
        self._last_note_change: float = 0.0

        # -- Idle ------------------------------------------------------------
        self._last_interaction: float = time.monotonic()
        self._idle_active:      bool  = False
        self._idle_note:        int   = 0

        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(_CYCLE_INTERVAL_S * 1000)
        self._idle_timer.timeout.connect(self._advance_idle_cycle)

    # -----------------------------------------------------------------------
    # Section 3: ResonanceThread result handlers
    # -----------------------------------------------------------------------

    def _on_trigger_result(self, ok: bool, chladni_id: str, note_id: int) -> None:
        ts = time.strftime("%H:%M:%S")
        status = "OK" if ok else "FAILED"
        print(f"[{ts}] [ResonanceClient] trigger_symbol {status} — "
              f"{chladni_id}  note={note_id}")

    def _on_ping_result(self, ok: bool) -> None:
        ts = time.strftime("%H:%M:%S")
        if ok:
            print(f"[{ts}] [Heartbeat] Pong received — link OK")
            self._hb_consecutive_misses = 0
            if self._heartbeat_warning:
                self._heartbeat_warning = False
                print(f"[{ts}] [Heartbeat] Comm link restored")
        else:
            self._hb_consecutive_misses += 1
            print(f"[{ts}] [Heartbeat] No pong "
                  f"(consecutive misses: {self._hb_consecutive_misses})")
            if (self._hb_consecutive_misses >= _HEARTBEAT_MISS_THRESHOLD
                    and not self._heartbeat_warning):
                self._heartbeat_warning = True
                print(f"[{ts}] [Heartbeat] WARNING — "
                      f"{self._hb_consecutive_misses} pings without pong")
        self.update()


    # -----------------------------------------------------------------------
    # Section 4: Heartbeat
    # -----------------------------------------------------------------------

    def _toggle_heartbeat(self) -> None:
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
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [Heartbeat] Ping dispatched "
              f"(current miss streak: {self._hb_consecutive_misses})")
        self._resonance.enqueue_ping()

    # -----------------------------------------------------------------------
    # Section 4: Idle / attract-cycle
    # -----------------------------------------------------------------------

    def _chladni_id_for_note(self, note_id: int) -> str:
        for name, entry in SYMBOLS.items():
            if entry["music_note"] == note_id:
                return name
        return ""

    def _enter_idle_mode(self) -> None:
        if self._idle_active:
            return
        self._idle_active = True
        self._idle_note   = 0
        print(f"[Idle] Entering cycle mode ({_IDLE_TIMEOUT_S // 60} min idle).")
        self._dispatch_idle_note()
        self._idle_timer.start()

    def _advance_idle_cycle(self) -> None:
        self._idle_note = (self._idle_note + 1) % _TOTAL_NOTES
        self._dispatch_idle_note()

    def _dispatch_idle_note(self) -> None:
        chladni_id = self._chladni_id_for_note(self._idle_note)
        ts = time.strftime("%H:%M:%S")
        if chladni_id:
            led = SYMBOLS[chladni_id]["led_effect"]
            print(f"[{ts}] [Idle] Cycle → note {self._idle_note} ({chladni_id})")
            self._resonance.enqueue_trigger(
                chladni_id, self._idle_note, led,
                self._left_volume, self._right_volume,
            )
        else:
            print(f"[{ts}] [Idle] Cycle → note {self._idle_note} (no symbol)")

    def _exit_idle_mode(self) -> None:
        if not self._idle_active:
            return
        self._idle_active = False
        self._idle_timer.stop()
        print("[Idle] User detected — exiting cycle mode.")

    def _record_interaction(self) -> None:
        self._last_interaction = time.monotonic()
        self._exit_idle_mode()

    # -----------------------------------------------------------------------
    # Section 4: Note-ID / symbol resolution (reads from SYMBOLS only)
    # -----------------------------------------------------------------------

    def _note_id_for_section(self, section: int) -> int:
        labels = self.image_labels if self.using_image_mode() else self.sector_labels
        return NOTE_MAP.get(labels[section % len(labels)], 0)

    def _symbol_name_for_section(self, section: int) -> str:
        return self._chladni_id_for_note(self._note_id_for_section(section))

    def _channels_for_section(self, section: int) -> list[dict]:
        """
        Return hardware channel array from SYMBOLS for the given section.
        Returns [] if SYMBOLS is empty or note unmapped — _draw_wave handles
        the empty case with built-in fallback rendering.
        """
        note_id = self._note_id_for_section(section)
        return self._channels_for_note(note_id)

    def _channels_for_note(self, note_id: int) -> list[dict]:
        """Hardware channel array for a committed note_id (independent of hand mode)."""
        for entry in SYMBOLS.values():
            if entry["music_note"] == note_id:
                return entry["channels"]
        return []

    def _display_note_id(self) -> int:
        """
        The note currently shown by preview + waves.
        Idle cycle note while attract-mode runs, otherwise the committed
        selection.  NEVER derived from section/using_image_mode — so opening
        or closing the hand cannot change what is displayed.
        """
        return self._idle_note if self._idle_active else self._selected_note_id

    # -----------------------------------------------------------------------
    # Section 5: Core widget interface (called by main.py)
    # -----------------------------------------------------------------------

    # DIFF 16: Added trigger_standby_test / _enter_standby / _exit_standby
    def trigger_standby_test(self) -> None:
        self._enter_standby()
        self.update()

    def _enter_standby(self) -> None:
        if self._standby_active:
            return
        self._standby_active = True
        print("[Standby] Entering standby mode.")

    def _exit_standby(self) -> None:
        if not self._standby_active:
            return
        self._standby_active = False
        print("[Standby] Exiting standby mode.")

    def set_tracked_hands(self, left_hand=None, right_hand=None,
                          blue_hand_closed: bool = False,
                          cursor_point=None) -> None:
        if left_hand is not None or right_hand is not None:
            # DIFF 15: Added standby exit logic
            self._last_hand_at = time.monotonic()
            self._exit_standby()
            self._record_interaction()

        self.external_left_hand  = left_hand
        self.external_right_hand = right_hand
        self.external_hands_time = time.monotonic()
        # blue_hand_closed is stored for visual rendering only — Spec 2:
        # hand open/close gestures are completely removed from note selection.
        self.blue_hand_closed = blue_hand_closed

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

    # DIFF 17: Updated to dt-based time advancement + standby check
    def update_animation(self) -> None:
        now = time.monotonic()
        if self._anim_last_time == 0.0:
            self._anim_last_time = now
        dt = min(now - self._anim_last_time, 0.05)  # cap: skip big jumps after pause
        self._anim_last_time = now
        self.t += dt * 3.0  # 3.0 keeps same apparent speed as the old 0.05 at ~60 fps
        channels = self._channels_for_note(self._display_note_id())
        if channels:
            avg_freq = sum(ch["frequency_hz"] for ch in channels) / len(channels)
        else:
            avg_freq = 200.0

        # wave_amplitude is a pure visual oscillator — decoupled from
        # hardware amplitude values (tiny floats in master_symbols.json).
        self.wave_amplitude = 0.50 + 0.45 * abs(math.sin(self.t * 0.9))
        self.frequency      = avg_freq

        if not self._idle_active:
            if time.monotonic() - self._last_interaction >= _IDLE_TIMEOUT_S:
                self._enter_idle_mode()

        # DIFF 17: Added standby timeout check
        if (not self._standby_active
                and time.monotonic() - self._last_hand_at >= _STANDBY_TIMEOUT_S):
            self._enter_standby()

        self.update_dwell_selection()
        self.update()

    # -----------------------------------------------------------------------
    # Section 4: Dwell selection — Spec 2 gesture lock
    # -----------------------------------------------------------------------

    def update_dwell_selection(self) -> None:
        if self._idle_active:
            return

        section = self.section_at(self.mouse_pos)
        now     = time.monotonic()

        if section < 0:
            self.dwell_section  = -1
            self.dwell_progress = 0.0
            self._dwell_armed   = True   # cursor left the ring → re-arm for re-selection
            return

        # needs_selection: dwell allowed on a different section, OR on the same
        # section after the cursor has left the ring and returned (_dwell_armed).
        # This lets the user re-select the same note by exiting and re-entering.
        needs_selection = section != self.selected_section or self._dwell_armed
        if not needs_selection or section != self.dwell_section:
            self.dwell_section    = section
            self.dwell_started_at = now
            self.dwell_progress   = 0.0
            # Lock the note_id now, at dwell start.
            # If hand opens/closes mid-dwell (mode changes), this stays fixed.
            self._dwell_note_id   = self._note_id_for_section(section)
            return

        self.dwell_progress = min(1.0, (now - self.dwell_started_at) / self.dwell_duration)
        if self.dwell_progress < 1.0:
            return

        # Debounce: reject rapid repeated triggers
        wall_now = time.time()
        if wall_now - self._last_note_change < 1.0:
            self.dwell_progress = 0.0
            return

        # Accept selection — use _dwell_note_id locked at dwell start.
        # This means hand open/close mid-dwell cannot change what note gets sent.
        self.selected_section  = section
        self._selected_note_id = self._dwell_note_id   # commit — display reads this
        chladni_id = self._chladni_id_for_note(self._dwell_note_id)
        if chladni_id:
            sym_channels = SYMBOLS[chladni_id]["channels"]
            if sym_channels:
                self.frequency = sum(ch["frequency_hz"] for ch in sym_channels) / len(sym_channels)
            led = SYMBOLS[chladni_id]["led_effect"]
            ts  = time.strftime("%H:%M:%S")
            print(f"[{ts}] [Trigger] {chladni_id}  note={self._dwell_note_id}")
            self._resonance.enqueue_trigger(
                chladni_id, self._dwell_note_id, led,
                self._left_volume, self._right_volume)

        self._last_note_change = wall_now
        self._last_interaction = now
        self.dwell_progress    = 0.0
        self._dwell_armed      = False   # disarm — must leave ring to fire same note again

    # -----------------------------------------------------------------------
    # Section 5: Qt event handlers
    # -----------------------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:
        self._record_interaction()
        pos              = QPointF(event.position())
        self.mouse_pos       = pos
        self.hover_section   = self.section_at(pos)
        self.image_btn_hover = self.image_btn_rect.contains(pos)
        self.update()

    def mousePressEvent(self, event) -> None:
        self._record_interaction()
        if (event.button() == Qt.LeftButton
                and self.image_btn_rect.contains(event.position())):
            self.image_mode = not self.image_mode
            self.update()

    def keyPressEvent(self, event) -> None:
        if event.isAutoRepeat():
            return super().keyPressEvent(event)
        key = event.key()
        if key == Qt.Key_M:
            self.settings_requested.emit()
        # DIFF 22: Added Key_B handler for hints visibility toggle
        elif key == Qt.Key_B:
            self._hints_visible = not self._hints_visible
            self.update()
        elif key == Qt.Key_H:
            self._toggle_heartbeat()
        elif key == Qt.Key_I:
            self.testing_toggle.emit()
        elif key == Qt.Key_F:
            # Spec 2: F key explicitly enters sharp mode — hand sensor does NOT.
            self.blue_hand_closed = True
            self.sharp_mode_until = time.monotonic() + 86400  # held until key release
            self._record_interaction()
            self.update()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if not event.isAutoRepeat() and event.key() == Qt.Key_F:
            self.blue_hand_closed = False
            self.sharp_mode_until = 0.0
            self.update()
            return
        super().keyReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self.hover_section   = -1
        self.image_btn_hover = False
        self.update()
        super().leaveEvent(event)

    def closeEvent(self, event) -> None:
        """Shut down background ResonanceThread and heartbeat timer cleanly."""
        self._hb_timer.stop()
        self._resonance.stop()
        self._resonance.wait(2000)
        super().closeEvent(event)

    # -----------------------------------------------------------------------
    # Section 5: Paint  (layer order: background → wave → UI → overlays)
    # -----------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy      = w / 2, h / 2
        base_radius = min(w, h)

        # Layer 1: solid background
        painter.fillRect(self.rect(), QColor("#020203")) #BACKGROUND

        # Layer 2: diagonal background wave (deepest visual layer)
        channels = self._channels_for_note(self._display_note_id())
        painter.save()
        # DIFF 18: Changed rotate(31) → rotate(30), length=2000 → length=1200
        painter.rotate(30) #ANGULO DAS ONDAS DE FUNDO
        self._draw_wave(painter, 0, 0, length=1200, channels=channels) #TAMANHO ONDA
        painter.restore()

        # Layer 3: interactive UI
        selector_radius = base_radius * self.selector_radius_scale
        center_radius   = base_radius * self.center_plate_radius_scale  # enlarged
        # DIFF 18: Changed 0.13 → 0.15 for preview_radius
        preview_radius  = max(150, base_radius * 0.15)   # CIRCULO PREVIEW

        img_btn_x = w - 104
        img_btn_y = 16
        preview_x = w - preview_radius - 20
        preview_y = h - preview_radius - 20

        self._draw_selector(painter, cx, cy, selector_radius)
        self._draw_reference_center(painter, cx, cy, center_radius)
        # Dwell ring drawn HERE — after center circle so it's never buried beneath it
        self._draw_dwell_loader(painter, cx, cy, selector_radius)
        self._draw_reference_disc(painter, preview_x, preview_y, preview_radius)
        self._draw_hands(painter)
        self._draw_image_button(painter, img_btn_x, img_btn_y)

        # Layer 4: status overlays
        # DIFF 18: Added standby overlay block
        if self._standby_active:
            self._draw_standby_overlay(painter, cx, cy, center_radius)

        if self._idle_active:
            pulse = 0.55 + 0.45 * abs(math.sin(self.t * 0.6))
            c = QColor(0, 217, 232, int(200 * pulse))
            painter.setPen(c)
            painter.setFont(QFont("Arial", 13, QFont.Bold))
            sym = self._chladni_id_for_note(self._idle_note) or "—"
            painter.drawText(QRectF(16, 16, 400, 24),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             f"● ATTRACT  note {self._idle_note}  ({sym})")

        if self._logo and not self._logo.isNull():
            lh = 100
            lw = int(lh * self._logo.width() / self._logo.height())
            painter.drawPixmap(16, h - lh - 16, lw, lh, self._logo)

        # DIFF 18: Added hints visibility guard
        if self._hints_visible:
            self._draw_hints(painter, w, h)
        self._draw_heartbeat_indicator(painter, w)

    # -----------------------------------------------------------------------
    # Section 5: Heartbeat status indicator (non-blocking)
    # -----------------------------------------------------------------------

    def _draw_heartbeat_indicator(self, painter: QPainter, w: int) -> None:
        if not self._heartbeat_enabled:
            return
        if self._heartbeat_warning:
            dot_color = QColor("#ff0038")
            label     = f"HB FAIL  ({self._hb_consecutive_misses} missed)"
        else:
            pulse     = 0.45 + 0.55 * abs(math.sin(self.t * 1.9))
            dot_color = QColor(0, 255, 37, int(210 * pulse))
            label     = "HB OK"

        dot_x, dot_y = w - 168.0, 8.0
        painter.setBrush(dot_color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(dot_x, dot_y), 4, 4)
        painter.setPen(dot_color)
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.drawText(QRectF(dot_x + 10, dot_y - 7, 150, 15),
                         Qt.AlignLeft | Qt.AlignVCenter, label)

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

        parts, total_w = [], 0
        for key, label in hints:
            kw = fm_key.horizontalAdvance(key)
            lw = fm_lbl.horizontalAdvance("  " + label)
            parts.append((key, label, kw, lw))
            total_w += kw + lw
        total_w += sep_gap * (len(hints) - 1)

        hx = (w - total_w) / 2
        for i, (key, label, kw, lw) in enumerate(parts):
            is_hb = (i == len(hints) - 1)
            kc    = (QColor("#ff0038") if is_hb and self._heartbeat_warning
                     else QColor("#00d9e8"))
            painter.setFont(key_font)
            painter.setPen(kc)
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
        # Left-hand fist (blue_hand_closed) switches the visual circle labels only.
        # It does NOT select/transmit any note — that only happens via completed dwell.
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
    # Section 5: Wave renderer
    # -----------------------------------------------------------------------

    # DIFF 19: Uses QPolygonF + drawPolyline (main branch style), _WAVE_STEP_BG constant
    def _draw_wave(self, painter: QPainter, x0: float, y0: float,
                   length: int = 485, channels: list | None = None) -> None:
        wave_count = 4
        spacing    = 44
        speed      = self.t * 4.0
        base_amp   = 20 + 15 * self.wave_amplitude # ONDA AMPLITUDE
        colors     = [QColor("#ff3a9e"), QColor("#cde70b"),
                      QColor("#00eaff"), QColor("#ff8500")]

        if channels and len(channels) >= wave_count:
            # Normalize hardware amplitudes to [0,1] for display — raw values
            # from master_symbols.json are tiny floats (0.01–0.21).
            raw_amps = [ch["amplitude"] for ch in channels[:wave_count]]
            max_amp  = max(raw_amps) if any(a > 0 for a in raw_amps) else 1.0
            amps     = [a / max_amp for a in raw_amps]
            wknums   = [0.025 + 0.060 * (ch["frequency_hz"] / 500.0)
                        for ch in channels[:wave_count]]
            phases   = [math.radians(ch["phase_deg"]) for ch in channels[:wave_count]]
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
            poly = QPolygonF([QPointF(x0 + x, baseline + math.sin(x * wk + speed + ph) * amp)
                              for x in range(0, length, _WAVE_STEP_BG)])

            glow = QColor(col); glow.setAlpha(42)
            painter.setPen(QPen(glow, 10, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPolyline(poly)

            lc = QColor(col); lc.setAlpha(210)
            painter.setPen(QPen(lc, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPolyline(poly)

            dot_offsets = (0.0, length / 3.0, 2.0 * length / 3.0) # PULSE DOTS FREQUENCY
            painter.setBrush(col)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            for offset in dot_offsets:
                mx = (self.t * 68 + wi * 36 + offset) % length
                my = baseline + math.sin(mx * wk + speed + ph) * amp
                painter.drawEllipse(QPointF(x0 + mx, my), 6, 6)

            painter.setPen(QColor(255, 255, 255, 170))
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.drawText(QRectF(x0 - 38, baseline - 10, 32, 20),
                             Qt.AlignRight, f"{wi * 90}")

    # -----------------------------------------------------------------------
    # Section 5: Wave overlay clipped to a circle
    # -----------------------------------------------------------------------

    # DIFF 20: Uses _WAVE_STEP_CIRCLE constant (was hardcoded step=2)
    def _draw_wave_in_circle(self, painter: QPainter,
                             cx: float, cy: float,
                             inner_r: float, wave_lanes: int = 4) -> None:
        channels = self._channels_for_note(self._display_note_id())
        clip     = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), inner_r, inner_r)

        wave_len = int(inner_r * 2.2)
        spacing  = max(20, int(inner_r * 0.28))
        speed    = self.t * 4.0
        base_amp = max(6, int(inner_r * 0.10)) + int(inner_r * 0.06 * self.wave_amplitude)
        colors   = [QColor("#ff3a9e"), QColor("#cde70b"),
                    QColor("#00eaff"), QColor("#ff8500")][:wave_lanes]

        if channels and len(channels) >= wave_lanes:
            raw_amps = [ch["amplitude"] for ch in channels[:wave_lanes]]
            max_amp  = max(raw_amps) or 1.0
            amps     = [a / max_amp for a in raw_amps]
            wknums   = [0.030 + 0.055 * (ch["frequency_hz"] / 500.0)
                        for ch in channels[:wave_lanes]]
            phases   = [math.radians(ch["phase_deg"]) for ch in channels[:wave_lanes]]
        else:
            amps   = [1.0] * wave_lanes
            wknums = [0.055] * wave_lanes
            phases = [i * math.pi / 2 for i in range(wave_lanes)]

        painter.save()
        painter.setClipPath(clip)

        for wi in range(wave_lanes):
            baseline = cy + (wi - (wave_lanes - 1) / 2.0) * spacing
            amp      = base_amp * amps[wi]
            ph       = phases[wi]
            wk       = wknums[wi]
            col      = colors[wi]
            x_start  = cx - inner_r * 1.05

            pts = [QPointF(x_start + x,
                           baseline + math.sin(x * wk + speed + ph) * amp)
                   for x in range(0, wave_len, _WAVE_STEP_CIRCLE)]

            glow = QColor(col); glow.setAlpha(28)
            painter.setPen(QPen(glow, 7, Qt.SolidLine, Qt.RoundCap))
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])

            lc = QColor(col); lc.setAlpha(90)
            painter.setPen(QPen(lc, 2, Qt.SolidLine, Qt.RoundCap))
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])

        painter.restore()

    # -----------------------------------------------------------------------
    # Section 5: Selector
    # -----------------------------------------------------------------------

    def _draw_selector(self, painter: QPainter,
                       cx: float, cy: float, radius: float) -> None:
        glow_a  = int(45 + 205 * self.wave_amplitude)
        colors  = self.image_colors if self.using_image_mode() else self.section_colors
        gc      = QColor(colors[self.selected_section]); gc.setAlpha(glow_a)
        glow    = QRadialGradient(QPointF(cx, cy), radius + 70)
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

        # _draw_dwell_loader is called in paintEvent AFTER _draw_reference_center
        # so it renders on top of the center circle, not buried beneath it.

    def _draw_dwell_loader(self, painter: QPainter,
                           cx: float, cy: float, radius: float) -> None:
        """
        Dwell progress ring drawn in the coloured pie zone (radius * 0.82).
        Must be called AFTER _draw_reference_center in paintEvent so it is
        not covered by the center circle overlay.
        """
        if self.dwell_section < 0 or self.dwell_progress <= 0:
            return
        a    = math.radians(-(self.dwell_section * 60 + 30))
        tx   = cx + math.cos(a) * radius * 0.82   # was 0.66 — now in visible ring zone
        ty   = cy + math.sin(a) * radius * 0.82
        rect = QRectF(tx - 20, ty - 20, 40, 40)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 60), 5, Qt.SolidLine, Qt.RoundCap))
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor("#ffffff"), 5, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect, 90 * 16, int(-360 * 16 * self.dwell_progress))

    # -----------------------------------------------------------------------
    # Section 5: Center image — Spec 1 (live footage default)
    # -----------------------------------------------------------------------

    def _draw_reference_center(self, painter: QPainter,
                                cx: float, cy: float, radius: float) -> None:
        """Camera feed only. Dark placeholder when no feed active. No wave, no Chladni."""
        inner_r = radius * 0.86
        target  = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
        clip    = QPainterPath()
        clip.addEllipse(target)

        painter.save()
        painter.setClipPath(clip)
        if self.center_live_image is not None and not self.center_live_image.isNull():
            source = self.cover_source_rect(self.center_live_image.width(),
                                            self.center_live_image.height())
            painter.drawImage(target, self.center_live_image, source)
        else:
            painter.fillRect(target, QColor("#0a0b0e"))
        painter.restore()

    # -----------------------------------------------------------------------
    # Section 5: Preview disc — Spec 1 (symbol PNG displayed here)
    # -----------------------------------------------------------------------

    def _draw_reference_disc(self, painter: QPainter,
                              cx: float, cy: float, radius: float) -> None:
        """
        Spec 1: display symbol PNG from master_symbols.json in this disc.
        Falls back to the Chladni contour renderer when image is unavailable.
        """
        sym_name = self._chladni_id_for_note(self._display_note_id())
        sym_img  = self._symbol_images.get(sym_name)
        inner_r  = radius * 0.86

        if sym_img and not sym_img.isNull():
            target = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
            source = self.cover_source_rect(sym_img.width(), sym_img.height())
            clip   = QPainterPath()
            clip.addEllipse(target)
            painter.setBrush(QColor("#bf8a47"))
            painter.setPen(QPen(QColor("#f3cf8d"), max(2, int(radius * 0.03))))
            painter.drawEllipse(QPointF(cx, cy), radius, radius)
            painter.save()
            painter.setClipPath(clip)
            painter.drawImage(target, sym_img, source)
            painter.restore()
        else:
            self._draw_chladni_plate(painter, cx, cy, radius, 4)

    def _draw_chladni_plate(self, painter: QPainter,
                             cx: float, cy: float,
                             radius: float, detail: int) -> None:
        cache_key = (self.selected_section, int(radius))
        if cache_key not in self._chladni_cache:
            size = int(radius * 2) + 8
            pix = QPixmap(size, size)
            pix.fill(Qt.transparent)
            lcx = size / 2.0
            lcy = size / 2.0
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            self._paint_chladni(p, lcx, lcy, radius, detail)
            p.end()
            self._chladni_cache[cache_key] = pix

        pix = self._chladni_cache[cache_key]
        painter.drawPixmap(int(cx - pix.width() / 2), int(cy - pix.height() / 2), pix)

    def _paint_chladni(self, painter: QPainter,
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

        bx = self.image_btn_rect.center().x()
        by = self.image_btn_rect.center().y()
        painter.drawRoundedRect(QRectF(bx - 18, by - 2, 36, 24), 8, 8)
        for i in range(4):
            painter.drawRoundedRect(
                QRectF(bx - 22 + i * 11, self.image_btn_rect.top() + 16, 10, 24), 5, 5)
        painter.drawLine(QPointF(bx - 8, by + 20), QPointF(bx - 18, by + 10))
        painter.drawLine(QPointF(bx + 8, by + 20), QPointF(bx + 18, by + 10))

    # -----------------------------------------------------------------------
    # Section 5: Standby attract overlay
    # -----------------------------------------------------------------------

    # DIFF 21: Added _ghost_landmarks and _draw_standby_overlay (were missing)
    def _ghost_landmarks(self, cx: float, cy: float,
                         scale: float, flip: bool) -> list:
        f = -1.0 if flip else 1.0
        return [QPointF(cx + dx * scale * f, cy + dy * scale)
                for dx, dy in _GHOST_HAND_PTS]

    def _draw_standby_overlay(self, painter: QPainter,
                               cx: float, cy: float,
                               center_radius: float) -> None:
        pulse  = 0.60 + 0.40 * abs(math.sin(self.t * 1.2))
        w      = self.width()
        scale  = 300
        alpha  = int(210 * pulse)

        left_cx  = w * 0.14
        right_cx = w * 0.86

        # Ghost hands flanking the selector ring
        painter.setOpacity(0.38 * pulse)
        left_pts  = self._ghost_landmarks(left_cx,  cy, scale, flip=True)
        right_pts = self._ghost_landmarks(right_cx, cy, scale, flip=False)
        self._draw_real_hand(painter, left_pts,  QColor("#00eaff"), False)
        self._draw_real_hand(painter, right_pts, QColor("#ff3030"), False)
        painter.setOpacity(1.0)

        # Labels below left hand — CLOSE / OPEN
        lbl_w  = 180
        lbl_x  = left_cx - lbl_w / 2
        lbl_y  = cy + 24
        lbl_fn = QFont("Arial", 13, QFont.Bold)
        painter.setFont(lbl_fn)

        painter.setPen(QColor(0, 234, 255, alpha))
        painter.drawText(QRectF(lbl_x, lbl_y,      lbl_w, 26), Qt.AlignCenter, "✊  CLOSE")
        painter.setPen(QColor(180, 240, 255, alpha))
        painter.drawText(QRectF(lbl_x, lbl_y + 28, lbl_w, 26), Qt.AlignCenter, "✋  OPEN")

        sub_fn = QFont("Arial", 10)
        sub_fn.setItalic(True)
        painter.setFont(sub_fn)
        painter.setPen(QColor(100, 180, 200, int(alpha * 0.7)))
        painter.drawText(QRectF(lbl_x, lbl_y + 56, lbl_w, 20),
                         Qt.AlignCenter, "switch note set")

        # Labels below right hand — MOVE INTO A NOTE + color dots
        rbl_w = 220
        rbl_x = right_cx - rbl_w / 2
        rbl_y = cy + 24
        painter.setFont(QFont("Arial", 13, QFont.Bold))
        painter.setPen(QColor(255, 80, 80, alpha))
        painter.drawText(QRectF(rbl_x, rbl_y, rbl_w, 26),
                         Qt.AlignCenter, "MOVE INTO A NOTE")

        # Colour dots row (matching section_colors)
        dot_r   = 7
        n_dots  = len(self.section_colors)
        spacing = 20
        row_w   = (n_dots - 1) * spacing
        dot_y   = rbl_y + 36
        painter.setPen(Qt.NoPen)
        for i, col in enumerate(self.section_colors):
            dot_x = right_cx - row_w / 2 + i * spacing
            c = QColor(col)
            c.setAlpha(alpha)
            painter.setBrush(c)
            painter.drawEllipse(QPointF(dot_x, dot_y), dot_r, dot_r)

        # Invitation text below center circle
        text_y = cy + center_radius + 75
        painter.setPen(QColor(0, 217, 232, alpha))
        painter.setFont(QFont("Arial", 15, QFont.Bold))
        painter.drawText(
            QRectF(cx - 340, text_y, 680, 100),
            Qt.AlignCenter | Qt.AlignVCenter,
            "COME TRY!  SELECT A MUSIC NOTE",
        )


# ===========================================================================
# Standalone entry point (dev/test — normally launched via main.py)
# ===========================================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w   = MainWindow()
    w.show()
    sys.exit(app.exec())