# SWAID — Bug Report & Analysis
**Date:** 2026-06-05  
**Analyst:** Claude Code  
**Branch:** HI-Integration  
**Sources reviewed:** `plate-resonance/`, `human-interface/src/`, `log.txt`, `client_ipc.log`, `system_config.json`, `MusicSynthesis/file1.pd`

---

## Project Overview

SWAID is an interactive musical installation based on Chladni plate resonance. The system has three main components:

| Component | Tech | Role |
|-----------|------|------|
| `plate-resonance` (C++) | PortAudio, libpd, ZeroMQ | Audio engine, LED control, ZMQ server |
| `human-interface` (Python/PySide6) | MediaPipe, ZeroMQ, OpenCV | Hand-tracking UI, ZMQ client |
| `MusicSynthesis` (PureData) | libpd | Music synthesis embedded in C++ core |

Communication: ZMQ REQ/REP over `ipc:///tmp/swaid.sock`. Hardware: ICUSBAUDIO7D USB soundcard (8ch), Raspberry Pi Pico over `/dev/ttyACM0` for LEDs.

---

## Critical Bugs

### BUG-01 — Segmentation Fault in `resonance_core`
**Severity:** Critical  
**File:** `swaid_launcher.sh:36` / `plate-resonance/build/resonance_core/resonance_core`  
**Log evidence:**
```
./swaid_launcher.sh: line 36: 44757 Segmentation fault "$CORE_EXE"
```

The C++ core crashes with SIGSEGV shortly after audio is restored. This happens on the **second** run in the session log (after the first clean shutdown). The most likely root cause is the `applyPattern` detached thread (see BUG-02) or the libpd thread-safety violation (see BUG-03) causing a use-after-free.

---

### BUG-02 — SPSC Queue Contract Violated by Hardware Worker Thread
**Severity:** Critical  
**File:** `plate-resonance/resonance_core/src/resonance_server.cpp:59`

The `LockFreeQueue<int> ledQueue` is explicitly documented as SPSC (Single-Producer Single-Consumer). The intended producer is the ZMQ listener thread (`jsonListenerThread`). However, when a serial write fails, the hardware worker thread **re-pushes** the effect back into the queue:

```cpp
// hardwareWorkerThread() — THE CONSUMER re-pushing to the queue (WRONG)
ledQueue.push(effectId.value()); // line 59
```

This makes the consumer also act as a producer, which is undefined behavior for an SPSC lock-free queue. The atomics in `LockFreeQueue` only provide correct ordering guarantees when exactly one thread writes `tail` and one thread writes `head`. Having the consumer modify `tail` can cause silent data corruption or an infinite loop.

**Fix:** Use a `std::mutex`-protected `std::queue`, or use a true MPMC queue, or handle retry logic via a local variable without re-pushing.

---

### BUG-03 — libpd Thread Safety Violation
**Severity:** Critical  
**Files:** `resonance_core/src/resonance_server.cpp:240`, `soundcard/src/audio_driver.cpp:148,194`

`libpd_float("from_core", music_note)` is called from the **ZMQ listener thread**:
```cpp
// jsonListenerThread — ZMQ thread
libpd_float("from_core", (float)music_note); // resonance_server.cpp:240
```

At the same time, `libpd_process_float(ticks, nullptr, pdOut.data())` is called from the **PortAudio audio callback thread**:
```cpp
// mixMusic() called from audioCallback / musicCallback — audio thread
libpd_process_float(ticks, nullptr, pdOut.data()); // audio_driver.cpp:148
```

libpd is **not thread-safe**. Calling `libpd_float` from one thread while `libpd_process_float` runs on another thread is a data race that can corrupt libpd's internal DSP state and cause the SIGSEGV in BUG-01.

**Fix:** Use `libpd`'s message queue mechanism, or protect all libpd calls with a mutex, or enqueue note changes via the same atomic mechanism used for generator frequencies.

---

### BUG-04 — Dual `EmbeddedSAL::connect()` Race at Startup
**Severity:** High  
**File:** `resonance_core/src/resonance_server.cpp:155`, `resonance_server.cpp:63-67`  
**Log evidence:**
```
[LED SAL] Connected to Pico (fd=4)   ← from jsonListenerThread
...
[LED SAL] Connected to Pico (fd=9)   ← from hardwareWorkerThread
```

Both `jsonListenerThread` and `hardwareWorkerThread` call `ledDriver.connect()` independently at startup. This opens `/dev/ttyACM0` twice, leaking one file descriptor (fd=4 is never closed once fd=9 replaces it). On reconnect cycles this leaks additional fds and may exhaust the process fd limit.

`EmbeddedSAL::connect()` checks nothing before calling `findPicoPort()` which opens the device unconditionally. The `fd_` atomic is set only after success, creating a TOCTOU window between the two threads.

**Fix:** Add a mutex inside `EmbeddedSAL::connect()` with an early-return check on `isConnected()`, or only let one thread be responsible for initial connection.

---

## High-Severity Bugs

### BUG-05 — `applyPattern` Detached Thread Race on Generator Amplitudes
**Severity:** High  
**File:** `soundcard/src/audio_driver.cpp:101-112`

