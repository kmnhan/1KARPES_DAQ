from __future__ import annotations

import logging
import os

import zmq
from qtpy import QtCore, QtGui, QtWidgets, uic

from constants import SLIT_TABLE, SLIT_PORT, CRYO_PORT, MG15_PORT
from logreader import get_pressure, get_temperature

# class ServerTemplate(QtCore.QThread):
#     PORT = 5555

#     def __init__(self):
#         super().__init__()
#         self.running: bool = False
#         self.context: zmq.Context | None = None

#     def run(self):
#         self.running = True
#         self.context = zmq.Context()
#         socket:zmq.Socket = self.context.socket(zmq.REP)
#         socket.bind(f"tcp://*:{self.PORT}")

#         while self.running:
#             try:
#                 message = socket.recv(flags=zmq.NOBLOCK)
#             except zmq.error.Again:
#                 continue
#             else:
#                 socket.send_string("Hello World!")
#         socket.close()
#         self.context.destroy()


class SlitServer(QtCore.QThread):
    PORT = SLIT_PORT
    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()

    def __init__(self, value: int | None = None):
        super().__init__()
        self.value = value
        self.running: bool = False
        self.context: zmq.Context | None = None

    @QtCore.Slot(int)
    def set_value(self, value: int):
        self.value = value

    def run(self):
        self.running = True
        self.context = zmq.Context()
        socket: zmq.Socket = self.context.socket(zmq.REP)
        socket.bind(f"tcp://*:{self.PORT}")
        self.sigSocketBound.emit()

        while self.running:
            try:
                message = socket.recv(flags=zmq.NOBLOCK)
            except zmq.error.Again:
                continue
            else:
                if message == b"0":
                    socket.send_string(str(SLIT_TABLE[self.value][0]))
                elif message == b"1":
                    socket.send_string(str(SLIT_TABLE[self.value][1]))
                elif message == b"2":
                    socket.send_string(str(SLIT_TABLE[self.value][2]))
        socket.close()
        self.sigSocketClosed.emit()
        self.context.destroy()


def dict_to_header(d: dict[str, str]) -> str:
    out: str = ""
    for k, v in d.items():
        out += f"{k}={v}\n"
    return out


class TemperatureServer(QtCore.QThread):
    PORT = CRYO_PORT
    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.running: bool = False
        self.context: zmq.Context | None = None

    def run(self):
        self.running = True
        self.context = zmq.Context()
        socket: zmq.Socket = self.context.socket(zmq.REP)
        socket.bind(f"tcp://*:{self.PORT}")
        self.sigSocketBound.emit()

        while self.running:
            try:
                message = socket.recv(flags=zmq.NOBLOCK)
            except zmq.error.Again:
                continue
            else:
                if message == b"1":
                    socket.send_string(dict_to_header(get_temperature()))
                else:
                    socket.send_json(get_temperature())

        socket.close()
        self.sigSocketClosed.emit()
        self.context.destroy()


class PressureServer(QtCore.QThread):
    PORT = MG15_PORT
    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.running: bool = False
        self.context: zmq.Context | None = None

    def run(self):
        self.running = True
        self.context = zmq.Context()
        socket: zmq.Socket = self.context.socket(zmq.REP)
        socket.bind(f"tcp://*:{self.PORT}")
        self.sigSocketBound.emit()

        while self.running:
            try:
                message = socket.recv(flags=zmq.NOBLOCK)
            except zmq.error.Again:
                continue
            else:
                if message == b"1":
                    socket.send_string(dict_to_header(get_pressure()))
                else:
                    socket.send_json(get_pressure())

        socket.close()
        self.sigSocketClosed.emit()
        self.context.destroy()
