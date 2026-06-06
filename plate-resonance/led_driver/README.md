# LED Driver (Embedded SAL)

A resilient serial communication bridge designed for controlling NeoPixel visual feedback from the C++ Core.

---

## Role

The C++ Core uses `EmbeddedSAL` to manage serial communication with a Raspberry Pi Pico acting as the LED strip controller. The driver offloads all serial operations to a background thread to guarantee that potential serial blocking doesn't interrupt time-critical DSP.

---

## Features

- **Asynchronous Dispatching**: LED commands are pushed to a thread-safe SPSC (Single Producer Single Consumer) queue, keeping the main ZeroMQ thread responsive.
- **Robust Self-Healing**: Detects device extraction, write timeouts, and interface disconnects. Automatically terminates the active descriptor and polls for a new serial interface `/dev/ttyACM*` or `/dev/ttyUSB*` every 2 seconds.
- **FUDI-Lite Protocol**: Sends simple ASCII packets: `FX:<id>\n`.
- **Hardware Agnostic**: Employs standard Unix serial terminal configurations (`termios`) matching 9600 baud, 8N1.

---

## Pico Firmware

Arduino-compatible firmware sources for the Raspberry Pi Pico are located in the `src/` folder:
- **Cross-Fading**: Includes smooth linear transitions between active LED effects.
- **Gamma Correction**: Uses perceptual gamma curves to ensure linear LED intensity.

---

## File Contents

- `include/embedded_sal.hpp`: Driver interface declaration and config state.
- `src/embedded_sal.cpp`: Serial file-descriptor reading/writing and recovery loop implementation.
- `test/test_pico_led.py`: Python utility to test raw command output directly to the hardware.
