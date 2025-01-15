import contextlib
import logging
import multiprocessing
import os
import sys

os.environ["QT_API"] = "pyqt6"
from qtpy import QtCore, QtGui, QtWidgets, uic

from erpes_daq.attributeserver.widgets import StatusWidget
from erpes_daq.sescontrol.widgets import ScanType, SESShortcuts

with contextlib.suppress(Exception):
    os.chdir(sys._MEIPASS)

log = logging.getLogger("main")
log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)


# Log all uncaught exceptions
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    log.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = handle_exception


class QHLine(QtWidgets.QFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)


class MainWindowGUI(
    *uic.loadUiType(os.path.join(os.path.dirname(__file__), "main.ui"))
):
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
        self.actionworkfile.triggered.connect(self.scantype.show_workfile_viewer)
        self.actionfixfiles.triggered.connect(self.scantype.fix_files)

    def closeEvent(self, event: QtGui.QCloseEvent):
        threadpool = QtCore.QThreadPool.globalInstance()
        flag = threadpool.waitForDone(15000)
        if not flag:
            QtWidgets.QMessageBox.critical(
                self,
                "Threadpool timed out after 15 seconds",
                f"Remaining threads: {threadpool.activeThreadCount()}",
            )

        log.info("All threads properly terminated! Yay!")
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

    log.info("Starting application")
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    win = MainWindow()
    win.show()
    win.activateWindow()
    qapp.exec()
