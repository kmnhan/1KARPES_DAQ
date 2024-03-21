import sys

from qtpy import QtCore, QtWidgets, uic

import pyloncam
import status
import webcam


class MainWindow(*uic.loadUiType("main.ui")):
    USER_WINDOWS: dict[str, type[QtWidgets.QWidget]] = {
        "webcam": webcam.MainWindow,
        "basler": pyloncam.MainWindow,
        "status": status.MainWindow,
    }

    sigFocusChanged = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("1KARPES Controls")

        self._child_windows: dict[str, QtWidgets.QWidget | None] = {
            k: None for k in self.USER_WINDOWS.keys()
        }

        # camera
        self.webcam_btn.clicked.connect(lambda: self.toggle_window("webcam"))
        self.basler_btn.clicked.connect(lambda: self.toggle_window("basler"))

        # status window
        self.status_btn.clicked.connect(lambda: self.toggle_window("status"))

    def toggle_window(self, window: str):
        win_closed = self._child_windows[window] is None
        if not win_closed:
            if not self._child_windows[window].isVisible():
                win_closed = True

        if win_closed:
            self._child_windows[window] = self.USER_WINDOWS[window]()
            self._child_windows[window].show()
            self._child_windows[window].activateWindow()
            self._child_windows[window].raise_()
        else:
            self._child_windows[window].close()
            self._child_windows[window] = None

    def closeEvent(self, *args, **kwargs):
        for w in self._child_windows.values():
            if w is not None:
                w.close()
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")

    win = MainWindow()
    win.show()
    win.activateWindow()
    win.status_btn.click()

    qapp.exec()
