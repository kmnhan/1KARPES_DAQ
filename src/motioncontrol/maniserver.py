"""Server side script. The commands are arbitrary and do not follow any standard (sorry)

There are two types of commands. One is a query which is prefixed with `?`. The other is
a motion command which is prefixed with `MOVE`. Some exmample commands and replies are
shown below. `[motor]` can be replaced by any character in `['X', 'Y', 'Z', 'P', 'T',
'Z']` that represents one of 6 axes. Values for disabled channels or disconnected axes
will be returned as `nan`. Motion commands will reply with an empty string.

+--------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| Query              | Description                                                                                                                                                                          |
+====================+======================================================================================================================================================================================+
| ?                  | List of length 6 that contains positions of all 6 channels.                                                                                                                          |
+--------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| ? STATUS           | Current status of the controller. For more information, see the docstring for MainWindow.status.                                                                                     |
+--------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| ? [motor]          | Get current position of motor in mm.                                                                                                                                                 |
+--------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| ? [motor] TOL      | Get tolerance of motor in mm.                                                                                                                                                        |
+--------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| ? [motor] MIN      | Get minimum position of motor in mm.                                                                                                                                                 |
+--------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| ? [motor] MAX      | Get minimum position of motor in mm.                                                                                                                                                 |
+--------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| MOVE [motor] 0.123 | Queues the motion to move the specified axis to the specified value. Replies with 0 when added to queue. When the given axis cannot be found among enabled channels, replies with 1. |
+--------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

"""

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
                else:
                    self.set_value("")

                # wait until we get an answer
                while self._ret_val is None:
                    time.sleep(0.001)
                socket.send(str(self._ret_val).encode())

                self.set_value(None)

        socket.close()
        self.sigSocketClosed.emit()
