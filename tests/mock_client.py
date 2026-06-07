import zmq
import json
import threading
import time
import sys

# Connect to the ZMQ IPC socket
context = zmq.Context()
socket = context.socket(zmq.REQ)
# Configure timeout so the socket doesn't block forever if the server dies
socket.setsockopt(zmq.RCVTIMEO, 2000)
socket.connect("ipc:///tmp/swaid.sock")

heartbeat_active = True

def send_request(msg_dict):
    global socket
    try:
        socket.send_json(msg_dict)
        reply = socket.recv_json()
        if msg_dict.get("message_type") != "ping":
            print(f"\n[SERVER REP] {json.dumps(reply, indent=2)}")
    except zmq.error.Again:
        print("\n[ZMQ TIMEOUT] Server did not respond within 2 seconds!")
        # REQ sockets are stuck after a timeout unless re-created
        socket.close()
        socket = context.socket(zmq.REQ)
        socket.setsockopt(zmq.RCVTIMEO, 2000)
        socket.connect("ipc:///tmp/swaid.sock")

def heartbeat_thread():
    while True:
        if heartbeat_active:
            send_request({"message_type": "ping"})
        time.sleep(0.1)  # 10Hz heartbeat

def cli_thread():
    global heartbeat_active
    print("Mockup Client CLI.")
    print("Commands:")
    print("  trigger <note>   - Sends a trigger with the specified note (e.g. trigger 4)")
    print("  shuffle          - Sends a shuffle command")
    print("  mute             - Sends a channel_state command to mute music & transducers")
    print("  unmute           - Sends a channel_state command to unmute music & transducers")
    print("  toggle_heartbeat - Stops/Starts the 10Hz ping (simulate dead client)")
    print("  exit             - Exits the client")

    while True:
        try:
            cmd = input("client> ").strip().lower()
            if cmd.startswith("trigger"):
                parts = cmd.split()
                if len(parts) == 2 and parts[1].isdigit():
                    send_request({"message_type": "trigger", "music_note": int(parts[1])})
                else:
                    print("Usage: trigger <note>")
            elif cmd == "shuffle":
                send_request({"message_type": "shuffle"})
            elif cmd == "mute":
                send_request({
                    "message_type": "channel_state",
                    "command": {
                        "music_mute": True,
                        "transducer_mute": True
                    }
                })
            elif cmd == "unmute":
                send_request({
                    "message_type": "channel_state",
                    "command": {
                        "music_mute": False,
                        "transducer_mute": False
                    }
                })
            elif cmd == "toggle_heartbeat":
                heartbeat_active = not heartbeat_active
                print(f"[STATE] Heartbeat active: {heartbeat_active}")
            elif cmd == "exit":
                print("Exiting...")
                sys.exit(0)
            elif cmd != "":
                print("Unknown command.")
        except EOFError:
            break

if __name__ == "__main__":
    t = threading.Thread(target=heartbeat_thread, daemon=True)
    t.start()
    cli_thread()
