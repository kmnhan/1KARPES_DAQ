"""Server side script that communicates with SES"""


import time
import threading

import zmq
from qtpy import QtCore

# from constants import CRYO_PORT, MG15_PORT, SLIT_PORT, SLIT_TABLE


commands = ["? STATUS", "? X", "? Y", "? Z", "? P", "? T", "? A", "MOVE X 0.123"]


class ManiServer(QtCore.QThread):
    PORT = 42623
    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()

    sigMove = QtCore.Signal(object, float)

    def __init__(self):
        super().__init__()
        self.running: bool = False
        
        self._ret_val = None
        
    def set_value(self, value):
        self._ret_val = value

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
                message: list[str] = (
                    socket.recv(flags=zmq.NOBLOCK).decode("utf-8").split()
                )
            except zmq.error.Again:
                time.sleep(0.1)
                continue
            else:
                if message[0] == "?":
                    print(message[1])
                elif message[0] == "MOVE":
                    print(message[1], message[2])
                else:
                    socket.send(b"")
        socket.close()
        self.sigSocketClosed.emit()
