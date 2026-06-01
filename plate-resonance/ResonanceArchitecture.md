# SWAID Plate Resonance: Comprehensive Software Architecture Specification

**Version:** 1.0
**Author:** Miguel Amorim
**Date:** June 2026

## 1. Executive Summary & Design Principles

The SWAID Plate Resonance service is a high-performance, real-time audio and hardware orchestration hub. It follows the **"Smart Client, Synchronized Core"** paradigm, where all UI logic lives in Python, while the C++ Core handles the real-time constraints of audio DSP and hardware I/O.

### **Core Principles:**
1.  **Dumb Server Strategy:** The Core strictly executes mappings defined in JSON; it holds no application-level "selection" state.
2.  **Concurrency Safety:** Blocking I/O (Serial/Network) is strictly isolated from the real-time audio thread to prevent stuttering.
3.  **Frame-Accurate Sync:** PureData is embedded (`libpd`) to eliminate network jitter between music and physical vibration.
4.  **Self-Healing Resilience:** The system autonomously recovers from USB disconnects (Soundcard/Pico) via asynchronous polling loops.
5.  **Single Source of Truth:** The Core exposes its internal generative state via "State Piggybacking" in ZMQ replies.

---

## 2. Technical Stack & Component Breakdown

The system is a C++17 application structured around specialized **Software Abstraction Layers (SALs)**:

| Component | Namespace / Files | Technology | Responsibility |
| :--- | :--- | :--- | :--- |
| **Watchdog** | `resonance_core/main.cpp` | C++, PortAudio | Manages the PortAudio lifecycle, device discovery, and autonomous recovery. |
| **Command Server** | `resonance_server.cpp` | ZeroMQ (cppzmq) | REQ/REP server listening on `ipc:///tmp/swaid.sock`. |
| **Musical Brain** | `libpd` (Embedded) | C, PureData | Generative sequencer execution; frame-accurate audio generation. |
| **Audio Driver** | `audio_driver.cpp` | PortAudio, C++ | Multi-stream I/O, Sine-wave synthesis, Linear Fading (100ms). |
| **LED Driver** | `embedded_sal.cpp` | POSIX Serial | Communication with Raspberry Pi Pico at 9600 baud. |
| **Sync Bridge** | `lock_free_queue.hpp` | C++, Atomics | SPSC (Single Producer Single Consumer) lock-free communication. |

---

## 3. Tiered Threading Model (Real-Time Safety)

To ensure audio stability, the Core isolates tasks into three priority-tiered threads:

### **Thread 1: The ZMQ IPC Listener (Low Priority)**
- **Behavior:** Blocks on `rep_socket.recv()`.
- **Role:** Ingests JSON commands, updates global atomic states, seeds the `libpd` root note.
- **Safety:** Does not touch hardware directly; only modifies thread-safe state.

### **Thread 2: The PortAudio Callback (Real-Time / "Sacred")**
- **Behavior:** High-priority interrupt fired by the OS audio driver (~187 times/sec).
- **Logic:**
    1. Executes `libpd_process_float()` for music audio.
    2. Generates 4 logical sine waves for transducers.
    3. **Mixer:** Routes music to `music_channels` and sine waves to `transducer_channels`.
- **Feedback Loop:** Catching PD notes via `pd_float_hook`. Updates transducer atomics and pushes LED IDs to the queue.
- **CRITICAL:** Performs zero standard I/O (no `write`, no `printf`) or memory allocation.

### **Thread 3: The Hardware Worker (Medium Priority)**
- **Behavior:** Continuous polling loop (`sleep(50ms)`).
- **Role:** Pops from the `LockFreeQueue` and executes the blocking Serial `write()` to the Pico.
- **Resilience:** Implements a 2-second reconnect loop if Serial I/O fails.

---

## 4. Communication Protocols & Payloads

### **4.1. UI $\leftrightarrow$ Core (ZeroMQ REQ/REP)**
The UI initiates all commands. Every request receives a JSON reply including **Diagnostics** and **Active State**.

#### **Command: `trigger`**
- **Payload:** `{"chladni_id": "CH_191", "music_note": 60, "led_effect_id": 1, "vol_l": 80, "vol_r": 80}`
- **Execution:** 
    1. `music_note` seeds the `libpd` sequencer.
    2. `chladni_id` parameters are loaded for transducers.
    3. `vol_l/r` scale the *Music* channels (1 & 2) only.

#### **Command: `channel_state`**
- **Payload:** `{"command": { "transducer_mute": bool, "music_mute": bool }}`
- **Logic:** `music_mute: true` sends a `-1` stop signal to the PureData sequencer.

#### **Command: `ping` (Heartbeat @ 20Hz)**
- **Payload:** `{"message_type": "ping"}`
- **Response (Piggybacking):**
  ```json
  {
    "status": "pong",
    "diagnostics": { "pico_serial": 1, "usb_audio": 1, "hdmi_audio": 1 },
    "active_state": { "current_note": 62, "current_chladni_id": "CHLADNI_294" }
  }
  ```

### **4.2. Core $\leftrightarrow$ PureData (Internal `libpd`)**
- **`from_core` (Inbound):** Seed for the sequencer root note.
- **`to_core` (Outbound):** PD sequencer fires the current active note for 1:1 hardware sync.
- **Spam Protection:** Core implements a state filter; logic only executes if the note has actually changed.

---

## 5. Self-Healing & Watchdog Protocol

### **5.1. Pico Serial Recovery**
If the RPi Pico is unplugged, Thread 3 detects the failure, closes the port, and infinitely polls `connect()` every 2 seconds without stopping the audio service.

### **5.2. Audio Stream Recovery**
The `main.cpp` Watchdog polls `Pa_IsStreamActive()` at 20Hz. On failure (USB Soundcard yanked):
1.  Calls `Pa_Terminate()` to clear OS locks.
2.  Enters a discovery loop, retrying substring matching (e.g., "USB Audio") every 5 seconds.
3.  Re-opens and starts streams automatically once hardware is detected.

---

## 6. Execution Model & Routing

### **Dual-Stream Logic (`system_config.json`)**
- **Combined Mode:** Music and Transducers are mixed in a single 8-channel PortAudio stream (USB).
- **Dual Mode:** Music routes to HDMI; Transducers route to USB Soundcard via isolated streams.

### **DSP Logic**
- **100ms Fixed Fade:** All transducer amplitude changes are stepped over 100ms to prevent mechanical clicking.
- **Volume Decoupling:** `vol_l/r` strictly control the `libpd` buffer. Transducer amplitudes are strictly derived from physics definitions in `master_symbols.json`.

---

## 7. Configuration Layers

1.  **`master_symbols.json` (Physics):** Definitions of Chladni patterns (Logical Transducers 1-4).
2.  **`system_config.json` (Hardware):** Mapping of logical components to physical soundcard channels and device discovery strings.

---

## 8. Detailed Data Pipeline: The Life of a Trigger

1.  **UI:** Sends `trigger` for `CH_191` via ZMQ.
2.  **Core T1:** Receives JSON -> Seeds root note to `libpd`.
3.  **libpd (T2):** Sequencer plays a note in the scale, say `52`.
4.  **Sync Hook:** `libpd` calls `pd_float_hook` -> Core updates oscillator frequencies to `CH_294` (mapped to `52`) -> Core pushes LED ID to Queue.
5.  **Hardware Worker (T3):** Dequeues ID -> Sends `FX:<id>` to Pico.
6.  **Output:** Transducers ramp to new frequency + LEDs change, perfectly synced to the music note.
