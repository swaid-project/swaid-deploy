import sys
import os
import time

# Add parent directory to path so we can import resonance_client
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resonance_client import ResonanceClient

def test_manual():
    client = ResonanceClient(endpoint="ipc:///tmp/swaid.sock")
    
    print("--- Resonance SDK Python Test ---")
    
    print("1. Ping...")
    if client.ping():
        print("Success: Core is online.")
    else:
        print("Failure: Core offline or timeout.")

    print("\n2. Trigger Symbol (CHLADNI_191) with custom volumes...")
    # Standardized vol_l and vol_r as integers (0-100)
    if client.trigger_symbol("CHLADNI_191", music_note=60, led_effect_id=1, vol_l=80, vol_r=20):
        print("Success: Trigger sent.")
    else:
        print("Failure: Trigger failed.")

    print("\n3. Manual Audio...")
    # Updated to match resonance_client.py parameter names
    if client.manual_audio(channel=0, frequency_hz=440.0, amplitude=0.5, phase_deg=0.0):
        print("Success: Manual audio sent.")
    else:
        print("Failure: Manual audio failed.")

    print("\n4. Manual LED...")
    if client.manual_led(led_effect=2):
        print("Success: Manual LED sent.")
    else:
        print("Failure: Manual LED failed.")

    print("\n5. Master Control (Mute)...")
    if client.master_control(mute=True):
        print("Success: Mute sent.")
    else:
        print("Failure: Mute failed.")

    print("\n6. Master Control (Reset)...")
    if client.master_control(reset=True):
        print("Success: Reset sent.")
    else:
        print("Failure: Reset failed.")

    print("\n7. Music Enable (Wrapper test)...")
    if client.music_enable(True):
        print("Success: Music enabled.")
    else:
        print("Failure: Music enable failed.")

if __name__ == "__main__":
    test_manual()
