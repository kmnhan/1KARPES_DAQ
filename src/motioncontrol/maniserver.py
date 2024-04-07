"""
A TCP server with a zmq.PAIR socket that enables interprocess communication with the
motion controller program. The server listens on port 42625. The commands follow a
SCPI-like syntax. All available commands are documented below.

Optional arguments are surrounded by brackets. The <axis> argument can either be a
string corresponding to a motor, or a integer corrensponding to the number of the
channel (1-based indexing). For the commands `NAME?`, `ENABLED?` and `POS?`, the <axis>
argument can be zero, which then returns a comma-separated string of corresponding
values. For these commands, omitting the <axis> argument results in the same behavior as
passing zero. Values for nonexistent axes will be returned as `nan` unless otherwise
specified.

STATUS? <controller>
    Returns the status integer. <controller> is a 0-based controller index.
NAME? [<axis>]
    Returns the name of the given channel, regardless of its enabled state. If the given
    channel is not found, returns an empty string.
ENABLED? [<axis>]
    Returns 0 or 1 based on whether the channel is enabled. If the given channel is not
    found, returns 0.
POS? [<axis>]
    Returns the current calibrated position of the given channel. If the given channel
    is disabled or not found, returns `nan`.
TOL? <axis>
    Returns the raw tolerance (integer-like) of the given channel regardless of its
    enabled state.
ATOL? <axis>
    Returns the absolute (calibrated) tolerance (float-like) of the given channel
    regardless of its enabled state.
MINMAX? <axis>
    Returns the configured minimum and maximum position of the given channel, given as a
    comma-separated string of two floats.
FIN? <uid>
    Returns 0 or 1 based on whether the motion corresponding to the given unique
    identifier is finished. The <uid> parameter is the unique identifier for each motion
    command, specified on the `MOVE` command.
CLR <uid>
    This command is used to signal that the given unique identifier can be cleared from
    memory. Future calls to `FIN?` with the same <uid> will be undefined. This command
    must only be called when the motion corresponding to the given unique identifier no
    longer needs to be tracked. When this function is called while the corresponding
    motion is still ongoing, the behavior is undefined.
MOVE <axis>,<position>[,<uid>]
    Queues the motion to move the specified axis to <position>. If the <uid> parameter
    is provided, the state of the motion can be tracked with the given identifier using
    the `FIN?` command. The <uid> parameter must be a unique string. Using a uuid
    generator is recommended. If the given channel is not found, the command is silently
    ignored, and the <uid>, if given, is silently discarded.

"""

import threading
import time

import zmq
from qtpy import QtCore


class ManiServer(QtCore.QThread):
    PORT = 42625

    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()
    sigRequest = QtCore.Signal(str, str)
    sigCommand = QtCore.Signal(str, str)
    sigMove = QtCore.Signal(str, float, object)

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
        socket: zmq.Socket = context.socket(zmq.PAIR)
        socket.bind(f"tcp://*:{self.PORT}")
        self.sigSocketBound.emit()

        while not self.stopped.is_set():
            try:
                message: str = socket.recv_string(flags=zmq.NOBLOCK)
            except zmq.error.Again:
                time.sleep(0.001)
                continue
            else:
                if "?" in message:  # Query
                    message: list[str] = [s.strip() for s in message.split("?")]
                    command, args = message[0].upper(), "".join(message[1:])
                    self.sigRequest.emit(command, args)
                    # Wait until we get an answer
                    while self._ret_val is None:
                        time.sleep(0.001)
                    socket.send_string(str(self._ret_val))
                    self.set_value(None)
                else:  # Command
                    message: list[str] = [s.strip() for s in message.split()]
                    command, args = message[0].upper(), "".join(message[1:])
                    if command == "MOVE" or command == "MV":
                        args = args.split(",")
                        if len(args) == 2:
                            axis, pos = args
                            uid = None
                        elif len(args) == 3:
                            axis, pos, uid = args
                        self.sigMove.emit(axis, float(pos), uid)
                    else:
                        self.sigCommand.emit(command, args)

        socket.close()
        self.sigSocketClosed.emit()
