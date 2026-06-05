# SWAID — Change Log
**Date:** 2026-06-05  
**Branch:** HI-Integration  
**Author:** Claude Code (automated fix pass)  
**Compiler verified:** `cmake --build . --target resonance_core` passes cleanly after all C++ edits.

Fixes are grouped by severity. See `BugReport.md` for full diagnosis. Bugs deferred in this pass are listed at the bottom.

---

## Critical Fixes

### BUG-03 — libpd thread-safety violation (most likely cause of SIGSEGV)
**Files changed:** `global.cpp`, `audio_driver.hpp`, `audio_driver.cpp`, `resonance_server.cpp`

`libpd_float("from_core", note)` was being called from the ZMQ listener thread while `libpd_process_float()` ran concurrently in the audio callback. libpd is not thread-safe — this data race is the most probable root cause of the segmentation fault (BUG-01).

**Fix:** Introduced `std::atomic<int> pendingLibpdNote{-2}` (`-2` = nothing pending). The ZMQ thread now stores the note with `pendingLibpdNote.store(note, release)` instead of calling libpd directly. Each audio callback (`audioCallback` combined mode, `musicCallback` separate mode) atomically exchanges the pending note with `-2` and — if a note was waiting — calls `libpd_float` on the audio thread immediately before `libpd_process_float`. This guarantees both calls happen on the same thread.

- `global.cpp`: Added definition `std::atomic<int> pendingLibpdNote{-2}`
- `audio_driver.hpp`: Added `extern std::atomic<int> pendingLibpdNote` declaration
- `audio_driver.cpp:audioCallback`: `pendingLibpdNote.exchange(-2)` + conditional `libpd_float` before `mixMusic()`
- `audio_driver.cpp:musicCallback`: same exchange pattern before `libpd_process_float()`
- `resonance_server.cpp`: `libpd_float("from_core", ...)` → `pendingLibpdNote.store(...)` in both `trigger` and `channel_state` handlers

### BUG-02 — SPSC queue contract violated by hardware worker retry
**File changed:** `resonance_server.cpp`

When the Pico serial write failed and reconnection also failed, the hardware worker thread (the queue **consumer**) was re-pushing to `ledQueue` via `ledQueue.push()` — making it also a producer. `LockFreeQueue` is explicitly SPSC; having the consumer write `tail` corrupts the lock-free ordering guarantees.

**Fix:** Introduced `std::optional<int> pendingRetry` local to `hardwareWorkerThread`. Failed reconnection now saves the effect to `pendingRetry` instead of re-pushing. The next loop iteration checks `pendingRetry.has_value()` before calling `ledQueue.pop()`, draining the local retry without touching the SPSC queue from the wrong thread.

---

## High Fixes

### BUG-04 — Dual `EmbeddedSAL::connect()` race at startup (fd leak)
**File changed:** `resonance_server.cpp`

Both `jsonListenerThread` and `hardwareWorkerThread` independently called `ledDriver.connect()` at startup. This opened `/dev/ttyACM0` twice, leaking the first file descriptor every restart cycle.

**Fix:** Removed the `ledDriver.connect()` block from `jsonListenerThread` entirely. The hardware worker is already responsible for monitoring and restoring the Pico connection via its idle-loop reconnect logic — there is no need for the ZMQ thread to also initiate it.

### BUG-05 — Concurrent detached fade threads race on generator amplitudes
**File changed:** `audio_driver.cpp`

`applyPattern()` detached a 100ms interpolation thread every time it was called. Rapid note changes (< 100ms apart) spawned multiple concurrent threads all writing to `generators[i].amp`, corrupting the interpolation and causing amplitude jumps or clicks.

**Fix:** Added `static std::atomic<unsigned long long> fadeGeneration{0}` in `audio_driver.cpp`. Each `applyPattern` call increments the counter and captures its generation id (`myGen = ++fadeGeneration`). The detached thread checks `fadeGeneration == myGen` before each step and at final write — if a newer call has started, the old thread exits immediately without writing. Only the latest fade runs to completion.

---

## Medium Fixes

### BUG-12 — Heartbeat failsafe fires under normal trigger traffic
**File changed:** `resonance_server.cpp`

`lastHeartbeat` was only updated when the message type was `"ping"`. Sustained `trigger` traffic with no explicit pings would trigger `masterMute` after 3 seconds even when the client was actively communicating.

**Fix:** Added `lastHeartbeat.store(now)` immediately after `if (!result) continue;` — i.e., on every successfully received message, regardless of type.

### BUG-08 — Camera resolution width typo
**File changed:** `human-interface/src/vision/hand_tracking.py`

`CAMERA_WIDTH = 1980` is not a standard resolution. The correct HD width is `1920`.

**Fix:** `CAMERA_WIDTH = 1920`

### BUG-09 — Mixed `time.time()` / `time.monotonic()` in dwell debounce
**File changed:** `human-interface/src/ui/interface.py`

Lines 223 and 229 used `time.time()` (wall clock) while all other timing in the file used `time.monotonic()`. An NTP jump or DST change could bypass or lock the 1-second note debounce.

**Fix:** Both occurrences replaced with `time.monotonic()`.

### BUG-10 — Duplicate logger causing double console output
**File changed:** `human-interface/src/network/resonance_client.py`

