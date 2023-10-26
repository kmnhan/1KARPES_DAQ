from __future__ import annotations

import os
import sys
import time
import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets, uic

from SESWrapper.ses_measure import SESMeasure
import framegui, webcam

SES_DIR = "D:/SES_1.9.6_Win64"
WRAPPER_PATH = os.path.join(SES_DIR, "SESWrapper.dll")
SES_INSTR = os.path.join(SES_DIR, "dll/SESInstrument.dll")
INSTR_PATH = os.path.join(SES_DIR, "data/DA30_Instrument.dat")


uiclass, baseclass = uic.loadUiType("test_gui.ui")


class SESDAQMain(uiclass, baseclass):
    USER_WINDOWS: dict[str, type[QtWidgets.QWidget]] = {
        "webcam": webcam.MainWindow,
        "basler": framegui.MainWindow,
    }

    # When changing this, make sure to update the objectName of the buttons
    SES_WINDOWS: tuple[str, ...] = (
        "CalibrateVoltages",
        "CalibrateDetector",
        "ControlSupplies",
        "SupplyInfo",
        "DetectorInfo",
    )

    sigFocusChanged = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("1KARPES Controls")

        # for debugging purposes on macOS
        if sys.platform.startswith("win"):
            # if False:
            self.measure = SESMeasure(
                WRAPPER_PATH,
                SES_DIR,
                ses_instrument=SES_INSTR,
                inst_path=INSTR_PATH,
                verbose=True,
                element_set="Low Pass (UPS)",
                motorcontrol=None,
            )
            for win_type in self.SES_WINDOWS:
                getattr(self, win_type).clicked.connect(
                    lambda *, v=win_type: self.measure.ses.OpenGUI(v)
                )
        else:
            self.measure = None
            for win_type in self.SES_WINDOWS:
                getattr(self, win_type).setDisabled(True)

        self._child_windows: dict[str, QtWidgets.QWidget | None] = {
            k: None for k in self.USER_WINDOWS.keys()
        }

        self.webcam_btn.clicked.connect(lambda: self.toggle_window("webcam"))
        self.basler_btn.clicked.connect(lambda: self.toggle_window("basler"))

    def test_acquisition(self):
        region = {
            # "fixed": False,
            # "highEnergy": 16.9778,
            # "lowEnergy": 15.4222,
            # "energyStep": 0.020,
            "fixed": True,
            "centerEnergy": 16.2000,
            "dwellTime": 10,  # ms
            "lens_mode": "DA30_01",
            "pass_energy": 20.0,
            "sweeps": 1,
        }
        data, slice_scale, channel_scale = self.measure.MeasureAnalyzerRegion(region)

    def toggle_window(self, window: str):
        if self._child_windows[window] is None:
            self._child_windows[window] = self.USER_WINDOWS[window]()
            self._child_windows[window].show()
        else:
            self._child_windows[window].close()
            self._child_windows[window] = None

    def closeEvent(self, *args, **kwargs):
        if self.measure is not None:
            self.measure.Finalize()
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)

    win = SESDAQMain()
    win.show()
    win.activateWindow()

    win.test_acquisition()

    qapp.exec()
