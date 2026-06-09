import os
import glob
import subprocess

def apply_v4l2_config(camera_device, exposure_time):
    if not camera_device or not os.path.exists(camera_device):
        return
    try:
        subprocess.run(["v4l2-ctl", "-d", camera_device, "-c", "auto_exposure=1"], check=False, stderr=subprocess.DEVNULL)
        subprocess.run(["v4l2-ctl", "-d", camera_device, "-c", "exposure_dynamic_framerate=0"], check=False, stderr=subprocess.DEVNULL)
        subprocess.run(["v4l2-ctl", "-d", camera_device, "-c", f"exposure_time_absolute={exposure_time}"], check=False, stderr=subprocess.DEVNULL)
        subprocess.run(["v4l2-ctl", "-d", camera_device, "-c", "contrast=128"], check=False, stderr=subprocess.DEVNULL)
        subprocess.run(["v4l2-ctl", "-d", camera_device, "-c", "brightness=128"], check=False, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[Hardware Discovery] Failed to apply v4l2-ctl on {camera_device}: {e}")

def get_camera_device_by_usb_port(port_identifier):
    """
    Resolves a USB port identifier (e.g., '1-2.1') to a /dev/videoX path.
    If port_identifier starts with '/dev/', it returns it directly for easy testing.
    """
    if not port_identifier:
        return None
        
    if port_identifier.startswith("/dev/"):
        return port_identifier if os.path.exists(port_identifier) else None
        
    for video_path in glob.glob("/sys/class/video4linux/video*"):
        try:
            # The realpath of the device points to the sysfs hardware tree
            real_path = os.path.realpath(video_path)
            if port_identifier in real_path:
                # Need to ensure it's a capture device, not a metadata node
                index_file = os.path.join(video_path, "index")
                if os.path.exists(index_file):
                    with open(index_file, 'r') as f:
                        if f.read().strip() == "0":
                            return "/dev/" + os.path.basename(video_path)
        except Exception:
            continue
    return None
