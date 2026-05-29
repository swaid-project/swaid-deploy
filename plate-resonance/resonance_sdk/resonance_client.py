import zmq
import json
import time

class ResonanceClient:
    """
    Python Client for the SWAID Plate Resonance Core.
    Implements the REQ/REP pattern as per May 2026 Architectural Update.
    """
    def __init__(self, endpoint="ipc:///tmp/swaid.sock"):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        # Timeouts in milliseconds
        self.socket.setsockopt(zmq.SNDTIMEO, 1000)
        self.socket.setsockopt(zmq.RCVTIMEO, 1000)
        self.socket.connect(endpoint)
        print(f"[Python SDK] Connected to {endpoint}")

    def send_request(self, payload):
        """Internal helper to send JSON and wait for ACK."""
        try:
            self.socket.send_json(payload)
            reply = self.socket.recv_json()
            return reply.get("status") in ["ok", "pong"]
        except zmq.ZMQError as e:
            print(f"[Python SDK] ZMQ Error: {e}")
            # In case of timeout or error, we might need to recreate the socket 
            # for REQ/REP state machine to reset, but simple return False for now.
            return False

    def trigger_symbol(self, chladni_id, music_note=0, led_effect_id=0, vol_l=1.0, vol_r=1.0):
        """Triggers a specific Chladni pattern and associated hardware effects."""
        payload = {
            "message_type": "trigger",
            "chladni_id": chladni_id,
            "music_note": music_note,
            "led_effect_id": led_effect_id,
            "L_volume": vol_l,
            "R_volume": vol_r
        }
        return self.send_request(payload)

    def ping(self):
        """Sends a heartbeat ping to the Core."""
        payload = {"message_type": "ping"}
        return self.send_request(payload)

    def set_music_enable(self, enabled):
        """Enables or disables audio output."""
        payload = {
            "message_type": "master_control",
            "command": {
                "music_enable": 1 if enabled else 0
            }
        }
        return self.send_request(payload)

    def mute(self, is_muted=True):
        """Mutes or unmutes the master output."""
        payload = {
            "message_type": "master_control",
            "command": {
                "mute": is_muted
            }
        }
        return self.send_request(payload)

if __name__ == "__main__":
    # Example usage / Heartbeat simulation
    client = ResonanceClient()
    print("Sending ping...")
    if client.ping():
        print("ACK: Core is online.")
        print("Sending test trigger...")
        client.trigger_symbol("CHLADNI_191", music_note=60, led_effect_id=1)
    else:
        print("NACK: Core offline or timeout.")
