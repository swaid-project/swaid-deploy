# SWAID Plate Resonance: Software Architecture Specification

**Version:** 2.1 (Synchronized Core & Protocol Specification)
**Last Updated:** May 2026

## 1. Architectural Philosophy
The system follows a **"Smart Client, Synchronized Core"** paradigm. 
- **Python UI (Smart Client):** Manages the high-level application state, user gestures (MediaPipe), and the primary symbol database (`master_symbols.json`).
- **C++ Core (Synchronized Hub):** Acts as a low-latency, real-time orchestrator. It manages the soundcard, executes the embedded musical brain (PureData via `libpd`), and synchronizes mechanical vibrations (Transducers) with visual feedback (LEDs).

---

## 2. Communication Protocols & Payloads

### **2.1. Python UI $\leftrightarrow$ C++ Core (ZeroMQ REQ/REP)**
The UI initiates all commands. Every request receives a `{"status": "ok"}` or `{"status": "pong"}` response.

#### **A. Command: `trigger`**
Sent when a user selects a Chladni symbol.
- **Payload:**
  ```json
  {
      "message_type": "trigger",
      "chladni_id": "CHLADNI_191",
      "music_note": 60,
      "led_effect_id": 1,
      "vol_l": 80,
      "vol_r": 80
  }
  ```
- **Execution Path:** 
    1. `music_note` is sent to `libpd` to start the sequencer.
    2. `led_effect_id` is pushed to the Hardware Worker queue.
    3. `chladni_id` parameters (frequency/amplitude) are loaded into the Transducer generators.
    4. `vol_l`/`vol_r` are stored to scale the *Music* channels (1 & 2) only.

#### **B. Command: `channel_state`**
Manages isolated muting of the two audio subsystems.
- **Payload:**
  ```json
  {
      "message_type": "channel_state",
      "command": {
          "transducer_mute": false,
          "music_mute": true
      }
  }
  ```
- **Logic:** `music_mute: true` additionally sends a `-1` stop signal to the PureData sequencer.

#### **C. Command: `ping`**
Heartbeat to maintain connection and reset the failsafe watchdog.
- **Payload:** `{"message_type": "ping"}`
- **Failsafe:** If the Core misses 3 consecutive pings (3 seconds), it automatically silences all outputs.

---

### **2.2. C++ Core $\leftrightarrow$ PureData (Internal `libpd`)**
Communication is frame-accurate and handled via C callbacks.

- **Inbound (`libpd_float`):**
    - `from_core`: Receives `root_note` (0-127) to seed the sequencer or `-1` to stop.
- **Outbound (`pd_float_hook`):**
    - `to_core`: Receives the integer note currently being played by the PD sequencer. This note is used to instantly synchronize the transducers and LEDs.

---

### **2.3. C++ Core $\rightarrow$ RPi Pico (Serial)**
ASCII-based protocol over USB-Serial (9600 baud).
- **Command:** `FX:<id>\n` (e.g., `FX:3\n`)
- **Execution:** Handled by a dedicated background worker thread to prevent blocking the audio callback.

---

## 3. Execution Model & Routing

### **Three-Tier Threading**
1. **Thread 1 (ZMQ):** High-level command ingestion. Updates atomic state.
2. **Thread 2 (Audio/Sacred):** PortAudio callback. Processes `libpd` and generates Transducer sine waves. 
3. **Thread 3 (Hardware):** Consumes a Lock-Free Queue to perform Serial `write()` operations to the Pico.

### **Audio Routing (`system_config.json`)**
The Core uses logical-to-physical mapping to avoid ALSA device collisions:
- **Channels 1 & 2:** Dedicated to **Generative Music** (from `libpd`). Scaled by `vol_l`/`vol_r`.
- **Channels 5, 6, 7, 8:** Dedicated to **Transducers 1, 2, 3, 4**. Frequencies and amplitudes are derived strictly from `master_symbols.json` and are **not** affected by music volume sliders.

---

## 4. Performance & Reliability
- **Configurability:** `SAMPLE_RATE` is defined in `system_config.json`.
- **Safety:** The `LockFreeQueue` prevents blocking I/O in the real-time thread.
- **Cleanup:** Legacy UDP logic (`puredata` component) is deprecated and moved to standalone debug tools.
