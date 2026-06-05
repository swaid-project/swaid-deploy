# Architectural Update Specification: Disabling Continuous Synchronization

**Version:** 8.1 (Feature Reversion & Toggle)
**Author:** Chief Software Engineer

**Target Audience:** Plate Resonance Team (C++)

**Date:** June 2026

## 1. Executive Summary

Following alignment with the Human-Interface team, the system behavior is being adjusted. The Chladni plate and LEDs should only react to the explicit `trigger` command sent by the UI. While the embedded `libpd` instance will continue to generate its autonomous musical sequence, the C++ Core will ignore the subsequent note changes rather than continuously synchronizing the physical hardware to them.

To preserve the engineering effort put into the continuous synchronization feature, **do not delete the code.** We will implement a compile-time toggle to disable the feedback loop and restore the direct hardware dispatch in the ZMQ listener.

---

## 2. Implementation Steps (`resonance_server.cpp`)

### **Step 1: Implement the Compile-Time Toggle**

At the top of `resonance_server.cpp` (below the includes), define a macro switch. This allows us to instantly reactivate the feature in the future by simply changing a `0` to a `1`.

```cpp
// Set to 1 to enable continuous hardware sync with PureData notes
// Set to 0 to only sync on the initial ZMQ trigger
#define CONTINUOUS_SYNC_ENABLED 0

```

### **Step 2: Bypass the PureData Hook**

Locate the `pd_float_hook` function. We will use the macro to compile out the execution logic. The hook will still technically be called by `libpd`, but it will instantly return without touching the atomic variables or the Lock-Free Queue.

```cpp
void pd_float_hook(const char *source, float value) {
#if CONTINUOUS_SYNC_ENABLED
    if (std::string(source) == "to_core") {
        int note = static_cast<int>(value);
        
        if (note != current_playing_note) {
            current_playing_note = note; 
            
            if (musicNoteMap.count(note)) {
                current_active_chladni = musicNoteMap[note]; 
                // ... (Existing transducer update logic) ...
            } else {
                current_active_chladni = "UNKNOWN";
            }
            
            ledQueue.push(note % 20); 
        }
    }
#endif
}

```

### **Step 3: Restore Direct Dispatch in the ZMQ Listener (CRITICAL)**

*Architectural Catch:* Because we previously relied on `pd_float_hook` to activate the transducers when a trigger was received, disabling the hook means the transducers will never turn on.

We must restore the explicit `applyPattern` and `ledQueue` calls inside the `jsonListenerThread` when a `"trigger"` command arrives.

```cpp
// Inside jsonListenerThread, when parsing a "trigger" command:

// 1. Seed the PureData sequencer (Remains unchanged)
libpd_float("from_core", music_note);

// 2. Direct Hardware Dispatch (Restored)
#if !CONTINUOUS_SYNC_ENABLED
    // Manually apply the Chladni pattern and LED effect immediately
    applyPattern(catalogue, chladni_id, "FAST"); // Utilizes the 100ms fade
    ledQueue.push(led_effect_id);
    
    // Freeze the active state to the triggered values
    current_playing_note = music_note;
    current_active_chladni = chladni_id;
#endif

```

### **Step 4: Freeze the "Piggybacked" State**

Because we wrapped the state updates in `#if !CONTINUOUS_SYNC_ENABLED`, the variables `current_playing_note` and `current_active_chladni` will now simply hold the values of the *last triggered symbol*.

You do **not** need to comment out the JSON injection logic for the ZMQ replies.

```cpp
// Leave this exactly as it is. It will now safely report the static triggered state.
reply["active_state"]["current_note"] = current_playing_note;
reply["active_state"]["current_chladni_id"] = current_active_chladni;

```

---

## 3. Impact Analysis

* **C++ Core:** The audio thread is now even lighter, as it no longer updates transducer variables during playback. The Pico serial thread will only be invoked once per user interaction.
* **Human-Interface:** The UI team can safely revert their high-frequency (20Hz) polling. They can return to the standard 1Hz heartbeat, as they no longer need to watch for spontaneous Chladni ID changes from the server.
