import os
import sys
from typing import TYPE_CHECKING

os.environ["QT_API"] = "pyqt6"
from attributeserver.dell_server import (
    PositionServer,
    PressureServer,
    TemperatureServer,
)
from qtpy import QtCore, QtGui, QtWidgets, uic

try:
    os.chdir(sys._MEIPASS)
except:  # noqa: E722
    pass

if TYPE_CHECKING:
    import threading


class ServerWidget(QtWidgets.QWidget):
    def __init__(
        self, name: str, server: PositionServer | PressureServer | TemperatureServer
    ):
        super().__init__()

        self._name = name
        self.server = server
        self.server_thread: threading.thread | None = None

        self.initUI()

    def initUI(self):
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QtWidgets.QLabel(self._name, self)
        layout.addWidget(self.label)

        self.start_button = QtWidgets.QPushButton("Start Server", self)
        self.start_button.clicked.connect(self.start_server)
        layout.addWidget(self.start_button)

        self.stop_button = QtWidgets.QPushButton("Stop Server", self)
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        self.setLayout(layout)

    def start_server(self):
        self.server_thread = self.server.run()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_server(self):
        self.server.stop()
        if self.server_thread:
            self.server_thread.join()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)


class ServerGUI(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(ServerWidget("Position", PositionServer()))
        layout.addWidget(ServerWidget("Pressure", PressureServer()))
        layout.addWidget(ServerWidget("Temperature", TemperatureServer()))
        self.setLayout(layout)


if __name__ == "__main__":
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    win = ServerGUI()
    win.show()
    win.activateWindow()
    qapp.exec()
