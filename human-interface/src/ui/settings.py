from pathlib import Path
from PySide6.QtWidgets import QDialog, QComboBox, QDialogButtonBox, QFormLayout, QLabel

_DIALOG_STYLE = """
QDialog { background-color: #0d0f14; color: #c8d4e8; font-family: Arial; font-size: 13px; }
QLabel { color: #7a8faa; font-size: 12px; }
QComboBox { background-color: #1a1e28; color: #c8d4e8; border: 1px solid #2a3a55; border-radius: 5px; padding: 5px 10px; min-width: 220px; font-size: 13px; }
QComboBox:hover { border: 1px solid #00d9e8; }
QComboBox::drop-down { border: none; width: 24px; }
QPushButton { background-color: #1a1e28; color: #c8d4e8; border: 1px solid #2a3a55; border-radius: 5px; padding: 6px 20px; font-size: 13px; min-width: 72px; }
QPushButton:hover { background-color: #00d9e820; border: 1px solid #00d9e8; color: #00d9e8; }
"""

class CameraSettingsDialog(QDialog):
    def __init__(self, tracking_camera, center_camera, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Câmeras — SWAID")
        self.setStyleSheet(_DIALOG_STYLE)
        
        self.tracking_camera_combo = QComboBox()
        self.center_camera_combo = QComboBox()
        
        # Discover cameras
        devices = self._discover_cameras()
        for label, source in devices:
            self.tracking_camera_combo.addItem(label, source)
            self.center_camera_combo.addItem(label, source)
            
        # Set current
        self._set_current(self.tracking_camera_combo, tracking_camera)
        self._set_current(self.center_camera_combo, center_camera)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow("Tracking das mãos", self.tracking_camera_combo)
        layout.addRow("Câmera do centro", self.center_camera_combo)
        layout.addRow(buttons)

    def _discover_cameras(self):
        video_devices = sorted(Path("/dev").glob("video*"), key=lambda p: int(p.name.replace("video", "") or 0))
        choices = []
        for dev in video_devices:
            choices.append((f"Device {dev.name}", str(dev)))
        if not choices:
            choices = [("Camera 1 (0)", 0), ("Camera 2 (1)", 1)]
        return choices

    def _set_current(self, combo, val):
        for i in range(combo.count()):
            if combo.itemData(i) == val:
                combo.setCurrentIndex(i)
                return

    def values(self):
        return {
            "tracking_camera": self.tracking_camera_combo.currentData(),
            "center_camera": self.center_camera_combo.currentData()
        }
