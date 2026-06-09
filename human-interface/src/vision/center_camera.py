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
        source = self.camera_source
        if isinstance(source, str) and source.startswith("/dev/video"):
            try: source = int(source.replace("/dev/video", ""))
            except ValueError: pass
            
        cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
        if not cap.isOpened():
            print(f"[CenterCamera] Failed to open {self.camera_source} (mapped to {source})")
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
