# Soundcard Driver Component

Real-time audio processing and dynamic channel routing for SWAID transducer vibrations.

---

## Role

This component implements the hardware-level PortAudio interface. It creates high-precision sine waves dynamically based on the frequencies, amplitudes, and phase parameters defined in `master_symbols.json`.

---

## Key Features

- **PortAudio Stream Management**: Resolves and opens outputs for the target USB Soundcard matching the name substring specified in `system_config.json`.
- **Interpolated ASR Envelopes**: Integrates dynamic 100ms fade-in/fade-out linear amplitude interpolation. Ramping prevent mechanical coil shock to the transducers and eliminates zero-crossing audio pops.
- **Dynamic Configuration Mapping**: Connects logical transducers (1 to 4) dynamically to their corresponding physical channels on the soundcard as configured in the system variables.
- **Safety Bounds Verification**: Verifies physical device limits (available output channels) before starting streams, preventing segmentation faults or buffer issues if channel assignments exceed device capacity.

---

## Execution Threading

The driver runs inside PortAudio's high-priority real-time audio thread:
- **`transducerCallback`**: Active execution loop. It reads atomic amplitude target variables and timestamps, calculates current sample values, and updates the soundcard output buffer.
- *Performance Rule*: Never triggers memory allocations, console prints (`std::cout`), or blocking operations inside this callback to avoid buffer underruns.

---

## Configuration

Settings are parsed from `system_config.json`:
- `transducer_device_name`: Name substring of target audio card.
- `sample_rate`: e.g., 44100 or 48000.
- `transducer_channels`: Maps logical transducer IDs to physical soundcard output indexes.
