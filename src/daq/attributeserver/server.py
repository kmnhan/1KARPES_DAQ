import threading
import time
from multiprocessing import shared_memory

import zmq
from attributeserver.getter import get_header
from qtpy import QtCore


class AttributeServer(QtCore.QThread):
    PORT = 5556
    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.stopped = threading.Event()

    @property
    def running(self):
        return not self.stopped.is_set()

    def run(self):
        self.mutex = QtCore.QMutex()
        self.stopped.clear()

        # Initialize shared memory
        self.shm_slit = shared_memory.SharedMemory(name="slit_idx", create=True, size=1)
        self.shm_seq = shared_memory.SharedMemory(name="seq_start", create=True, size=8)

        context = zmq.Context.instance()
        if not context:
            context = zmq.Context()
        socket: zmq.Socket = context.socket(zmq.PUB)
        socket.bind(f"tcp://*:{self.PORT}")
        self.sigSocketBound.emit()

        # Broadcast header over socket
        while not self.stopped.is_set():
            socket.send_string(get_header())
            time.sleep(0.005)

        # Remove shared memory
        self.shm_slit.close()
        self.shm_slit.unlink()
        self.shm_seq.close()
        self.shm_seq.unlink()

        socket.close()
        self.sigSocketClosed.emit()
