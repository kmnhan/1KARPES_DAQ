"""Server side script that communicates with SES"""


import threading
import time

import zmq
from qtpy import QtCore

# commands = ["? STATUS", "? X", "? Y", "? Z", "? P", "? T", "? A", "MOVE X 0.123"]


class ManiServer(QtCore.QThread):
    PORT = 42625

    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()
    sigMove = QtCore.Signal(str, float)
    sigRequest = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.stopped = threading.Event()

    @property
    def running(self):
        return not self.stopped.is_set()

    @QtCore.Slot(object)
    def set_value(self, value):
        self.mutex.lock()
        self._ret_val = value
        self.mutex.unlock()

    def run(self):
        self.mutex = QtCore.QMutex()
        self.set_value(None)

        self.stopped.clear()
        context = zmq.Context.instance()
        if not context:
            context = zmq.Context()
        socket: zmq.Socket = context.socket(zmq.REP)
        socket.bind(f"tcp://*:{self.PORT}")
        self.sigSocketBound.emit()

        while not self.stopped.is_set():
            try:
                message: list[str] = (
                    socket.recv(flags=zmq.NOBLOCK).decode("utf-8").split()
                )
            except zmq.error.Again:
                time.sleep(0.01)
                continue
            else:
                if message[0] == "?":
                    message.pop(0)
                    self.sigRequest.emit(message)
                elif message[0] == "MOVE":
                    self.sigMove.emit(message[1], float(message[2]))
                    self.set_value("")
                else:
                    self.set_value("")

                # wait until we get an answer
                while self._ret_val is None:
                    time.sleep(0.001)
                socket.send(str(self._ret_val).encode())

                self.set_value(None)

        socket.close()
        self.sigSocketClosed.emit()
