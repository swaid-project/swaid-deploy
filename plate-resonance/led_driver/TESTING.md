# Testing the Parallel Audio + LED System

## Overview

The `rx_driver.cpp` now controls both **audio patterns** (via PortAudio) and **LED effects** (via USB serial to Raspberry Pi Pico) in **parallel** when a ZeroMQ trigger is received.

Each Chladni symbol in the catalogue is hard-mapped to a specific LED effect (0-19) in `rx_driver.cpp`. When a ZeroMQ trigger arrives:
1. The audio pattern fades in over the specified transition time
2. Simultaneously, `R` or `L` serial commands are sent to the Pico to navigate to the mapped LED effect

---

## Hardware Setup

1. **Raspberry Pi Pico** with `leds_pico_v3.ino` flashed
2. **USB cable** connecting Pico to the PC running `rx_driver`
3. **NeoPixel strip** (180 LEDs) connected to Pico GPIO 15
4. **Audio interface** with at least 4 output channels (Front L, Front R, Rear L, Rear R)

### Flashing the Pico

#### Option A: PlatformIO (VS Code) — Recommended
```bash
cd src/LEDs\ Control
# Open this folder in VS Code with PlatformIO extension
# Build: Ctrl+Alt+B
# Upload: Ctrl+Alt+U
```

#### Option B: Arduino IDE
Open `src/LEDs Control/leds_pico_v3/leds_pico_v3.ino` in Arduino IDE, select **Raspberry Pi Pico** board, and upload.

---

## Symbol to LED Effect Mapping

| Symbol | LED Effect ID | LED Effect Name |
|--------|---------------|-----------------|
| CHLADNI_CROSS | 0 | Arco-Iris Fluido |
| CHLADNI_STAR_4 | 10 | Explosao de Estrela |
| CHLADNI_RING | 3 | Respiracao Oceano |
| CHLADNI_DIAGONAL | 7 | Scanner Duplo |
| CHLADNI_GRID_2x2 | 14 | Matrix |
| CHLADNI_STAR_8 | 4 | Aurora Boreal |
| CHLADNI_SPIRAL | 9 | Serpente Cromatica |
| CHLADNI_FLOWER_6 | 5 | Cometa Arco-Iris |
| CHLADNI_BUTTERFLY | 8 | Vagalumes |
| CHLADNI_MANDALA | 17 | Galaxia |
| CHLADNI_TORUS_KNOT | 6 | Plasma Quantico |

---

## Build

```bash
cd src/soundcard/driver
make
```

No new libraries are required — POSIX serial APIs (`termios`, `fcntl`) are built into Linux.

---

## Test Procedure

### 1. Connect the Pico

- Plug the Raspberry Pi Pico into USB
- Verify it appears as a serial device:
  ```bash
  ls /dev/ttyACM0
  # or
  ls /dev/serial/by-id/
  ```

### 2. Start the Receiver

```bash
cd src/soundcard/driver
./rx_driver
```

- Select your audio device when prompted
- Choose **TUI** mode (`2`) for easier console output monitoring
- Enable the JSON listener:
  ```
  > json on
  ```

You should see:
```
[LED Serial] Connected to Pico (fd=...)
ZeroMQ listener ready - listening on ipc:///tmp/swaid.sock
```

If the Pico is not connected, you will see a warning but audio will still work:
```
[LED Serial] Pico not found on any known serial port.
```

### 3a. Test LEDs Directly (No Audio)

To test the Pico LED effects independently of the audio system, use the direct serial tester:

```bash
cd src/soundcard/driver/test_files
python3 test_pico_led.py
```

```
===== Teste Direto Pico LEDs =====
<número>  → Envia FX:<número> (0–19)
r         → Efeito aleatório
s         → Mostrar lista de efeitos
q         → Sair
Escolha: 10
→ Enviado: FX:10 — Explosão de Estrela
```

This sends `FX:10\n` directly to the Pico via USB serial. The Pico will immediately start a fade transition to effect 10. This is useful for quickly testing individual LED effects without triggering audio.

### 3b. Send Test Triggers (Audio + LED together)

In a **second terminal**, run the main testbench:

```bash
cd src/soundcard/driver/test_files
python3 test_hi.py
```

#### Manual trigger:
```
===== HI Sender Menu =====
1) Enviar pacote manual
...
Escolha: 1
  symbol [CHLADNI_CROSS]: CHLADNI_RING
  transition [MEDIUM]:
  ...
```

#### Random triggers:
```
Escolha: 2
```

#### Batch random triggers:
```
Escolha: 3
Numero de pacotes: 5
Delay minimo (s) [default 0.2]: 1
Delay maximo (s) [default 1.0]: 2
```

### 4. Observe Parallel Output

In the `rx_driver` terminal you should see **both** audio and LED activity:

```
Parsed symbol: CHLADNI_RING
Applying: CHLADNI_RING | Fade: MEDIUM (300ms)
[LED Serial] Arrived at effect 3
```

- **Audio**: The 4 transducer channels should fade to the ring pattern frequencies
- **LEDs**: The NeoPixel strip should fade through transitions until reaching effect 3 (Respiracao Oceano)

### 5. Verify LED Navigation Timing

The Pico receives a direct `FX:<num>` command and performs a single fade transition (~700ms) to the target effect.

Example: switching from effect 0 to effect 10:
- One `FX:10` command sent
- **~700ms total** for the fade transition
- The built-in LED blinks **once**
- No intermediate effects are shown

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `[LED Serial] Pico not found` | Pico not plugged in or wrong port | Check `ls /dev/ttyACM*`, ensure Pico is connected |
| LEDs not changing | Serial port busy or wrong baud rate | Close `controlador_pc_v2.py` if running; verify Pico runs at 9600 baud |
| LEDs skip effects | Invalid FX command | Check Pico serial output for `err:FX:out_of_range` |
| Audio works but no LEDs | `json on` not enabled | Type `json on` in rx_driver TUI |
| Compile error `termios` | Missing headers | Install `build-essential`: `sudo apt install build-essential` |

---

## Debug with Deprecated Keyboard Controller

For manual LED testing without ZeroMQ, the old keyboard controller still works:

```bash
cd src/embedded_sw/LEDs\ Control
python3 controlador_pc_v2.py
```

> **Note:** This is deprecated. `rx_driver.cpp` will take over LED control when `json on` is active. Do not run both simultaneously — they will conflict over the serial port.
