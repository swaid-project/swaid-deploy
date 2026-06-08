# Plate Resonance (C++ Server): Full Architecture & Specification

## 1. System Overview

The Plate Resonance Server is a C++ application designed to act as a high-performance, real-time hardware orchestrator. It receives state commands via an IPC ZeroMQ (`REQ/REP`) socket from the Human-Interface (Python UI).

The server is strictly a "Dumb Server". It does not make logical decisions about what symbols mean; it simply maps incoming `music_note` requests to physical hardware actions:

1. Synthesizing 4-channel sine waves to an external USB Soundcard using precisely timed DSP amplitude envelopes (Fade In, Sustain, Fade Out).
2. Routing LED effect IDs via USB-Serial to a Raspberry Pi Pico.
3. Sending music generation commands via UDP network sockets to an external PureData audio instance.

---

## 2. Server Start-Up Procedure

When the C++ executable is launched, it must execute a strict, linear initialization sequence before opening the ZMQ port to the client.

1. **Configuration Loading:**
* Parse `system_config.json` to acquire the target Audio Device name, Sample Rate, and UDP ports (3000 and 3001).
* Parse `master_symbols.json` into an O(1) in-memory hash map. **Crucial:** The map is keyed by `music_note` (integer) so the server can instantly retrieve the corresponding `chladni_id`, `LED_effect`, `symbol_duration_ms`, `fade_in_ms`, and `fade_out_ms` without the client needing to transmit them.


2. **State Initialization:**
* Set internal variables to default safe states: `current_note = -1`, `current_chladni_id = "NONE"`, `led_effect_id = -1`.
* Initialize boolean states: `music_state = false` (disabled), `transducer_state = false` (muted), `is_busy = false` (ready for commands).


3. **UDP Socket Initialization:**
* Create UDP sockets bound to `localhost` targeting ports 3000 and 3001.
* *Note:* PureData boots into `music_disable` by default. The C++ Server must explicitly send a disable message ("0") to port 3001 on boot to ensure that the music state is initialized to disabled.


4. **Hardware Discovery & Connection:**
* Initiate the PortAudio search for the external soundcard (See Section 5.1).
* Initiate the Serial search for the Pico (See Section 5.2).


5. **Open IPC ZMQ:**
* Bind the `REP` socket to `ipc:///tmp/swaid.sock`. The server is now ready.



---

## 3. Communication Protocol (ZeroMQ REQ/REP)

The server operates on a strict request-reply cycle. Every JSON payload received from the client **must** be immediately answered with a standard diagnostic reply.

*Note: The Human-Interface client is responsible for reading the symbol durations from its own copy of `master_symbols.json` and actively blocking user inputs during the (fade_in + duration + fade_out) window to prevent command spamming.*

### 3.1. Command: `trigger`

Fired when the Human-Interface detects a user gesture selecting a symbol.

* **Client Request (REQ):**

```json
{
  "message_type": "trigger",
  "music_note": 2
}

```

* **Server Execution Sequence:**
1. **Concurrency Check:** If `is_busy == true`, the server ignores the trigger to protect ongoing acoustic sequences.
2. **Lookup:** Uses the parsed `master_symbols.json` map to look up the complete symbol object associated with `music_note: 2`.
3. **DSP Enveloping (Transducers):** The server calculates three lock-free timestamps based on the current system time:
* `t_sustain = current_time + fade_in_ms`
* `t_release = t_sustain + symbol_duration_ms`
* `t_end = t_release + fade_out_ms`
* The ultra-fast Audio Thread uses these atomic timestamps (`t_start`, `t_sustain`, `t_release`, `t_end`) to seamlessly interpolate the transducer amplitudes on the assigned physical channels (mapped via `system_config.json`, e.g., 5, 6, 7, and 8). The `generateSineWaves` function continuously calculates the real-time amplitude. It linearly ramps from 0 to `AMP_VALUE` until `t_sustain`, holds steady until `t_release`, and ramps down to 0 until `t_end`. Phase increment is calculated per sample block to ensure continuous waveform phase (`currentBasePhase`) without popping.


4. **LEDs:** Pushes the mapped `LED_effect` into a thread-safe Lock-Free Queue to be processed by the background Pico serial thread.
5. **PureData (UDP 3000 & 3001):** Transmits the `music_note` payload via UDP to port 3000 (`pdSender`) to instruct PureData which musical sequence to generate. If `music_state` is currently `false` (disabled), the server sends an enable message ("1") to port 3001 (`pdMuteSender`) to enable the music, and updates its internal `music_state` to `true`. Once enabled, the music remains enabled unless explicitly muted or a timeout occurs.



