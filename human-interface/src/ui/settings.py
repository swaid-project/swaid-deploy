from pathlib import Path
from PySide6.QtWidgets import (QDialog, QComboBox, QDialogButtonBox, QFormLayout, 
                             QLabel, QPushButton, QHBoxLayout, QWidget)

_DIALOG_STYLE = """
QDialog { background-color: #0d0f14; color: #c8d4e8; font-family: Arial; font-size: 13px; }
QLabel { color: #7a8faa; font-size: 12px; }
QComboBox { background-color: #1a1e28; color: #c8d4e8; border: 1px solid #2a3a55; border-radius: 5px; padding: 5px 10px; min-width: 220px; font-size: 13px; }
QComboBox:hover { border: 1px solid #00d9e8; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background-color: #1a1e28; color: #c8d4e8; border: 1px solid #2a3a55; selection-background-color: #00d9e820; selection-color: #00d9e8; }
QPushButton { background-color: #1a1e28; color: #c8d4e8; border: 1px solid #2a3a55; border-radius: 5px; padding: 6px 20px; font-size: 13px; min-width: 72px; }
QPushButton:hover { background-color: #00d9e820; border: 1px solid #00d9e8; color: #00d9e8; }
QPushButton:pressed { background-color: #00d9e840; }
"""

_TOGGLE_STYLE = (
    "QPushButton {"
    "  background-color: #1a1e28; color: #6677aa;"
    "  border: 1px solid #2a3a55; border-radius: 5px;"
    "  padding: 6px 16px; font-size: 13px; text-align: left;"
    "}"
    "QPushButton:checked {"
    "  background-color: #00d9e825; color: #00d9e8;"
    "  border: 1px solid #00d9e8;"
    "}"
    "QPushButton:hover { border: 1px solid #00d9e8; }"
)

class CameraSettingsDialog(QDialog):
    def __init__(self, tracking_camera, center_mode, center_camera,
                 standby_callback=None,
                 diag_callback=None,  diag_active=False,
                 hb_callback=None,    hb_active=True,
                 hints_callback=None, hints_active=True,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("SWAID — Settings")
        self.setStyleSheet(_DIALOG_STYLE)
        
        self.tracking_camera_combo = QComboBox()
        self.center_mode_combo = QComboBox()
        self.center_camera_combo = QComboBox()
        
        # Discover cameras
        devices = self._discover_cameras()
        for label, source in devices:
            self.tracking_camera_combo.addItem(label, source)
            self.center_camera_combo.addItem(label, source)
            
        self.center_mode_combo.addItem("Live footage", "live")
            
        # Set current
        self._set_current(self.tracking_camera_combo, tracking_camera)
        self._set_current(self.center_camera_combo, center_camera)
        self.center_mode_combo.setCurrentIndex(0)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # -- Toggle row --
        diag_btn = QPushButton("  [I]  Diagnostics")
        diag_btn.setCheckable(True)
        diag_btn.setChecked(diag_active)
        diag_btn.setStyleSheet(_TOGGLE_STYLE)
        if diag_callback: diag_btn.clicked.connect(diag_callback)

        hb_btn = QPushButton("  [H]  Heartbeat")
        hb_btn.setCheckable(True)
        hb_btn.setChecked(hb_active)
        hb_btn.setStyleSheet(_TOGGLE_STYLE)
        if hb_callback: hb_btn.clicked.connect(hb_callback)

        hints_btn = QPushButton("  [B]  Hints Bar")
        hints_btn.setCheckable(True)
        hints_btn.setChecked(hints_active)
        hints_btn.setStyleSheet(_TOGGLE_STYLE)
        if hints_callback: hints_btn.clicked.connect(hints_callback)

        toggle_row = QWidget()
        toggle_row_layout = QHBoxLayout(toggle_row)
        toggle_row_layout.setContentsMargins(0, 0, 0, 0)
        toggle_row_layout.setSpacing(8)
        toggle_row_layout.addWidget(diag_btn)
        toggle_row_layout.addWidget(hb_btn)
        toggle_row_layout.addWidget(hints_btn)

        # -- Standby test button --
        standby_btn = QPushButton("▶  Test Standby Mode")
        standby_btn.setStyleSheet(
            "QPushButton { color: #00d9e8; border: 1px solid #00d9e840; }"
            "QPushButton:hover { background-color: #00d9e820; border: 1px solid #00d9e8; }"
        )
        if standby_callback: standby_btn.clicked.connect(standby_callback)
        else: standby_btn.setEnabled(False)

        layout = QFormLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setVerticalSpacing(12)
        layout.setHorizontalSpacing(16)
        layout.addRow("Toggles", toggle_row)
        layout.addRow("Tracking das mãos", self.tracking_camera_combo)
        layout.addRow("Centro", self.center_mode_combo)
        layout.addRow("Câmera do centro", self.center_camera_combo)
        layout.addRow("", standby_btn)
        layout.addRow(buttons)

    def _discover_cameras(self):
        from vision.hand_tracking import discover_camera_choices
        return discover_camera_choices()

    def _set_current(self, combo, val):
        for i in range(combo.count()):
            if combo.itemData(i) == val:
                combo.setCurrentIndex(i)
                return

    def values(self):
        return {
            "tracking_camera": self.tracking_camera_combo.currentData(),
            "center_mode": self.center_mode_combo.currentData(),
            "center_camera": self.center_camera_combo.currentData()
        }
