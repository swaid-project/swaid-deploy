# Resonance SDK (Python)

Welcome to the **Resonance SDK**. This library serves as the official bridge between **Team HI** (Python Frontend) and **Our Team** (C++ Core Plate Drivers).

## What Does This Do?
Team HI works in Python, and this SDK provides a native Python client to communicate with the Chladni hardware drivers. 

It handles networking via ZeroMQ and JSON formatting, implementing the REQ/REP pattern required by the Resonance Core.

### The Workflow
1.  **Team HI (Python):** Uses the `ResonanceClient` class.
2.  **SDK (Python):** Wraps requests into JSON and manages the ZeroMQ state machine.
3.  **ZeroMQ (Network):** Pushes the payload over the local network (typically IPC) to the physical hardware receiver.

---

## Setup
Ensure you have `pyzmq` installed:

```bash
pip install pyzmq
```

---

## How to Use (For Team HI)

Team HI can simply import the `ResonanceClient` from `resonance_client.py`.

### Python Integration Example

```python
from resonance_client import ResonanceClient

# 1. Initialize the client
client = ResonanceClient(endpoint="ipc:///tmp/swaid.sock")

# 2. Trigger a symbol
# chladni_id: The ID of the pattern to display (e.g., "CHLADNI_191")
# music_note: MIDI note number
# led_effect_id: ID of the LED effect to trigger
# vol_l, vol_r: Volume for Left and Right channels (0.0 to 1.0)
success = client.trigger_symbol(
    chladni_id="CHLADNI_191",
    music_note=60,
    led_effect_id=1,
    vol_l=0.8,
    vol_r=0.8
)

if success:
    print("Command accepted by Core.")
else:
    print("Failed to send command or timeout.")

# 3. Ping the core
if client.ping():
    print("Core is online.")
```

## File Breakdown
*   **`resonance_client.py`**: The main Python implementation of the SDK.