### 3.2. Command: `shuffle`

Allows the UI to trigger a pre-programmed acoustic sequence to evenly redistribute the sand on the plate, clearing previous patterns.

* **Client Request (REQ):**

```json
{
  "message_type": "shuffle"
}

```

* **Server Execution Sequence:**
1. Sets atomic flag `is_busy = true` to ignore overlapping triggers.
2. Spawns a **Detached C++ Thread** (`std::thread::detach`) that iterates through a pre-programmed shuffle sequence (e.g., `SHUFFLE_1`, `SHUFFLE_2`, etc. loaded from the JSON).
3. For each shuffle step, it calculates and applies the exact same DSP Enveloping logic (`fade_in` -> `sustain` -> `fade_out`), utilizing `std::this_thread::sleep_for(total_duration)` before moving to the next frequency set.
4. Once the entire sequence finishes, it ensures all amplitudes rest at 0.0, and resets `is_busy = false`.



### 3.3. Command: `ping` (Heartbeat @ 10Hz)

Used to maintain the connection, keep the hardware alive, and synchronize UI state.

* **Client Request (REQ):**

```json
{
  "message_type": "ping"
}

```

* **Server Execution Sequence:**
* The server updates a `last_ping_timestamp`. (See Section 6 for Timeout Logic).
* If the system was previously in a timeout/muted state, receiving a ping immediately unmutes the soundcard channels, but the music remains disabled. The music will only be re-enabled upon the receipt of the next trigger message.



### 3.4. Standard Server Response (REP)

Regardless of whether the request was `trigger`, `shuffle`, or `ping`, the server **always** responds with this exact payload structure:

```json
{
  "status": "ok",
  "diagnostics": {
    "pico_serial": 1,
    "usb_audio": 1,
    "UDP_connection": 1,
    "music_state": 1,
    "transducer_state": 1
  },
  "active_state": {
    "current_note": 2,
    "current_chladni_id": "CHLADNI_191",
    "led_effect_id": 1
  }
}

```

* **Diagnostics:** `1` indicates healthy/active, `0` indicates disconnected/muted/error.
* **Active State:** Echoes the variables currently locked into the C++ server memory.

---

## 4. Internal Threading Architecture

To prevent the UDP network sends or the Pico Serial port from blocking the real-time audio soundcard, the server must be strictly divided into four asynchronous threads:

* **Thread 1: The ZMQ Listener (Command Ingestion)**
* Blocks on `zmq_recv`. Parses incoming JSON.
* Calculates `t_sustain`, `t_release`, and `t_end` timestamps and updates shared `std::atomic` variables.
* Executes UDP network sends to 3000/3001.
* Formulates and sends the JSON REP.


* **Thread 2: PortAudio Callback (Sacred Audio DSP)**
* Ultra-fast, real-time OS thread.
* Reads atomic timestamps. Modulates target amplitudes to create smooth ASR (Attack-Sustain-Release) envelopes.
* Generates pure sine waves into the `outBuffer` for Channels 5-8.
* *Rule:* Never performs memory allocation, std::cout, or network/serial I/O.


* **Thread 3: Hardware Worker (Pico Serial)**
* Reads from a thread-safe `LockFreeQueue<int> ledQueue`.
* Handled by the `hardwareWorkerThread()`, it executes blocking `write()` operations (e.g., `"FX:1\n"`) to the `/dev/ttyACM*` file descriptor through the `EmbeddedSAL` interface.
* If a write fails or connection drops, it enters a recovery mode, buffering the pending command, and attempts to reconnect.


* **Thread 4: Main / Watchdog (Auto-Recovery)**
* Runs an infinite sleep loop checking connection health and managing reconnects.



---

## 5. Device Discovery & Auto-Recovery (Self-Healing)

The system is designed to run unattended. If a cable is unplugged, the server must not crash. It must flag the error in the JSON `diagnostics`, and poll infinitely until the hardware is restored.

### 5.1. USB Soundcard Discovery (Watchdog)

