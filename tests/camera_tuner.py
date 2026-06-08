import cv2
import subprocess
import sys

def main():
    # Use the first argument as device, default to /dev/video2
    device = sys.argv[1] if len(sys.argv) > 1 else "/dev/video2"
    
    print(f"Connecting to {device}...")
    
    # Initialize basic camera settings
    subprocess.run(["v4l2-ctl", "-d", device, "-c", "auto_exposure=1"], check=False, stderr=subprocess.DEVNULL)
    subprocess.run(["v4l2-ctl", "-d", device, "-c", "exposure_dynamic_framerate=0"], check=False, stderr=subprocess.DEVNULL)
    
    # Try opening the camera using V4L2
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"Error: Could not open {device}. Make sure the camera is connected and the path is correct.")
        print(f"Usage: python camera_tuner.py [/dev/videoX]")
        return

    # Callbacks for the Trackbars
    def update_exposure(val):
        subprocess.run(["v4l2-ctl", "-d", device, "-c", f"exposure_time_absolute={val}"], check=False, stderr=subprocess.DEVNULL)

    def update_contrast(val):
        subprocess.run(["v4l2-ctl", "-d", device, "-c", f"contrast={val}"], check=False, stderr=subprocess.DEVNULL)
        
    def update_brightness(val):
        subprocess.run(["v4l2-ctl", "-d", device, "-c", f"brightness={val}"], check=False, stderr=subprocess.DEVNULL)

    # Create the window
    window_name = f"Camera Tuner - {device}"
    cv2.namedWindow(window_name)
    
    # Create Trackbars (Sliders)
    # The max values here are typical defaults. If your camera supports higher, you can adjust the script.
    cv2.createTrackbar("Exposure", window_name, 100, 1000, update_exposure)
    cv2.createTrackbar("Contrast", window_name, 128, 255, update_contrast)
    cv2.createTrackbar("Brightness", window_name, 128, 255, update_brightness)

    # Set initial value
    update_exposure(100)

    print("\n--- Camera Tuner Started ---")
    print("Use the sliders in the window to adjust the camera settings in real-time.")
    print("Press 'q' or 'ESC' while focused on the window to exit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame. Did the camera disconnect?")
            break

        cv2.imshow(window_name, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:  # 27 is ESC key
            break

    # Cleanup
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
