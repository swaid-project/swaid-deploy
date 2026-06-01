# PureData Component (Legacy UDP)

Legacy communication utilities for the SWAID system.

## Status: ⚠️ Legacy / Debug Only
As of Version 6.0, PureData is **embedded directly** into the C++ Core via `libpd`. 

This directory is no longer part of the production execution path. It is maintained solely as a **Standalone Debug Tool** for the Music Synthesis team to verify `.pd` patches in an external PureData instance without running the full C++ backend.

## Features
- **`puredata_cli`**: A small C++ utility that fires a UDP packet to `127.0.0.1:3000`.
- **FUDI Protocol**: Implements the `note;\n` string format.

## contents
- `src/main.cpp`: Standalone CLI source.
- `src/puredata_sender.cpp`: Raw UDP socket implementation.
