import multiprocessing
import sys
import os

os.environ["QT_API"] = "pyqt6"
from qtpy import QtCore, QtGui, QtWidgets, uic

from attributeserver.widgets import StatusWidget
from sescontrol.widgets import ScanType, SESShortcuts


try:
    os.chdir(sys._MEIPASS)
except:
    pass


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

        self.threadpool = QtCore.QThreadPool.globalInstance()

        self.ses_shortcuts = SESShortcuts()
        self.status = StatusWidget()
        self.scantype = ScanType()

        self.centralWidget().layout().addWidget(self.ses_shortcuts)
        self.centralWidget().layout().addWidget(self.status)
        self.centralWidget().layout().addWidget(QHLine())
        self.centralWidget().layout().addWidget(self.scantype)

        self.ses_shortcuts.sigAliveChanged.connect(self.scantype.setEnabled)
        self.actionreconnect.triggered.connect(self.ses_shortcuts.reconnect)
        self.actionworkfile.triggered.connect(self.scantype.workfileitool.show)
        self.actionrestartworkfile.triggered.connect(
            self.scantype.restart_workfile_viewer
        )

    def closeEvent(self, event: QtGui.QCloseEvent):
        flag = self.threadpool.waitForDone(15000)
        if not flag:
            QtWidgets.QMessageBox.critical(
                self,
                "Threadpool timed out after 15 seconds",
                f"Remaining threads: {self.threadpool.activeThreadCount()}",
            )

        print("Proper Termination Achieved! Yay!")
        super().closeEvent(event)


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
