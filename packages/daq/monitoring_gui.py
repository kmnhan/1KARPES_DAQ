import contextlib
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

with contextlib.suppress(Exception):
    os.chdir(sys._MEIPASS)

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

        self.refresh_timer = QtCore.QTimer()
        self.refresh_timer.setInterval(50)
        self.refresh_timer.timeout.connect(self.check_server_status)
        self.check_server_status()
        self.refresh_timer.start()

    def check_server_status(self):
        if self.server.running.is_set():
            self.button.setText("Stop Server")
        else:
            self.button.setText("Start Server")

    def initUI(self):
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QtWidgets.QLabel(self._name, self)
        layout.addWidget(self.label)

        self.button = QtWidgets.QPushButton("Start Server", self)
        self.button.clicked.connect(self.toggle_server)
        layout.addWidget(self.button)

        self.setLayout(layout)

    def toggle_server(self):
        if self.server.running.is_set():
            self.stop_server()
        else:
            self.start_server()

    def start_server(self):
        self.server_thread = self.server.run()

    def stop_server(self):
        self.server.stop()
        if self.server_thread:
            self.server_thread.join()


class ServerGUI(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Servers")
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(ServerWidget("Position", PositionServer()))
        layout.addWidget(ServerWidget("Pressure", PressureServer()))
        layout.addWidget(ServerWidget("Temperature", TemperatureServer()))
        self.setLayout(layout)

    def closeEvent(self, event: QtGui.QCloseEvent):
        for child in self.children():
            if isinstance(child, ServerWidget):
                child.stop_server()
        event.accept()


if __name__ == "__main__":
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    win = ServerGUI()
    win.show()
    win.activateWindow()
    qapp.exec()
