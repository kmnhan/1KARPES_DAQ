import multiprocessing
import sys

from qtpy import QtCore, QtGui, QtWidgets, uic

from attributeserver.widgets import StatusWidget
from sescontrol.widgets import ScanType, SESController


class MainWindowGUI(*uic.loadUiType("main.ui")):

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("1KARPES Data Acquisition")

        self.ses_controls = SESController()
        self.status = StatusWidget()
        self.scantype = ScanType()

        self.centralWidget().layout().addWidget(self.ses_controls)
        self.centralWidget().layout().addWidget(self.status)
        self.centralWidget().layout().addWidget(self.scantype)

        self.ses_controls.sigAliveChanged.connect(self.scantype.setEnabled)


class MainWindow(MainWindowGUI):
    def __init__(self):
        super().__init__()

    def closeEvent(self, event: QtGui.QCloseEvent):
        self.scantype.closeEvent(event)
        if event.isAccepted():
            self.status.closeEvent(event)
            super().closeEvent(event)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    win = MainWindow()
    win.show()
    win.activateWindow()
    qapp.exec()
