# Resonance Core

The central hub and primary service of the SWAID Plate Resonance project.

## Role
The `resonance_core` is a high-priority C++ application that orchestrates real-time audio, generative music, and hardware feedback. It is the only component that talks directly to the hardware.

## Key Features

- **Embedded `libpd`**: Executes PureData patches (`file1.pd`) natively. No network lag; frame-accurate feedback.
- **ZeroMQ Server**: REQ/REP server listening on IPC (`/tmp/swaid.sock`). Provides hardware diagnostics and active state in every reply.
- **Three-Tier Threading**:
    - **Thread 1 (ZMQ)**: Asynchronous command parsing and atomic state updates.
    - **Thread 2 (Audio)**: Sacred real-time DSP context. 20Hz health monitoring.
    - **Thread 3 (Hardware)**: Dedicated loop for USB-Serial I/O with auto-recovery for the RPi Pico.
- **System Watchdog**: The main thread autonomously monitors PortAudio streams. If a USB Soundcard is removed, it automatically nukes the context and retries discovery every 5 seconds.
- **State Piggybacking**: Exposes what the generative musical brain is doing (`current_note`, `current_chladni_id`) so the UI can sync its animations.

## Contents
- `src/main.cpp`: The System Watchdog and boot orchestrator.
- `src/resonance_server.cpp`: ZMQ Listener and `libpd` hook implementation.
- `include/lock_free_queue.hpp`: SPSC queue for thread-safe LED dispatch.

## Dependencies
Linked against: `libpd_static`, `portaudio`, `soundcard`, `led_driver`, `cppzmq`.
