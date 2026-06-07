# Human Interface (Python Client): Full Architecture & Specification

**Version:** 1.0 (Target Architecture Blueprint)

**Component:** `human-interface` (Python / PySide6 / MediaPipe)

**Role:** Smart Client / State Manager / Vision Engine

## 1. System Overview

The Human-Interface Client is a Python-based desktop application responsible for the "Smart" logic of the SWAID Plate Resonance system. While the C++ Server blindly executes hardware commands, the Python Client holds the state, enforces interaction rules, parses computer vision, and renders the visual UI.

**Core Responsibilities:**

1. **Computer Vision:** Running Google MediaPipe to track user hand landmarks via a webcam feed.
2. **State & Timing Management:** Acting as the "Single Source of Truth" by parsing `master_symbols.json` to calculate interaction lockouts (Attack-Sustain-Release timing envelopes) to protect the server from command spam.
3. **Asynchronous Networking:** Maintaining a 10Hz ZeroMQ IPC heartbeat without freezing the PySide6 GUI thread.
4. **Diagnostic Dashboard:** Rendering real-time hardware warnings based on the C++ Server's telemetry.

---

## 2. Client Start-Up Procedure

When `main.py` is executed (or the PyInstaller compiled binary is launched), the application must execute a strict, linear initialization sequence before rendering the main window.

1. **Configuration Loading (`master_symbols.json`):**
* The client parses `master_symbols.json` on boot.
* It constructs an O(1) in-memory lookup dictionary. **Crucial:** It must create mappings that allow the UI hitboxes/gestures to instantly retrieve the `music_note` ID, as well as the timing parameters (`fade_in_ms`, `symbol_duration_ms`, `fade_out_ms`).


2. **Network Layer Initialization (`resonance_client.py`):**
* Instantiates the `ResonanceClient` class.
* Spawns the isolated ZeroMQ Background Worker Thread (See Section 3) to begin polling the `ipc:///tmp/swaid.sock` socket immediately.


3. **Vision Engine Initialization (`hand_tracking.py`):**
* Boots the OpenCV `VideoCapture` pipeline.
* Loads the MediaPipe `hand_landmarker.task` model into memory.


4. **GUI Instantiation (PySide6):**
* Boots the Qt Event Loop.
* Instantiates the Main Window, mapping the internal state variables to the UI canvases (Sinusoidal wave renderers and Symbol Image display).
* Starts the internal `QTimer` UI sync loops (10Hz).



---

## 3. Network Layer Architecture (ZeroMQ)

Because ZMQ `REQ/REP` sockets are strictly synchronous and blocking, executing a `socket.send()` directly from the PySide6 UI thread will freeze the application if the C++ server is offline.

To prevent this, `resonance_client.py` must be implemented using a **Thread-Safe Command Queue Pattern**.

### 3.1. The Background ZMQ Thread

* **The Loop:** An isolated background thread runs an infinite `while` loop at roughly 10Hz to 20Hz (every 50ms - 100ms).
* **Command Ingestion:** It checks a thread-safe `queue.Queue()`.
* If a command (e.g., `trigger`, `shuffle`) is in the queue, it pops it and sends it.
* If the queue is empty, it generates a default `{"message_type": "ping"}` payload and sends it.


* **Receive Timeout (`RCVTIMEO`):** The socket must be configured with a strict 200ms receive timeout. If the C++ Server crashes or is offline, `recv_json()` throws an exception (`zmq.error.Again`). The client catches this, closes/rebuilds the socket to prevent deadlock, and flags the connection as offline.
* **State Caching:** When a valid JSON reply is received from the server, the thread safely overwrites two class-level properties: `self.cached_diagnostics` and `self.cached_active_state`.

### 3.2. Public API Methods

The `ResonanceClient` class exposes simple, non-blocking methods for the UI to call. These methods solely push dictionaries into the Queue.

* `client.trigger(music_note: int)`
* `client.shuffle()`
* `client.set_channel_state(transducer_mute: bool, music_mute: bool)`

---

## 4. Command Generation & UI Blocking (ASR Logic)

The "Smart Client" is responsible for protecting the C++ Server from command spam. Because the server is generating precise audio DSP envelopes (Attack-Sustain-Release), the UI must lock its own inputs to give the hardware time to finish the acoustic sequence.

### 4.1. The `trigger` Execution Sequence

1. **Detection:** The Computer Vision pipeline detects a hand hovering over UI Button #2.
2. **Concurrency Check:** The UI checks if `self.is_input_locked == true`. If true, the gesture is ignored.
3. **Lookup & Calculation:** * The UI looks up the symbol data for `music_note: 2`.
* Calculates `total_lockout_ms = fade_in_ms + symbol_duration_ms + fade_out_ms`.


