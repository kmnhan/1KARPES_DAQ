from __future__ import annotations

import os
import sys
import time
import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets, uic


from SESWrapper.ses_measure import SESMeasure


SES_DIR = "D:/SES_1.9.6_Win64"
WRAPPER_PATH = "D:/SES_1.9.6_Win64/SESWrapper.dll"
SES_INSTR = os.path.join(SES_DIR, "dll/SESInstrument.dll")
INSTR_PATH = os.path.join(SES_DIR, "data/DA30_Instrument.dat")


uiclass, baseclass = uic.loadUiType("test_gui.ui")


class SESDAQMain(uiclass, baseclass):
    sigFocusChanged = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("SES GUI")

        self.measure = SESMeasure(
            WRAPPER_PATH,
            SES_DIR,
            ses_instrument=SES_INSTR,
            inst_path=INSTR_PATH,
            verbose=True,
            element_set="Low Pass (UPS)",
            motorcontrol=None,
        )
        self.CalibrateVoltages.clicked.connect(
            lambda: self.measure.ses.OpenGUI("CalibrateVoltages")
        )
        self.CalibrateDetector.clicked.connect(
            lambda: self.measure.ses.OpenGUI("CalibrateDetector")
        )
        self.ControlSupplies.clicked.connect(
            lambda: self.measure.ses.OpenGUI("ControlSupplies")
        )
        self.SupplyInfo.clicked.connect(lambda: self.measure.ses.OpenGUI("SupplyInfo"))
        self.DetectorInfo.clicked.connect(
            lambda: self.measure.ses.OpenGUI("DetectorInfo")
        )

    def closeEvent(self, *args, **kwargs):
        self.measure.Finalize()
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)

    win = SESDAQMain()
    win.show()
    win.activateWindow()

    qapp.exec()
