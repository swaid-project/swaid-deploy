# SWAID Resonance Core

The central orchestration node and primary service runner for the SWAID project.

---

## Role

The C++ Core is a high-performance, multi-threaded application that ingests front-end commands via IPC, coordinates real-time audio synthesis (PortAudio), forwards LED commands (serial Pico), and directs the remote music synthesizer (UDP PureData).

---

## Key Architecture

### 1. ZeroMQ Command Server
Binds to an IPC Unix domain socket at `ipc:///tmp/swaid.sock`. It receives JSON payloads from the Python client and responds immediately with diagnostic and status updates.

### 2. Multi-Threaded Operation
- **Thread 1 (ZMQ Command Ingestion)**: Listens for incoming commands (e.g., `trigger`, `shuffle`, `ping`). It parses inputs, updates shared state atomically, dispatches UDP audio packets, and sends reply payloads.
- **Thread 2 (Soundcard DSP)**: Running in PortAudio's high-priority thread, this callback computes real-time sine waves for 4 independent channels (logical transducers 1-4 mapped to physical channels) utilizing atomic timestamps for frame-accurate ASR (Attack-Sustain-Release) envelopes.
- **Thread 3 (Serial Dispatcher)**: A background worker thread running in a loop, popping LED effects from a lock-free queue and writing them to the Raspberry Pi Pico via USB-Serial.
- **Thread 4 (Watchdog and System Monitor)**: Running on the main program thread. It evaluates the 2.0s watchdog heartbeat, checks the status of PortAudio streams, and triggers self-healing routines if hardware connection drops.

### 3. Mutex-Locked State Protection
Accesses to global state strings (such as `current_active_chladni` updated by the detached shuffle thread) are protected using mutex blocks (`std::mutex`) to prevent concurrency data races.

---

## Dependencies

- `zmq` (libzmq and cppzmq bindings)
- `portaudio` (v19)
- `nlohmann_json` (JSON parser)
- `soundcard` (Internal transducer project library)
- `led_driver` (Internal Pico Serial SAL library)
- `puredata` (Internal UDP network library)
