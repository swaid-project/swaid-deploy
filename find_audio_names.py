import sounddevice as sd
import json

def list_devices():
    print("\n" + "="*60)
    print(" SWAID REMOTE AUDIO DIAGNOSTIC")
    print("="*60)
    
    devices = sd.query_devices()
    print(f"\nFound {len(devices)} devices:\n")
    
    for i, dev in enumerate(devices):
        name = dev['name']
        outs = dev['max_output_channels']
        default = " (DEFAULT)" if i == sd.default.device[1] else ""
        print(f"[{i}] {name}")
        print(f"    Channels: {outs} {default}")
        print("-" * 30)

    print("\nRECOMMENDATION:")
    print("Look for the name of your LG TV and the ICUSBAUDIO7D device above.")
    print("Copy the text exactly into your plate-resonance/system_config.json")
    print("="*60 + "\n")

if __name__ == "__main__":
    try:
        list_devices()
    except Exception as e:
        print(f"Error: {e}")
        print("Please run: pip install sounddevice")
