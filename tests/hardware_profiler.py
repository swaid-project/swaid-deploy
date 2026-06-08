import socket
import json
import time
import argparse
import sys
import os

try:
    import serial
except ImportError:
    print("Warning: 'pyserial' not installed. Microcontroller mode will fail. Run: pip install pyserial")

try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    print("Warning: 'sounddevice' or 'numpy' not installed. Soundcard mode will fail. Run: pip install sounddevice numpy")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../json_config/system_config.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def test_puredata():
    config = load_config()
    ip = "127.0.0.1"
    port = config["communication"].get("pd_udp_port", 3000)
    
    print(f"--- PureData Mode ---")
    print(f"Target: UDP {ip}:{port}")
    note = input("Enter note ID to send (e.g., 2) or 'q' to quit: ")
    if note.lower() == 'q': return
    
    msg = f"{note};\n".encode('utf-8')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    print(f"[DISPATCH TIME] {time.time():.4f} - Sending UDP packet...")
    sock.sendto(msg, (ip, port))
    print(f"[FINISH TIME]   {time.time():.4f} - Packet sent.")
    sock.close()

def test_microcontroller():
    config = load_config()
    baud = config["communication"].get("pico_baud_rate", 9600)
    port = input("Enter serial port (e.g., /dev/ttyACM0) or 'q' to quit: ")
    if port.lower() == 'q': return
    
    fx = input("Enter LED Effect ID (e.g., 1): ")
    
    try:
        ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2) # Wait for Pico to reset after opening DTR
        
        msg = f"FX:{fx}\n".encode('utf-8')
        print(f"[DISPATCH TIME] {time.time():.4f} - Writing to Serial {port}...")
        ser.write(msg)
        ser.flush() # Ensure it's fully written to the OS buffer
        print(f"[FINISH TIME]   {time.time():.4f} - Serial write complete.")
        ser.close()
    except Exception as e:
        print(f"Serial Error: {e}")

def test_soundcard():
    config = load_config()
    sample_rate = config["audio_routing"].get("sample_rate", 48000)
    
    freq = float(input("Enter frequency in Hz (e.g., 190.5) or 'q' to quit: "))
    duration = float(input("Enter duration in seconds (e.g., 0.5): "))
    
    print(f"Generating a {freq}Hz sine wave for {duration} seconds...")
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    wave = 0.5 * np.sin(freq * t * 2 * np.pi)
    
    print(f"[DISPATCH TIME] {time.time():.4f} - Sending buffer to soundcard...")
    sd.play(wave, samplerate=sample_rate)
    sd.wait() # Block until done
    print(f"[FINISH TIME]   {time.time():.4f} - Audio playback finished.")

def main():
    parser = argparse.ArgumentParser(description="SWAID Hardware Profiler (Mock Server)")
    parser.add_argument("--mode", choices=["puredata", "microcontroller", "soundcard"], help="The hardware mode to test")
    args = parser.parse_args()
    
    if not args.mode:
        print("Please specify a mode. Example: python hardware_profiler.py --mode puredata")
        parser.print_help()
        sys.exit(1)
        
    print(f"=== Starting SWAID Hardware Profiler in {args.mode.upper()} mode ===")
    
    if args.mode == "puredata":
        test_puredata()
    elif args.mode == "microcontroller":
        test_microcontroller()
    elif args.mode == "soundcard":
        test_soundcard()

if __name__ == "__main__":
    main()