`applyPattern` detaches a thread that interpolates `generators[i].amp` over 100ms:
```cpp
std::thread([fromAmps, toAmps, duration, symbol_id]() {
    for (int s = 1; s <= steps; s++) {
        for (int i = 0; i < NUM_GENERATORS; i++)
            generators[i].amp.store(fromAmps[i] + t * (toAmps[i] - fromAmps[i]));
        ...
    }
}).detach(); // audio_driver.cpp:112
```

If `applyPattern` is called again within 100ms (rapid note changes), a second detached thread starts. Both threads now write to `generators[i].amp` concurrently. While each individual `store` is atomic, the interpolation sequence from the first thread is corrupted by the second — causing clicks, amplitude jumps, or undefined output.

**Fix:** Cancel the previous fade thread before starting a new one, or use a single persistent fade goroutine driven by an atomic target + timestamp.

---

### BUG-06 — PureData Patch Connection Errors (Functional)
**Severity:** High  
**File:** `MusicSynthesis/file1.pd`  
**Log evidence:**
```
file1.pd 0 0 153 0 (loadbang->loadbang) connection failed
cannot connect to non-existing object
file1.pd 103 0 157 0 (*~->???) connection failed
cannot connect to non-existing object
file1.pd 104 0 157 1 (+->???) connection failed
error: audio signal outlet connected to nonsignal inlet (ignored)
```

