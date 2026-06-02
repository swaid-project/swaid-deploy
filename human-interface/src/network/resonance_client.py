import zmq
import json
import threading
import queue
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ResonanceClient")

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
        self.diagnostics = {"pico_serial": 0, "usb_audio": 0, "hdmi_audio": 0}
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
                socket.send_json(payload)
                response = socket.recv_json()

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
                self.diagnostics = {"pico_serial": 0, "usb_audio": 0, "hdmi_audio": 0}

                # Rebuild socket to break the REQ/REP state machine deadlock
                socket.close()
                socket = self._create_socket()
            
            except Exception as e:
                logger.error(f"Unexpected network error: {e}")
                self.is_connected = False
                time.sleep(1.0) # Back off on major errors

            # Maintain ~20Hz loop (50ms)
            time.sleep(0.05)

        socket.close()

    # --- Public API for the UI (Non-blocking) ---

    def trigger(self, chladni_id: str, music_note: int, led_effect: int, vol_l: int = 100, vol_r: int = 100):
        """Enqueues a trigger command for the physical and musical state."""
        self._command_queue.put({
            "message_type": "trigger",
            "chladni_id": str(chladni_id),
            "music_note": int(music_note),
            "led_effect_id": int(led_effect),
            "vol_l": int(vol_l),
            "vol_r": int(vol_r)
        })

    def set_channel_state(self, transducer_mute: bool = None, music_mute: bool = None):
        """Enqueues a mute/unmute command for specific audio logical groups."""
        cmd = {}
        if transducer_mute is not None:
            cmd["transducer_mute"] = bool(transducer_mute)
        if music_mute is not None:
            cmd["music_mute"] = bool(music_mute)
            
        if cmd:
            self._command_queue.put({
                "message_type": "channel_state",
                "command": cmd
            })

    def manual_audio(self, channel: int, frequency_hz: float = None, amplitude: float = None, phase_deg: float = None):
        """
        Enqueues a manual audio generator override.
        channel: 0-7 (physical transducer index)
        """
        cmd = {"channel": int(channel)}
        if frequency_hz is not None:
            cmd["frequency_hz"] = float(frequency_hz)
        if amplitude is not None:
            cmd["amplitude"] = float(amplitude)
        if phase_deg is not None:
            cmd["phase_deg"] = float(phase_deg)

        self._command_queue.put({
            "message_type": "manual_audio",
            "command": cmd
        })

    def manual_led(self, led_effect_id: int):
        """Enqueues a manual LED effect override."""
        self._command_queue.put({
            "message_type": "manual_led",
            "command": {"led_effect": int(led_effect_id)}
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
