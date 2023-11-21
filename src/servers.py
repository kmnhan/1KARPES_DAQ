import time

import zmq
from qtpy import QtCore

from constants import CRYO_PORT, MG15_PORT, SLIT_PORT, SLIT_TABLE
from livelogreader import get_pressure, get_temperature

# class ServerTemplate(QtCore.QThread):
#     PORT = 5555

#     def __init__(self):
#         super().__init__()
#         self.running: bool = False

#     def run(self):
#         self.running = True
#         context = zmq.Context.instance()
#         if not context:
#             context = zmq.Context()
#         socket: zmq.Socket = context.socket(zmq.REP)
#         socket.bind(f"tcp://*:{self.PORT}")

#         while self.running:
#             try:
#                 message = socket.recv(flags=zmq.NOBLOCK)
#             except zmq.error.Again:
#                 pass
#             else:
#                 socket.send_string("Hello World!")
#             time.sleep(0.01)
#         socket.close()


def dict_to_header(d: dict[str, str]) -> str:
    out: str = ""
    for k, v in d.items():
        out += f"{k}={v}\n"
    return out


class SlitServer(QtCore.QThread):
    PORT = SLIT_PORT
    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()

    def __init__(self, value: int | None = None):
        super().__init__()
        self.value = value
        self.running: bool = False

    @QtCore.Slot(int)
    def set_value(self, value: int):
        self.value = value

    def run(self):
        self.running = True
        context = zmq.Context.instance()
        if not context:
            context = zmq.Context()
        socket: zmq.Socket = context.socket(zmq.REP)
        socket.bind(f"tcp://*:{self.PORT}")
        self.sigSocketBound.emit()

        while self.running:
            try:
                message = socket.recv(flags=zmq.NOBLOCK)
            except zmq.error.Again:
                pass
            else:
                slit_info = {
                    "Analyzer Slit Number": str(SLIT_TABLE[self.value][0]),
                    "Analyzer Slit Width": str(SLIT_TABLE[self.value][1]),
                    "Analyzer Slit Aperture": str(SLIT_TABLE[self.value][2]),
                }
                if message == b"1":
                    socket.send_string(dict_to_header(slit_info))
                else:
                    socket.send_json(slit_info)
            time.sleep(0.01)
        socket.close()
        self.sigSocketClosed.emit()


class TemperatureServer(QtCore.QThread):
    PORT = CRYO_PORT
    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.running: bool = False

    def run(self):
        self.running = True
        context = zmq.Context.instance()
        if not context:
            context = zmq.Context()
        socket: zmq.Socket = context.socket(zmq.REP)
        socket.bind(f"tcp://*:{self.PORT}")
        self.sigSocketBound.emit()

        while self.running:
            try:
                message = socket.recv(flags=zmq.NOBLOCK)
            except zmq.error.Again:
                pass
            else:
                if message == b"1":
                    socket.send_string(dict_to_header(get_temperature()))
                else:
                    socket.send_json(get_temperature())
            time.sleep(0.01)
        socket.close()
        self.sigSocketClosed.emit()


class PressureServer(QtCore.QThread):
    PORT = MG15_PORT
    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.running: bool = False

    def run(self):
        self.running = True
        context = zmq.Context.instance()
        if not context:
            context = zmq.Context()
        socket: zmq.Socket = context.socket(zmq.REP)
        socket.bind(f"tcp://*:{self.PORT}")
        self.sigSocketBound.emit()

        while self.running:
            try:
                message = socket.recv(flags=zmq.NOBLOCK)
            except zmq.error.Again:
                pass
            else:
                if message == b"1":
                    socket.send_string(dict_to_header(get_pressure()))
                else:
                    socket.send_json(get_pressure())
            time.sleep(0.01)
        socket.close()
        self.sigSocketClosed.emit()