`logging.basicConfig(...)` added a handler to the root logger, and `logger.propagate` defaulted to `True`, so every `ResonanceClient` log message appeared twice in the console (once via the named logger's `StreamHandler`, once via root propagation).

**Fix:** Removed `basicConfig` call. Set `logger.propagate = False`. Added an explicit `StreamHandler` with the `[Python UI]` prefix format directly on the named logger, keeping the same console output without duplication.

---

## Low Fixes

### BUG-14 — `sendEffect` skips LED effect 0 on first call
**File changed:** `plate-resonance/led_driver/src/embedded_sal.cpp`

`current_effect_` was initialized to `0` in the constructor. The early-exit guard `if (current_effect_.load() == fx_id) return true` would silently no-op the very first call to `sendEffect(0)`, even though the Pico starts in an unknown state.

**Fix:** Changed constructor initializer from `current_effect_(0)` to `current_effect_(-1)`, so the first call for any valid effect (0–19) always sends the command.

---

---

## Session 3 Fixes (cold-boot segfault + camera + failsafe) — 2026-06-05

### BUG-06 — PD patch broken connections cause SIGSEGV in libpd DSP engine
**File changed:** `MusicSynthesis/file1.pd`

`file1.pd` contained 157 objects (indices 0–156). Two `#X connect` lines referenced object index 157, which does not exist. Object 103 (`*~ 0.5`, a DSP signal object) had its outlet wired to the nonexistent index 157. When libpd's DSP engine processes audio, it follows the outlet pointer to write samples into the destination buffer. With no object at 157, the pointer is null → writes to address 0 → SIGSEGV in the PortAudio callback.

This is why every cold boot crashed immediately after "Audio restored successfully." (`Pa_StartStream` triggers the callback, which runs `libpd_process_float`, which hits the null DSP buffer). Run 3 in the log survived only because the failsafe had already set `masterMute=true` (UI started after audio had been retrying for >3 s), preventing `libpd_process_float` from being reached.

**Fix:** `file1.pd` lines 257–258 — corrected both connections to target index 156 (`dac~ 1 2`, the audio output object):
- `#X connect 103 0 157 0;` → `#X connect 103 0 156 0;`
- `#X connect 104 0 157 1;` → `#X connect 104 0 156 1;`

### BUG-16 — Failsafe timer arms before UI has had a chance to connect
**File changed:** `plate-resonance/resonance_core/src/resonance_server.cpp`

The 3-second failsafe watchdog started counting from ZMQ bind time. On cold boot, audio device discovery takes 5–10 seconds before the core is "ready", but `jsonListenerThread` binds ZMQ almost immediately. The UI launcher waits only 2 seconds before starting the Python process; Python startup + first ping takes another 0.5–1 second. On slow boots (soundcard hot-plugged), the total time from ZMQ bind to first ping exceeds 3 seconds, causing the failsafe to mute before the session even begins. Once muted, audio stayed silent for the entire session (no automatic recovery path existed).

**Fix (two-part):**
1. Added `bool heartbeatReceived = false` (local to `jsonListenerThread`). The failsafe condition is now gated: `if (heartbeatReceived && now - lastHeartbeat > 3)`. The 3-second countdown does not start until the first ping arrives.
2. Added `bool muteFromFailsafe = false`. When the failsafe fires, this flag is set. The `ping` handler checks: if `muteFromFailsafe && masterMute`, it clears both — auto-unmuting when the client reconnects after a disconnect. This ensures the installation recovers silently from brief network/restart interruptions.

### BUG-15 (continued) — Camera scan hardcoded to indices 0 and 1
**Files changed:** `human-interface/src/vision/hand_tracking.py`, `human-interface/src/main.py`

Both `/dev/video0` and `/dev/video1` on this hardware are UVC interfaces exposed by the ICUSBAUDIO7D soundcard, not video capture devices. A USB webcam would enumerate at `/dev/video2` or higher. `FALLBACK_CAMERA_CHOICES = [0, 1]` and the `on_camera_error` handler only tried those two indices, so a connected webcam was never found.

**Fix:**
- `open_camera()` in `hand_tracking.py` now builds its candidate list dynamically: it starts with the requested source, then appends every device found via `Path("/dev").glob("video*")`. Each candidate is tested with `CAP_V4L2` then `CAP_ANY`; a `cap.read()` confirms the device can actually deliver frames (filters out audio-device UVC stubs that return `isOpened()=True` but produce no data). The function returns the first working camera found at any index.
- `on_camera_error()` in `main.py` dynamically scans `/dev/video*` at call time for the fallback list, replacing the static `FALLBACK_CAMERA_CHOICES`. This handles cameras appearing after startup (USB hot-plug).

---

## Deferred / Not Fixed

| Bug | Reason deferred |
|-----|-----------------|
| **BUG-07** (`receive from_core` missing from PD patch) | Requires adding a `[receive from_core]` object and wiring it into the DSP chain in PD itself. Must be validated aurally. |
| **BUG-11** (`diag_hdmi_audio` always 1) | Diagnostic naming is misleading but functionally harmless; the flag tracks "any audio active" not HDMI specifically. Renaming requires coordinating the key with the Python UI diagnostic panel. |
| **BUG-13** (left/right hand label swap) | The frame is flipped with `cv2.flip(frame, 1)` before landmark detection. The current label assignment (`sorted_lms[0]` = left) may already be correct after the flip — inverting without confirming the UX intent risks breaking correct behavior. Needs live camera test. |
