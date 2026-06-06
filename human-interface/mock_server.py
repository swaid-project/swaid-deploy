import zmq
import json
import threading
import sys
import time
import os

# Mock Server State
diagnostics = {
    "pico_serial": 1,
    "usb_audio": 1,
    "UDP_connection": 1,
    "music_state": 1,
    "transducer_state": 1
}

active_state = {
    "current_note": -1,
    "current_chladni_id": "NONE",
    "led_effect_id": -1
}

master_symbols = {}
freeze_server = False

def load_master_symbols():
    global master_symbols
    try:
        # Expected to be run from human-interface directory
        path = "../master_symbols.json"
        if not os.path.exists(path):
            path = "master_symbols.json" # Fallback if run from root
            
        with open(path, "r") as f:
            symbols = json.load(f)
            for symbol in symbols:
                if "music_note" in symbol:
                    master_symbols[symbol["music_note"]] = symbol
        print(f"[INIT] Loaded master_symbols.json successfully from {path}.")
    except Exception as e:
        print(f"[ERROR] Failed to load master_symbols.json: {e}")

def get_server_response():
    return {
        "status": "ok",
        "diagnostics": diagnostics,
        "active_state": active_state
    }

def zmq_thread():
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.bind("ipc:///tmp/swaid.sock")
    print("[ZMQ] Listening on ipc:///tmp/swaid.sock")

    while True:
        try:
            message = socket.recv_json()
            msg_type = message.get("message_type")
            
            if msg_type != "ping":
                print(f"\n[CLIENT REQ] {json.dumps(message)}")
            
            if freeze_server:
                if msg_type != "ping":
                    print("[ZMQ] Server frozen. Blocking request (will cause client timeout).")
                while freeze_server:
                    time.sleep(0.1)
                # Must send a reply to reset the ZMQ REP socket state machine,
                # even if the client has already timed out and disconnected.
                socket.send_json(get_server_response())
                continue

            if msg_type == "trigger":
                note = message.get("music_note", -1)
                symbol = master_symbols.get(note)
                if symbol:
                    active_state["current_note"] = note
                    active_state["current_chladni_id"] = symbol.get("display_name", "UNKNOWN")
                    active_state["led_effect_id"] = symbol.get("LED_effect", -1)
                    diagnostics["music_state"] = 1
            elif msg_type == "channel_state":
                cmd = message.get("command", {})
                if "music_state" in cmd:
                    diagnostics["music_state"] = 1 if cmd["music_state"] else 0
                if "transducer_state" in cmd:
                    diagnostics["transducer_state"] = 1 if cmd["transducer_state"] else 0
            
            response = get_server_response()
            socket.send_json(response)
        except zmq.ZMQError as e:
            print(f"[ZMQ ERROR] {e}")
            time.sleep(1)

def cli_thread():
    global freeze_server
    print("\nMockup Server CLI. Available commands:")
    print("  toggle_pico, toggle_usb, toggle_udp, toggle_music")
    print("  freeze, reset, exit\n")

    while True:
        try:
            cmd = input("mock> ").strip().lower()
            if cmd == "toggle_pico":
                diagnostics["pico_serial"] = 1 if diagnostics["pico_serial"] == 0 else 0
                print(f"[STATE] pico_serial -> {diagnostics['pico_serial']}")
            elif cmd == "toggle_usb":
                diagnostics["usb_audio"] = 1 if diagnostics["usb_audio"] == 0 else 0
                print(f"[STATE] usb_audio -> {diagnostics['usb_audio']}")
            elif cmd == "toggle_udp":
                diagnostics["UDP_connection"] = 1 if diagnostics["UDP_connection"] == 0 else 0
                print(f"[STATE] UDP_connection -> {diagnostics['UDP_connection']}")
            elif cmd == "toggle_music":
                diagnostics["music_state"] = 1 if diagnostics["music_state"] == 0 else 0
                print(f"[STATE] music_state -> {diagnostics['music_state']}")
            elif cmd == "freeze":
                freeze_server = not freeze_server
                print(f"[STATE] freeze -> {freeze_server}")
            elif cmd == "reset":
                for k in diagnostics.keys():
                    diagnostics[k] = 1
                freeze_server = False
                print("[STATE] All diagnostics reset to 1. Server unfrozen.")
            elif cmd == "exit":
                print("Exiting...")
                os._exit(0)
            elif cmd != "":
                print("Unknown command. Try: toggle_pico, toggle_usb, toggle_udp, toggle_music, freeze, reset, exit")
        except EOFError:
            break

if __name__ == "__main__":
    load_master_symbols()
    
    t_zmq = threading.Thread(target=zmq_thread, daemon=True)
    t_zmq.start()
    
    cli_thread()
