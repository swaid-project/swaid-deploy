import cv2
import time
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

class CenterCameraThread(QThread):
    camera_frame_ready = Signal(object)
    
    def __init__(self, camera_source):
        super().__init__()
        self.camera_source = camera_source
        self.running = True
        
    def run(self):
        from vision.hand_tracking import open_camera
        
        cap = open_camera(self.camera_source)
        if not cap.isOpened():
            print(f"[CenterCamera] Failed to open {self.camera_source}")
            self.running = False
            return
            
        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue
                
            # Flip and convert color
            frame = cv2.flip(frame, 1)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame_rgb.shape
            qimg = QImage(frame_rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
            self.camera_frame_ready.emit(qimg)
            time.sleep(1/30.0) # ~30 fps
            
        cap.release()
        
    def stop(self):
        self.running = False
