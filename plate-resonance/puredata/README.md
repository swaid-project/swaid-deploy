# PureData UDP Transmitter Component

An active production library designed for communicating with an external PureData musical synthesis engine from the C++ Core.

---

## Role

Rather than generating music natively in C++, the SWAID server delegates sound synthesis to an external PureData patch. This component builds a static library (`puredata`) that implements UDP message sockets to send note and mute/enable packets.

---

## Protocol Specifications

### Note Triggers (Port 3000)
Notes are sent via the **FUDI Protocol** as a string terminated by a semicolon and newline:
`[note_id];\n`
For example, triggering note 2 sends `2;\n`.

### Music Enable / Mute (Port 3001)
Used to toggle the audio generation of the PureData patch. Unlike note triggers, this is message-sensitive:
- Sending `1;\n` enables the audio output.
- Sending `0;\n` (or any value other than 1) disables/mutes the audio output.

---

## Startup and Recovery Behavior

1. **Initial Boot**: The server automatically initializes the PureData stream to disabled on startup by transmitting `0` to port 3001.
2. **First Trigger**: Upon receiving the first ZMQ note trigger, the server sends `1` to port 3001 to activate synthesis.
3. **Heartbeat Timeout**: If the ZMQ client disconnects or times out for more than 2 seconds, the server automatically transmits `0` to port 3001 to mute the patch.
4. **Reconnect**: When the client reconnects, the music remains muted until a new trigger command is received.

---

## File Contents

- `include/puredata_sender.hpp`: Declares `PureDataSender` class.
- `src/puredata_sender.cpp`: Implementations of socket creation, address routing, and `sendto()` packet delivery.
- `src/main.cpp`: Standalone command line utility (`puredata_cli`) used for testing PureData triggers directly from a terminal.
