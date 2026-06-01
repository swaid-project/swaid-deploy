# SWAID Plate Resonance: Comprehensive Software Architecture Specification

**Version:** 6.1
**Author:** Miguel Amorim
**Date:** June 2026

## 1. Executive Summary & Design Principles

The SWAID Plate Resonance service is a high-performance, real-time audio and hardware orchestration hub. It follows the **"Smart Client, Synchronized Core"** paradigm, where all UI and scientific selection logic lives in Python, while the C++ Core handles the "Sacred" real-time constraints of audio DSP and hardware I/O.

### **Core Principles:**
1.  **Dumb Server Strategy:** The Core does not make decisions; it strictly executes mappings defined in JSON.
2.  **Concurrency Safety:** Blocking I/O (Serial/Network) is strictly isolated from the real-time audio thread.
3.  **Frame-Accurate Sync:** PureData is embedded (`libpd`) to eliminate network jitter between music and physical vibration.
4.  **Hardware Decoupling:** Logical transducer indices are mapped to physical soundcard channels via external configuration.

---

## 2. Technical Stack & Component Breakdown

The system is a C++17 application structured around specialized **Software Abstraction Layers (SALs)**:

| Component | File Path / Namespace | Technology | Responsibility |
| :--- | :--- | :--- | :--- |
| **Orchestrator** | `resonance_core/src/main.cpp` | C++, STL | Boots the system, manages autonomous discovery, and links threads. |
| **Command Server** | `resonance_core/src/resonance_server.cpp` | ZeroMQ (cppzmq) | REQ/REP server listening on `ipc:///tmp/swaid.sock`. |
| **Musical Brain** | `libpd` (Embedded) | C, PureData | Generative sequencer execution; frame-accurate audio generation. |
| **Audio Driver** | `soundcard/src/audio_driver.cpp` | PortAudio, C++ | Multi-stream I/O, Sine-wave synthesis, Linear Fading (100ms). |
| **LED Driver** | `led_driver/src/embedded_sal.cpp` | POSIX Serial | Communication with Raspberry Pi Pico at 9600 baud. |
| **Sync Bridge** | `resonance_core/include/lock_free_queue.hpp` | C++, Atomics | SPSC (Single Producer Single Consumer) lock-free communication. |

---

## 3. Tiered Threading Model (Real-Time Safety)

The system operates three distinct threads with prioritized responsibilities:

### **Thread 1: The ZMQ IPC Listener (Low Priority)**
*   **Context:** `jsonListenerThread`
*   **Behavior:** Blocks on `rep_socket.recv()`.
*   **Role:** 
    1. Parses incoming JSON.
    2. Updates global `std::atomic` states (e.g., `musicMute`, `masterMute`).
    3. Seeds the `libpd` root note via `libpd_float("from_core", ...)`.
    4. Responds with `{"status": "ok"}` to ACK the Python UI.

### **Thread 2: The PortAudio Callback (Real-Time / "Sacred")**
*   **Context:** `audioCallback`, `musicCallback`, or `transducerCallback`.
*   **Behavior:** High-priority interrupt fired by the OS audio driver (~187 times/sec at 256 buffer size).
*   **Logic:**
    1. **Music Engine:** Executes `libpd_process_float()` to compute the next block of music.
    2. **Sine Engine:** Computes 4 logical sine waves based on logical transducer state.
    3. **Mixer:** Routes music to `systemConfig.routing.music_channels` and sine waves to `systemConfig.routing.transducer_channels`.
    4. **Safety:** Strict "No I/O" policy. No `printf`, no `write()`, no `malloc`.

### **Thread 3: The Hardware Worker (Medium Priority)**
*   **Context:** `hardwareWorkerThread`
*   **Behavior:** Continuous polling loop (`std::this_thread::sleep_for(10ms)`).
*   **Role:**
    1. Pops `led_effect_id` from the `LockFreeQueue`.
    2. Executes `ledDriver.sendEffect(id)`, which performs the blocking Serial `write()`.
*   **Purpose:** Ensures Thread 2 never stalls if the USB-Serial buffer is full or the Pico is slow to respond.

---

## 4. Full Communication Protocol Specification

### **4.1. UI $\leftrightarrow$ Core (JSON over ZMQ)**