* **Initial Boot / Reconnection:** The Watchdog thread calls `Pa_GetDeviceInfo()` and iterates through all connected OS audio devices. It performs a substring match against the device name specified in `system_config.json` (e.g. `ICUSBAUDIO7D`). It also validates that `info->maxOutputChannels` meets the required minimum channels; if channels return 0, it means the device is currently locked by another audio process (like PulseAudio or a zombie resonance server), logging a specific failure to the user.
* **Health Check:** Every 2 seconds, the Watchdog calls `Pa_IsStreamActive()`.
* **Failure State:** If the stream aborts (cable pulled), `diagnostics["usb_audio"]` is set to `0`. The Watchdog safely calls `Pa_Terminate()`, waits 5 seconds, and attempts the Discovery sequence again.

### 5.2. Raspberry Pi Pico Discovery (Thread 3)

* **Initial Boot / Reconnection:** Thread 3 scans `/dev/` for `ttyACM*` or `ttyUSB*`. If found, it configures `termios` for 9600 baud, 8N1.
* **Health Check:** Tracked during the `write()` command when popping from the queue.
* **Failure State:** If `write(fd, payload, size)` returns `-1`, the USB serial connection has dropped. `diagnostics["pico_serial"]` is set to `0`. Thread 3 closes the file descriptor, sleeps for 2 seconds, and re-runs the `/dev/` scan until successful.

### 5.3. UDP Connection Failsafe

Because UDP is connectionless ("fire and forget"), the server cannot truly know if PureData is listening.

* The `diagnostics["UDP_connection"]` is determined by the success of the C++ `sendto()` socket system call. If the local OS network stack fails to route the packet, this drops to `0`.

---

## 6. The Heartbeat Timeout Failsafe

To protect the physical Chladni plate hardware from overheating or generating noise if the Python UI crashes, the server employs a Dead Man's Switch.

1. **Tracking:** Every time a `ping` (or any valid message) arrives in Thread 1, a `std::chrono` timestamp is updated (`last_valid_msg_time`).
2. **Monitoring:** Inside the Main Watchdog thread loop, the server compares the current time to `last_valid_msg_time`.
3. **The Trigger:** If the delta exceeds **2000 milliseconds (2.0 seconds)**, the server enters Emergency Mute:
* Sets `diagnostics["transducer_state"] = 0` and forcefully fades amplitudes on channels 5-8 to 0.0.
* Sets `diagnostics["music_state"] = 0` and sends a disable message ("0") to UDP port 3001 to disable PureData.


4. **Recovery:** The instant a new `ping` or `trigger` is received, the timestamp is refreshed, the server automatically reverses the mute states, and normal operation resumes.

---

## Appendix A: `master_symbols.json` Schema Requirement

The system architecture mandates that all timing, routing, and acoustic parameters are centralized in the JSON configuration. This ensures that visual, musical, and physical hardware modifications can be made without recompiling the C++ Core.

Each symbol object in the JSON array must strictly adhere to the following schema:

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
            { "output": 1, "frequency_hz": 190.5, "amplitude": 0.2, "phase_deg": 0 },
            { "output": 2, "frequency_hz": 190.5, "amplitude": 0.2, "phase_deg": 0 },
            { "output": 3, "frequency_hz": 190.5, "amplitude": 0.2, "phase_deg": 0 },
            { "output": 4, "frequency_hz": 190.5, "amplitude": 0.2, "phase_deg": 0 }
        ]
    },
    "ui_metadata": {
        "image_path": "./dictionary/CHLADNI_191.png"
    }
}
```

## Appendix B: Audiovisual Synchronization (Staggered Execution)

To ensure perceptual tightness between the mechanical vibration, the LED flash, and the PureData audio synthesis, the server employs a **Timestamp-Based Staggered Execution**. 

Because different external subsystems have inherently different dispatch latencies (e.g., localhost UDP is nearly instantaneous, while USB-Serial UART has OS polling lag), dispatching them "simultaneously" causes noticeable A/V desync (flamming).

The server offsets execution delays per-peripheral to allow slower mediums to "catch up". These offsets are centrally managed in `system_config.json` allowing empirical calibration without recompilation:

```json
"synchronization_offsets_ms": {
    "puredata_udp": 0,
    "pico_serial": 0,
    "soundcard": 25
}
```

**Implementation Strategy:**
1. **UDP / PureData:** Dispatched immediately (typically `+0ms` offset).
2. **Serial / Pico:** Placed into the `ledQueue`. The hardware worker thread evaluates the offset duration before pushing the `write()` command over the USB bus.
3. **PortAudio / Transducers:** The `t_start` timestamp variable for the DSP amplitude envelopes is pushed into the future by the specified offset. The real-time callback thread naturally waits for the system clock to cross `t_start` before moving amplitudes away from 0.0.