Three connections in `file1.pd` reference objects that don't exist or have wrong types:
- Connection `0 → 153`: `loadbang` trying to connect to a missing object (index 153 doesn't resolve to a valid loadbang in the current patch).
- Connection `103 → 157`: `*~` (signal) trying to connect to `???` (missing object).
- Connection `104 → 157`: `+` (control) trying to connect to a signal inlet.

These errors mean the DSP output chain for the `dac~` (audio output) is broken — **music synthesis output may be partially or fully silent**.

---

### BUG-07 — `receive from_core` Missing from PureData Patch
**Severity:** High  
**File:** `MusicSynthesis/file1.pd`, `resonance_core/src/resonance_server.cpp:240`

The C++ core sends the music note via:
```cpp
libpd_float("from_core", (float)music_note);
```
This requires a `[receive from_core]` object in the PD patch to receive the value. The patch (`file1.pd`) contains no such receiver — it uses `[netreceive 3000 1]` and `[netreceive 3001 1]` (TCP sockets) internally, and hardcoded note logic. **Note changes triggered by the UI have no effect on the music synthesis.**

---

## Medium-Severity Bugs

### BUG-08 — Camera Resolution Typo
**Severity:** Medium  
**File:** `human-interface/src/vision/hand_tracking.py:25`

```python
CAMERA_WIDTH = 1980   # Should be 1920
CAMERA_HEIGHT = 1020
```

`1980` is not a standard resolution. Most webcams support `1920×1080`. This causes `cap.set(CAP_PROP_FRAME_WIDTH, 1980)` to silently fall back to the nearest supported resolution (likely 1920), which then doesn't match what the code expects, potentially causing letterboxing artifacts in `letterbox_for_detection`.

---

### BUG-09 — Mixed `time.time()` / `time.monotonic()` in Dwell Logic
**Severity:** Medium  
**File:** `human-interface/src/ui/interface.py:223,229`

```python
if time.time() - self._last_note_change < 1.0: return    # line 223 — wall clock
...
self._last_note_change = time.time()                       # line 229 — wall clock
```

All other timing in `interface.py` and `hand_tracking.py` uses `time.monotonic()`. If the system clock is adjusted (NTP sync, DST), `_last_note_change` can jump, causing either the debounce to be skipped entirely (triggering rapid-fire notes) or locking up note selection for many seconds.

**Fix:** Replace both with `time.monotonic()`.

---

### BUG-10 — Duplicate Logger Instantiation
**Severity:** Medium  
**File:** `human-interface/src/network/resonance_client.py:10-15`

```python
logging.basicConfig(level=logging.DEBUG, format='[Python UI] %(levelname)s: %(message)s')
logger = logging.getLogger("ResonanceClient")   # line 10 — first assignment
...
logger = logging.getLogger("ResonanceClient")   # line 14 — overwrites line 10
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler("client_ipc.log")
```

The root logger from `basicConfig` and the named `ResonanceClient` logger both propagate to stderr, so every log message appears **twice** in the console (once via root handler, once via named handler propagation). The first `logger` assignment on line 10 is immediately useless.

**Fix:** Remove the `basicConfig` call, or set `logger.propagate = False` after adding the file handler.

---

### BUG-11 — `diag_hdmi_audio` Always Set to 1 After Audio Recovery
**Severity:** Medium  
**File:** `plate-resonance/resonance_core/src/main.cpp:60`

```cpp
if (m_stream || t_stream) diag_hdmi_audio.store(1); // always true if audio setup succeeded
```

Since `setupAudioStreams` only returns `true` when at least `t_stream` is open, `t_stream` is never null here. `diag_hdmi_audio` is always forced to 1 after any successful audio recovery, regardless of whether HDMI audio is actually active. The client log shows `"hdmi_audio": 0` during disconnected states but the diagnostic name is misleading — it tracks "any audio" not "HDMI audio".

---

### BUG-12 — ZMQ `recv` Timeout Applied Before Heartbeat Check
**Severity:** Medium  
**File:** `resonance_core/src/resonance_server.cpp:187-198`

```cpp
auto result = rep_socket.recv(msg, zmq::recv_flags::none);

long long now = ...;
if (now - lastHeartbeat.load() > 3) {
    masterMute.store(true); // FAILSAFE
}

if (!result) continue;  // check result AFTER failsafe check
```

The socket has a 500ms receive timeout (`rcvtimeo = 500`). On timeout, `result` is empty, and `continue` skips the message processing. But the heartbeat check happens **before** `if (!result) continue` — this is correct in intent but means the failsafe fires based on `now - lastHeartbeat`, which is only updated on valid `ping` messages. If the Python client is sending pings but RECV times out spuriously, `masterMute` gets incorrectly set. More importantly, `lastHeartbeat` is never updated on non-ping messages, so intensive `trigger` traffic with no pings will falsely fire the failsafe within 3 seconds.

**Fix:** Update `lastHeartbeat` on every successfully received message, not only on `ping`.

---

## Low-Severity Issues

### BUG-13 — Hand Tracking `sorted_lms` Left/Right Assignment
**Severity:** Low  
**File:** `human-interface/src/vision/hand_tracking.py:191-193`

```python
sorted_lms = sorted(res.hand_landmarks, key=lambda h: sum(l.x for l in h)/len(h))
left = normalized_landmark_points(sorted_lms[0], mapping)
if len(sorted_lms) >= 2: right = normalized_landmark_points(sorted_lms[-1], mapping)
```

Hands are sorted by mean X position. The leftmost hand in the camera frame is named `left` and rightmost is named `right`. However, because the frame is flipped (`cv2.flip(frame, 1)` on line 165), the camera's left corresponds to the user's right. **The left/right labels are swapped relative to the actual hand.** This may cause incorrect closed-hand detection (the gesture for note selection uses `left_hand`).

---

### BUG-14 — `sendEffect` Skips Effect ID 0
**Severity:** Low  
**File:** `plate-resonance/led_driver/src/embedded_sal.cpp:84,87`

```cpp
bool EmbeddedSAL::sendEffect(int fx_id) {
    if (fx_id < 0 || fx_id >= TOTAL_LED_EFFECTS) return true;  // line 84
    if (current_effect_.load() == fx_id) return true;           // line 87
```

`current_effect_` is initialized to `0` in the constructor. If the first requested effect is also `0`, `sendEffect` returns early on line 87 without actually sending the command. The Pico starts in an undefined state so effect `0` may not be playing. The first trigger to note 0 will always silently fail.

**Fix:** Initialize `current_effect_` to `-1`.

---

### BUG-15 — No Camera Access Error Handling in `HandTrackingThread`
**Severity:** Low  
**File:** `human-interface/src/vision/hand_tracking.py:136`

```python
cap = open_camera(self.camera_index)
if not cap.isOpened(): return
```

When the camera fails to open, the thread silently returns. No signal is emitted, the UI never shows a warning, and `state["tracker"]` points to a dead thread. The UI continues showing "HB OK" and no camera feed — with no indication to the user that hand tracking is completely offline.

**Log evidence:**
```
[ WARN:0@1.824] global cap_v4l.cpp:914 open VIDEOIO(V4L2:/dev/video0): can't open camera by index
[ERROR:0@1.826] global obsensor_uvc_stream_channel.cpp:163 getStreamChannelGroup Camera index out of range
```

---

## Summary Table

| ID | Component | Severity | Description |
|----|-----------|----------|-------------|
| BUG-01 | C++ Core | Critical | Segmentation fault on second boot |
| BUG-02 | C++ Core | Critical | SPSC queue used as MPSC — data corruption |
| BUG-03 | C++ Core | Critical | libpd called from two threads simultaneously |
| BUG-04 | C++ Core | High | `EmbeddedSAL::connect()` race at startup, fd leak |
| BUG-05 | C++ Core | High | Detached fade threads race on generator amplitudes |
| BUG-06 | PureData | High | Three broken connections in `file1.pd` — DSP chain broken |
| BUG-07 | PureData | High | `receive from_core` missing — note changes have no effect |
| BUG-08 | Python UI | Medium | Camera width typo: 1980 instead of 1920 |
| BUG-09 | Python UI | Medium | Mixed `time.time()` / `time.monotonic()` in dwell timing |
| BUG-10 | Python UI | Medium | Duplicate logger — double stderr output |
| BUG-11 | C++ Core | Medium | `diag_hdmi_audio` always 1 after audio recovery |
| BUG-12 | C++ Core | Medium | Heartbeat failsafe not updated on non-ping messages |
| BUG-13 | Python UI | Low | Left/right hand labels swapped after `cv2.flip` |
| BUG-14 | C++ Core | Low | `sendEffect` never sends effect ID 0 (initial state) |
| BUG-15 | Python UI | Low | Silent camera failure — no UI warning emitted |

---

