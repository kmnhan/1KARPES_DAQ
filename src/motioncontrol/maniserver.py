"""Server side script that communicates with SES"""


import zmq
from qtpy import QtCore
import time
# from constants import CRYO_PORT, MG15_PORT, SLIT_PORT, SLIT_TABLE


commands = [
    "?STATUS",
    "?X",
    "?Y",
    "?Z",
    "?P",
    "?T",
    "?A",
]

class ManiServer(QtCore.QThread):
    PORT = 42623
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
                time.sleep(0.1)
                continue
            else:
                pass

        socket.close()
        self.sigSocketClosed.emit()

