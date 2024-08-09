"""
Attribute server for the DAQ computer.

The SES user extension plugin will connect to this server after every scan to get the
scan attributes.

"""

import logging
import threading
import time
from multiprocessing import shared_memory

import zmq
from qtpy import QtCore

from attributeserver.getter import get_header

log = logging.getLogger("attrs")


class AttributeServer(QtCore.QThread):
    PORT = 5556

    def __init__(self):
        super().__init__()
        self.stopped = threading.Event()

    @property
    def running(self):
        return not self.stopped.is_set()

    def run(self):
        self.mutex = QtCore.QMutex()
        self.stopped.clear()

        self.shm_slit = shared_memory.SharedMemory(name="slit_idx", create=True, size=1)
        log.debug("Shared memory slit_idx created")

        self.shm_seq = shared_memory.SharedMemory(name="seq_start", create=True, size=8)
        log.debug("Shared memory seq_start created")

        context = zmq.Context.instance()
        if not context:
            context = zmq.Context()
        socket: zmq.Socket = context.socket(zmq.PUB)
        socket.bind(f"tcp://*:{self.PORT}")
        log.info(f"Attribute server started on TCP port {self.PORT}")

        # Broadcast header over socket
        while not self.stopped.is_set():
            socket.send_string(get_header())
            time.sleep(0.01)

        log.info("Attribute server stopped")

        self.shm_slit.close()
        self.shm_slit.unlink()
        log.debug("Shared memory slit_idx unlinked")

        self.shm_seq.close()
        self.shm_seq.unlink()
        log.debug("Shared memory shm_seq unlinked")

        socket.close()
        log.debug("Attribute server socket closed")
