import multiprocessing
import sys

from qtpy import QtCore, QtGui, QtWidgets, uic

from attributeserver.widgets import StatusWidget
from sescontrol.widgets import ScanType, SESShortcuts


class QHLine(QtWidgets.QFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)


class MainWindowGUI(*uic.loadUiType("main.ui")):

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("1KARPES Data Acquisition")

        self.ses_shortcuts = SESShortcuts()
        self.status = StatusWidget()
        self.scantype = ScanType()

        self.centralWidget().layout().addWidget(self.ses_shortcuts)
        self.centralWidget().layout().addWidget(self.status)
        self.centralWidget().layout().addWidget(QHLine())
        self.centralWidget().layout().addWidget(self.scantype)

        self.ses_shortcuts.sigAliveChanged.connect(self.scantype.setEnabled)
        self.actionreconnect.triggered.connect(self.ses_shortcuts.reconnect)


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
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    win = MainWindow()
    win.show()
    win.activateWindow()
    qapp.exec()
