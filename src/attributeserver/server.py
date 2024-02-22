import time
import threading

import zmq
from qtpy import QtCore

from getter import get_header


class AttributeServer(QtCore.QThread):
    PORT = 5557
    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.stopped = threading.Event()

    @property
    def running(self):
        return not self.stopped.is_set()

    def lock_mutex(self):
        if self.mutex is not None:
            self.mutex.lock()

    def unlock_mutex(self):
        if self.mutex is not None:
            self.mutex.unlock()

    def request_query(self, message: str, signal: QtCore.SignalInstance):
        self.lock_mutex()
        self.queue.put((message, signal))
        self.unlock_mutex()

    def request_write(self, message: str):
        self.lock_mutex()
        self.queue.put((message, None))
        self.unlock_mutex()

    def run(self):
        self.mutex = QtCore.QMutex()
    
        self.stopped.clear()
        context = zmq.Context.instance()
        if not context:
            context = zmq.Context()
        socket: zmq.Socket = context.socket(zmq.PUSH)
        socket.bind(f"tcp://*:{self.PORT}")
        self.sigSocketBound.emit()

        while not self.stopped.is_set():
            # try:
            #     message = socket.recv(flags=zmq.NOBLOCK)
            # except zmq.error.Again:
            #     pass
            # else:
            socket.send_string(get_header())
            time.sleep(0.001)
        socket.close()
        self.sigSocketClosed.emit()
