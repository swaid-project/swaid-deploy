import zmq
import json
import threading
import queue
import time
import logging
import uuid

# Configure logging
logger = logging.getLogger("ResonanceClient")
logger.setLevel(logging.DEBUG)
logger.propagate = False  # prevent double output via root logger

file_handler = logging.FileHandler("client_ipc.log")
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('[Python UI] %(levelname)s: %(message)s'))
logger.addHandler(console_handler)

class ResonanceClient:
    """
    Native Python Client for the SWAID Plate Resonance Core.
    Implements a thread-safe Command Queue Pattern with background polling (20Hz).
    """
    def __init__(self, endpoint="ipc:///tmp/swaid.sock"):
        self.endpoint = endpoint
        self.context = zmq.Context()

        # Thread-Safe Command Queue
        self._command_queue = queue.Queue()

        # Cached State (Read by the UI)
        # Defaults reflect a "disconnected" or "unknown" state
        self.diagnostics = {
            "pico_serial": 0, 
            "usb_audio": 0, 
            "UDP_connection": 0,
            "music_state": 0,
            "transducer_state": 0
        }
        self.active_state = {"current_note": -1, "current_chladni_id": "NONE"}
        self.is_connected = False

        # Worker Thread
        self._running = True
        self._worker_thread = threading.Thread(target=self._network_loop, daemon=True)
        self._worker_thread.start()
        logger.info(f"ResonanceClient initialized. Connecting to {endpoint}")

    def _create_socket(self):
        """Creates a fresh REQ socket with safety timeouts."""
        socket = self.context.socket(zmq.REQ)
        socket.setsockopt(zmq.RCVTIMEO, 200) # 200ms timeout for responsiveness
        socket.setsockopt(zmq.SNDTIMEO, 200)
        socket.setsockopt(zmq.LINGER, 0)
        try:
            socket.connect(self.endpoint)
        except Exception as e:
            logger.error(f"Socket connect failed: {e}")
        return socket

    def _network_loop(self):
        """Background thread loop: handles all ZMQ I/O."""
        socket = self._create_socket()

        while self._running:
            # 1. Determine payload (Command from queue vs Heartbeat Ping)
            try:
                payload = self._command_queue.get_nowait()
            except queue.Empty:
                payload = {"message_type": "ping"}

            # 2. Network I/O with Timeout Safety
            try:
                # --- Deep Diagnostic Logging (Ignoring Pings) ---
                if payload.get("message_type") != "ping":
                    logger.debug(f"TX -> {json.dumps(payload)}")

                socket.send_json(payload)
                response = socket.recv_json()

                if payload.get("message_type") != "ping":
                    logger.debug(f"RX <- {json.dumps(response)}")

                # 3. Update Cached State (Piggybacking)
                if isinstance(response, dict):
                    if "diagnostics" in response:
                        self.diagnostics = response["diagnostics"]
                    if "active_state" in response:
                        self.active_state = response["active_state"]
                    
                    self.is_connected = True
                else:
                    self.is_connected = False

            except zmq.error.Again:
                # TIMEOUT: Server is offline or crashed
                if self.is_connected:
                    logger.warning("Server connection timed out.")
                self.is_connected = False
                # Zero out diagnostics to trigger UI warnings
                self.diagnostics = {
                    "pico_serial": 0, 
                    "usb_audio": 0, 
                    "UDP_connection": 0,
                    "music_state": 0,
                    "transducer_state": 0
                }

                # Rebuild socket to break the REQ/REP state machine deadlock
                socket.close()
                socket = self._create_socket()
            
            except Exception as e:
                logger.error(f"Unexpected network error: {e}")
                self.is_connected = False
                time.sleep(1.0) # Back off on major errors

            # Maintain 10Hz loop (100ms)
            time.sleep(0.1)

        socket.close()

    # --- Public API for the UI (Non-blocking) ---

    def trigger(self, music_note: int):
        """Enqueues a trigger command for the physical and musical state."""
        self._command_queue.put({
            "trace_id": f"req-{uuid.uuid4().hex[:8]}",
            "message_type": "trigger",
            "music_note": int(music_note)
        })

    def shuffle(self):
        """Enqueues a shuffle command to clear the plate."""
        self._command_queue.put({
            "trace_id": f"req-{uuid.uuid4().hex[:8]}",
            "message_type": "shuffle"
        })


    def stop(self):
        """Gracefully shuts down the background network thread."""
        self._running = False
        if self._worker_thread.is_alive():
            self._worker_thread.join()
        self.context.term()

if __name__ == "__main__":
    # Test script
    client = ResonanceClient()
    print("ResonanceClient Polling Test (Ctrl+C to stop)...")
    try:
        while True:
            status = "ONLINE" if client.is_connected else "OFFLINE"
            print(f"[{status}] Diags: {client.diagnostics} | State: {client.active_state}", end="\r")
            time.sleep(0.5)
    except KeyboardInterrupt:
        client.stop()
        print("\nStopped.")
