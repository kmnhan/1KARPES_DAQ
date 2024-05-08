from __future__ import annotations

import sys

import pyloncam
import webcam
from qtpy import QtCore, QtWidgets, uic

uiclass, baseclass = uic.loadUiType("camera.ui")


class CameraWindow(uiclass, baseclass):
    USER_WINDOWS: dict[str, type[QtWidgets.QWidget]] = {
        "webcam": webcam.MainWindow,
        "basler": pyloncam.MainWindow,
    }

    sigFocusChanged = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("1KARPES Controls")

        self._child_windows: dict[str, QtWidgets.QWidget | None] = {
            k: None for k in self.USER_WINDOWS.keys()
        }

        self.webcam_btn.clicked.connect(lambda: self.toggle_window("webcam"))
        self.basler_btn.clicked.connect(lambda: self.toggle_window("basler"))

    def toggle_window(self, window: str):
        if self._child_windows[window] is None:
            self._child_windows[window] = self.USER_WINDOWS[window]()
            self._child_windows[window].show()
        else:
            self._child_windows[window].close()
            self._child_windows[window] = None

    def closeEvent(self, *args, **kwargs):
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)

    win = CameraWindow()
    win.show()
    win.activateWindow()

    qapp.exec()