4. **Dispatch:** Calls `client.trigger(music_note=2)`.
5. **The UI Lock:** * Sets `self.is_input_locked = true`. (Hitboxes turn grey/disabled).
* Spawns a PySide6 `QTimer::singleShot(total_lockout_ms, unlock_function)`.
* Once the exact millisecond duration passes, the timer fires, setting `self.is_input_locked = false`, allowing the user to select a new symbol seamlessly as the physical audio finishes fading out.



### 4.2. The `shuffle` Execution Sequence

1. **Dispatch:** User presses the "Clear Plate" button. UI calls `client.shuffle()`.
2. **Calculation:** The UI loops through all `SHUFFLE_X` symbols in `master_symbols.json`, summing their `(fade_in + duration + fade_out)` values to find the exact duration of the entire sequence.
3. **The UI Lock:** Applies the `QTimer::singleShot` lock for the calculated sequence length, displaying a "Shuffling Sand..." overlay to the user.

---

## 5. UI Animation & State Synchronization

The UI must visually reflect the active physical state of the plate, rendering sinusoidal wave animations and displaying the target image pattern.

* **The Piggyback Protocol:** The Python client does not need to guess when to update its visuals. It relies on the 10Hz `ping` heartbeat.
* **The 10Hz Render Loop:** The PySide6 UI runs a `QTimer` every 100ms that executes `update_visuals()`.
* **Execution Logic:**
1. The function reads `client.cached_active_state["current_chladni_id"]`.
2. It compares this to an internal `self.currently_rendered_id`.
3. If they differ (indicating the user triggered a new note, or the PureData sequencer autonomously changed the note), the UI updates its state.
4. It fetches `hardware_config.channels` from the local JSON map, using the amplitude/frequency data to mathematically animate the sine waves on the GUI canvas.
5. It loads `ui_metadata.image_path` to update the central pattern image.



---

## 6. The Diagnostics & Self-Healing Dashboard

Because the C++ Server operates autonomously and attempts to self-heal when cables are unplugged, the UI must visually warn the user of hardware faults without crashing.

* **The Dashboard Overlay:** A permanent, absolute-positioned UI widget (e.g., a banner at the top of the screen) that is hidden by default.
* **The 10Hz Health Loop:** Inside the same UI `QTimer` loop, the application evaluates `client.cached_diagnostics`.

**Display Logic:**

1. **Critical Failure:** If the ZeroMQ socket triggers a timeout (Server crashed or `swaid_launcher.sh` failed to boot it), show a red banner: `"CRITICAL: C++ Core Offline. Please restart the system."`
2. **Audio Disconnect:** If `usb_audio == 0`, show an orange banner: `"WARNING: USB Soundcard disconnected. System attempting auto-recovery..."`
3. **LED Disconnect:** If `pico_serial == 0`, show an orange banner: `"WARNING: LED Controller disconnected. System attempting auto-recovery..."`
4. **All Clear:** If all diagnostics return `1` and the ZMQ socket is connected, the banner is completely hidden (`widget.hide()`).

*Architectural Benefit:* If a user trips over the USB Soundcard cable, the banner appears instantly. When they plug it back in, the C++ Server's Watchdog catches it, rebuilds PortAudio, updates the ZMQ reply to `usb_audio: 1`, and the Python UI instantly hides the banner. Total self-healing.

---

## Appendix A: `master_symbols.json` Schema Requirement

To maintain the "Single Source of Truth", the Python UI must parse the exact same JSON configuration file as the C++ Server. The UI utilizes this file to map hitboxes to `music_note`s, calculate QTimer lockouts using the timing envelopes, and draw the visual animations.

```json
{
    "music_note": 2,
    "display_name": "CHLADNI_191",
    "LED_effect": 1,
    "symbol_duration_ms": 500,
    "fade_in_ms": 100,
    "fade_out_ms": 100,
    "hardware_config": {
        "channels": [
            { "output": 1, "frequency_hz": 190.5, "amplitude": 0.016, "phase_deg": 0 },
            { "output": 2, "frequency_hz": 190.5, "amplitude": 0.016, "phase_deg": 0 },
            { "output": 3, "frequency_hz": 190.5, "amplitude": 0.016, "phase_deg": 0 },
            { "output": 4, "frequency_hz": 190.5, "amplitude": 0.016, "phase_deg": 0 }
        ]
    },
    "ui_metadata": {
        "image_path": "./dictionary/CHLADNI_191.png"
    }
}

```