#### **Command: `trigger`**
*   **Payload:**
    ```json
    {
      "message_type": "trigger",
      "chladni_id": "CHLADNI_422",
      "music_note": 60,
      "led_effect_id": 2,
      "vol_l": 100,
      "vol_r": 100
    }
    ```
*   **Logic:** Seeds `libpd` with `60`. The Core looks up `CHLADNI_422` and prepares the 100ms fade for transducers. `vol_l/r` are stored in `musicVolL/R`.

#### **Command: `channel_state`**
*   **Payload:**
    ```json
    {
      "message_type": "channel_state",
      "command": { "transducer_mute": bool, "music_mute": bool }
    }
    ```
*   **Logic:** `music_mute: true` sends a `-1` stop signal to `libpd`. `transducer_mute: true` forces all generator amplitudes to `0.0`.

#### **Command: `ping`**
*   **Payload:** `{"message_type": "ping"}`
*   **Logic:** Resets the 3s watchdog timer. Returns `{"status": "pong"}`.

### **4.2. Core $\leftrightarrow$ PureData (libpd Hooks)**
*   **`from_core` (Inbound):** Seed for the sequencer root note.
*   **`to_core` (Outbound):** PD sequencer fires the current active note. 
    *   *Trigger Mechanism:* Core uses `pd_float_hook` to catch this.
    *   *Spam Protection:* Implements a `current_playing_note` state filter; logic only executes if the note is different from the previous one.

### **4.3. Core $\rightarrow$ RPi Pico (Serial)**
*   **Protocol:** 9600 8N1 ASCII.
*   **Format:** `"FX:<int>\n"`.
*   **Response:** Pico sends `"ok:FX:<int>"` (Logged by Thread 3, not acted upon).

---

## 5. Configuration Layers

### **`master_symbols.json` (Physics Layer)**
*   **Logical Mapping:** Uses `logical_transducer` indices (1-4).
*   **Parameters:** `frequency_hz` (float), `amplitude` (float), `phase_deg` (float).

### **`system_config.json` (Hardware Layer)**
*   **Discovery:** `transducer_device_name` and `music_device_name` substrings.
*   **Sample Rate:** Global `sample_rate` (default 48000).
*   **Routing:** Defines which logical transducers map to which physical PortAudio channels.

---

## 6. Detailed Data Pipeline: The Life of a Trigger

1.  **Ingestion:** UI sends `trigger` for `CHLADNI_191` with `note: 48`.
2.  **Dispatch:** ZMQ thread receives JSON. Sends root note `48` to `libpd`.
3.  **Generative Loop:** Inside the next PortAudio callback (Thread 2), `libpd` sequencer computes a note in the scale of `48`, say `52`.
4.  **Synchronization Hook:**
    *   `libpd` calls `pd_float_hook("to_core", 52)`.
    *   Core checks if `52 != current_playing_note` (Spam Filter).
    *   Core looks up `52` in `musicNoteMap` -> finds `CHLADNI_294`.
    *   Core updates `generators[idx].freq` atomics instantly.
    *   Core pushes `LED ID` (from `CHLADNI_294`) to `ledQueue`.
5.  **Vibration:** The physical transducers smoothly ramp to `CHLADNI_294` frequencies over 100ms.
6.  **Visuals:** Thread 3 pops from `ledQueue` and writes `FX:<id>` to the Pico.

---

## 7. Production Reliability & Fallbacks

*   **Autonomous Discovery Boot:** On startup, `main.cpp` enters a non-crashing loop. It scans for the "USB Audio" and "HDMI" device names every 5 seconds. The server remains in a "Ready to initialize" state until hardware is detected.
*   **Watchdog Failsafe:** If no ZMQ `ping` is received for 3.0 seconds, the Core assumes the UI has crashed and triggers `masterMute` to protect the transducers from over-vibration.
*   **DSP Soft-Start:** Amplitudes are always initialized at `0.0`. Every update uses the 100ms linear interpolator to prevent mechanical snapping.
*   **Dual-Stream Isolation:** If Music and Transducers are on separate devices, they use isolated PortAudio streams. A failure in the HDMI driver will not stop the USB Transducer vibrations.
