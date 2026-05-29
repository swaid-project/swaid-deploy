import zmq
import json
import logging

# Configure logging - default to WARN to be quiet as a library
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("ResonanceSDK")

class ResonanceClient:
    """
    Python Client library for the SWAID Plate Resonance Core.
    Implements a robust REQ/REP pattern with automatic socket recovery.
    """
    def __init__(self, endpoint="ipc:///tmp/swaid.sock", context=None):
        """
        Initializes the Resonance Client.
        
        Args:
            endpoint (str): ZeroMQ endpoint to connect to.
            context (zmq.Context, optional): Existing ZeroMQ context to use.
        """
        self.endpoint = endpoint
        self.context = context or zmq.Context()
        self.socket = None
        self._setup_socket()

    def _setup_socket(self):
        """Initializes or resets the REQ socket to clear ZeroMQ state machine errors."""
        if self.socket:
            try:
                self.socket.close(linger=0)
            except:
                pass
        
        self.socket = self.context.socket(zmq.REQ)
        # Timeouts in milliseconds - ensures the library doesn't hang the caller
        self.socket.setsockopt(zmq.SNDTIMEO, 1000)
        self.socket.setsockopt(zmq.RCVTIMEO, 1000)
        self.socket.connect(self.endpoint)
        logger.debug(f"Connected to {self.endpoint}")

    def send_request(self, payload):
        """Internal helper to send JSON and wait for ACK.
        
        On ZeroMQ errors (like timeouts or state machine violations), 
        it automatically recreates the socket to maintain connectivity.
        """
        try:
            self.socket.send_json(payload)
            reply = self.socket.recv_json()
            return reply.get("status") in ["ok", "pong"]
        except zmq.ZMQError as e:
            logger.warning(f"ZMQ Error: {e}. Attempting socket recovery.")
            self._setup_socket()
            return False
        except Exception as e:
            logger.error(f"Unexpected error in SDK: {e}")
            return False

    def trigger_symbol(self, chladni_id, music_note=0, led_effect_id=0, vol_l=100, vol_r=100):
        """Triggers a specific Chladni pattern and associated hardware effects.
        
        Args:
            chladni_id (str): ID of the pattern to apply (e.g. 'CHLADNI_191').
            music_note (int): MIDI note to send to PureData.
            led_effect_id (int): ID of the LED effect to trigger.
            vol_l (int): Volume for left-side channels (0-100).
            vol_r (int): Volume for right-side channels (0-100).
        """
        payload = {
            "message_type": "trigger",
            "chladni_id": str(chladni_id),
            "music_note": int(music_note),
            "led_effect_id": int(led_effect_id),
            "vol_l": int(vol_l),
            "vol_r": int(vol_r)
        }
        return self.send_request(payload)

    def ping(self):
        """Sends a heartbeat ping to the Core to verify connectivity."""
        payload = {"message_type": "ping"}
        return self.send_request(payload)

    def music_enable(self, enabled):
        """Convenience wrapper to enable or disable audio output."""
        return self.master_control(music_enable=enabled)

    def manual_audio(self, channel, frequency_hz=None, amplitude=None, phase_deg=None):
        """Manually control a specific audio generator channel.
        
        Args:
            channel (int): Generator index (0-7).
            frequency_hz (float, optional): New frequency in Hertz.
            amplitude (float, optional): New amplitude (0.0-1.0).
            phase_deg (float, optional): Phase offset in degrees.
        """
        command = {"channel": int(channel)}
        if frequency_hz is not None:
            command["frequency_hz"] = float(frequency_hz)
        if amplitude is not None:
            command["amplitude"] = float(amplitude)
        if phase_deg is not None:
            command["phase_deg"] = float(phase_deg)
            
        payload = {
            "message_type": "manual_audio",
            "command": command
        }
        return self.send_request(payload)
        
    def manual_led(self, led_effect):
        """Manually trigger a specific LED effect (0-255)."""
        payload = {
            "message_type": "manual_led",
            "command": {
                "led_effect": int(led_effect)
            }
        }
        return self.send_request(payload)

    def master_control(self, music_enable=None, mute=None, reset=None):
        """Master controls for audio outputs and generators.
        
        Args:
            music_enable (bool, optional): Alias for not mute.
            mute (bool, optional): If True, silences all output.
            reset (bool, optional): If True, resets all generators to 440Hz/0Amp.
        """
        command = {}
        if music_enable is not None:
            command["music_enable"] = 1 if music_enable else 0
        if mute is not None:
            command["mute"] = bool(mute)
        if reset is not None:
            command["reset"] = bool(reset)
            
        payload = {
            "message_type": "master_control",
            "command": command
        }
        return self.send_request(payload)

if __name__ == "__main__":
    # Internal self-test
    logging.getLogger().setLevel(logging.INFO)
    client = ResonanceClient()
    print("SDK Library Self-Test...")
    if client.ping():
        print("[SUCCESS] Core is online.")
    else:
        print("[OFFLINE] Core not responding.")
