# Architectural Update Specification: The "Smart Client, Synchronized Core" Paradigm

**Version:** 6.0 (Final Production Readiness)
**Author:** Chief Software Engineer

**Target Audience:** Plate Resonance Team (C++)

**Date:** June 2026

## 1. Executive Summary

As we approach the final validation phase for the SWAID project, the architecture has fully transitioned to the **"Smart Client, Synchronized Core"** paradigm. The Python UI holds the state, while the C++ Core acts as a low-latency, real-time orchestrator containing embedded PureData (`libpd`).

While the core threading architecture (ZMQ Thread, PortAudio Thread, Hardware Worker Thread) is solid, this final update addresses four critical production requirements: Autonomous Headless Booting, Dual-Stream Audio Toggling, DSP Fading Optimization, and Real-Time Control-Rate Spam protection.

---

## 2. Autonomous Headless Boot (Removing Console I/O)

**The Problem:** The current `selectAudioDevice()` function in `main.cpp` relies on `std::cin` to ask the user to select an audio device. In a production environment where the system boots automatically on startup, this will freeze the application indefinitely.

**The Solution:** Implement String-Matching Device Discovery.

* **Update `system_config.json`:** Add target device name substrings.
* **Update `main.cpp`:** Iterate through `Pa_GetDeviceInfo(i)->name` and use standard string matching (e.g., `std::string::find`) to locate the requested devices.
* **Retry Loop:** If the device is not found (e.g., the USB soundcard is unplugged), the Core should not crash. It should enter a loop, sleeping for 5 seconds, and re-scan the PortAudio device list until the hardware is detected.

---

## 3. Dual-Stream Audio Routing (HDMI vs. USB Toggle)

**The Problem:** The system requires the flexibility to route the Generative Music (PureData) to either the TV/Monitor speakers (HDMI) or the external Soundcard speakers (USB), while always routing the Transducer sine waves to the USB Soundcard.

**The Solution:** Update the `system_config.json` routing schema and implement conditional PortAudio stream creation.

**New Config Schema:**

```json
"audio_routing": {
    "transducer_device_name": "USB Audio CODEC",
    "music_device_name": "HDMI",  
    "music_channels": [1, 2],
    "transducer_channels": { ... }
}

```

**Execution Logic in C++:**

1. Read both device names during startup.
2. **If `transducer_device_name` == `music_device_name`:** Open **ONE** PortAudio stream. Inside `audioCallback`, mix the `libpd` audio directly alongside the transducer sine waves (current implementation).
3. **If `transducer_device_name` != `music_device_name`:** Open **TWO** separate PortAudio streams. The first callback handles only the `libpd` computation and outputs to HDMI. The second callback handles only the sine wave generators and outputs to the USB soundcard.

---

## 4. DSP Optimization: The 100ms Fixed Fade

**The Problem:** The current `applyPattern()` function implements a redundant string-based selection for fade speeds ("SLOW", "MEDIUM", "FAST"). Furthermore, snapping amplitudes instantly (0ms fade) causes "zero-crossing discontinuities" which physically manifest as loud, damaging pops/clicks on the transducers.

**The Solution:** Strip out the dead code and hardcode a DSP sweet spot.

* Delete the `fadeDurationMs` logic and the string arguments from `applyPattern`.
* Hardcode a fixed **100ms linear fade** when updating amplitudes.
* *Why 100ms?* It is mathematically long enough to prevent the speaker cone from snapping and causing a pop, but short enough that the visual transition of the sand and the LEDs appear instantaneous to the human eye, maintaining perfect musical synchronization.

---

## 5. Safety Critical Fix: Control-Rate Spam in `libpd`

**The Problem:** In `resonance_server.cpp`, the `pd_float_hook` executes inside the ultra-fast audio thread. If the PureData sequencer rapidly outputs the exact same note (or if it operates at audio-rate instead of control-rate), the hook will fire hundreds of times per second. This will instantly flood the Lock-Free Queue, causing the background worker thread to infinitely spam the Raspberry Pi Pico over USB-Serial, resulting in a microcontroller crash.

**The Solution:** Implement a strict State Filter to ensure the hardware is only notified of genuine state changes.

**Update `resonance_server.cpp` as follows:**

```cpp
// Add global/static tracker
static int current_playing_note = -1;

void pd_float_hook(const char *source, float value) {
    if (std::string(source) == "to_core") {
        int note = static_cast<int>(value);
        
        // SAFETY NET: Only execute if the note actually changed
        if (note != current_playing_note) {
            current_playing_note = note; 
            
            // 1. Update Transducers (Safe atomic update)
            if (musicNoteMap.count(note)) {
                std::string chladni_id = musicNoteMap[note];
                if (catalogue.count(chladni_id)) {
                    // ... (existing generator update logic) ...
                }
            }
            
            // 2. Queue LED update (Safe lock-free push)
            ledQueue.push(note % 20); 
        }
    }
}

```

---

## 6. Immediate Action Items for the C++ Team

1. **Remove `std::cin`:** Rewrite `selectAudioDevice()` to auto-connect based on substrings in `system_config.json`, including a 5-second retry fallback.
2. **Implement Dual-Stream Logic:** Update PortAudio initialization to handle separate Music and Transducer outputs if the config specifies two different device names.
3. **Optimize Fades:** Remove "SLOW/MEDIUM/FAST" logic from `audio_driver.cpp` and hardcode a single 100ms linear fade.
4. **Patch the Queue Spam:** Immediately add the `current_playing_note` state filter to `pd_float_hook` to protect the Raspberry Pi Pico from serial flooding.