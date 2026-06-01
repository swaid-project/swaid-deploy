# LED Driver (Embedded SAL)

Resilient Serial bridge for the SWAID visual feedback system.

## Role
Manages USB-Serial communication between the C++ Core and the Raspberry Pi Pico driving the NeoPixel strip.

## Features

- **Asynchronous Execution**: Designed to be called by a background worker thread (`Thread 3`) to ensure Serial latency never blocks the audio engine.
- **Self-Healing Loop**: If the USB cable is bumped or the Pico resets, the driver detects the `write()` failure, closes the port, and infinitely polls for a new link every 2 seconds.
- **Auto-Discovery**: Scans `/dev/ttyACM*` and `/dev/ttyUSB*` automatically.
- **FUDI-Lite Protocol**: ASCII based. Sends `FX:<id>\n`.

## Pico Firmware
The `src/*.ino` files contain the Arduino-based firmware for the Pico. It implements:
- Smooth cross-fading between effects.
- **Perceptual Gamma Correction**: Ensures LED brightness appears linear to the human eye.

## contents
- `include/embedded_sal.hpp`: Class definition with error trapping.
- `src/embedded_sal.cpp`: Resilient I/O implementation.
- `test/test_pico_led.py`: Direct debug utility.
