"""Optics controller server.

A TCP server with a zmq.PAIR socket that enables interprocess communication with the
optics controller program. The server listens on port 42633. The commands follow a
SCPI-like syntax. All available commands are documented below.

Optional arguments are surrounded by brackets. The <axis> argument can either be a
string corresponding to a motor, or a integer corrensponding to the number of the
channel (0-based indexing). For `POS?` and `ENABLED?`, the <axis> argument can be
omitted, which then returns a comma-separated string of corresponding values.

ENABLED? [<axis>]
    Returns 0 or 1 based on whether the channel is enabled. If the given channel is not
    found, returns 0.
POS? [<axis>]
    Returns the current position of the given channel (in physical units).
MINMAX? <axis>
    Returns the minimum and maximum position of the given channel, given as a
    comma-separated string of two floats.
CMD? <uid>
    Returns 0 or 1 based on whether the motion corresponding to the given unique
    identifier has been conveyed to the controller successfully. This does not
    necessarily mean that the motion is finished. The <uid> parameter is the unique
    identifier for each motion command, specified on the `MOVE` command.
CLR <uid>
    This command is used to signal that the given unique identifier can be cleared from
    memory. Future calls to `CMD?` with the same <uid> will be undefined. This command
    must only be called when the motion corresponding to the given unique identifier no
    longer needs to be tracked. This command has no effect if it is called while the
    corresponding motion is still ongoing.
MOVE <axis>,<position>[,<uid>]
    Queues the motion to move the specified axis to <position>. If the <uid> parameter
    is provided, the state of the motion can be tracked with the given identifier using
    the `CMD?` command. The <uid> parameter must be a unique string. Using a uuid
    generator is recommended. If the given channel is not found, the command is silently
    ignored, and the <uid>, if given, is silently discarded.
MOVEPOL <pol_num>[,<uid>]
    Queues the motion to move the polarization state to the specified polarization
    number. The mapping between polarization number and motor positions is pre-defined
    in the optics controller program. If the <uid> parameter is provided, the state of
    the motion can be tracked with the given identifier using the `CMD?` command. The
    <uid> parameter must be a unique string. Using a uuid generator is recommended. If
    the given polarization number is invalid, the command is silently ignored, and the
    <uid>, if given, is silently discarded.

"""

import logging
import threading
import time

import zmq
from qtpy import QtCore

log = logging.getLogger("opticscontrol")


class OpticsServer(QtCore.QThread):
    PORT = 42633

    sigSocketBound = QtCore.Signal()
    sigSocketClosed = QtCore.Signal()
    sigRequest = QtCore.Signal(str, str)
    sigCommand = QtCore.Signal(str, str)
    sigMove = QtCore.Signal(str, float, object)
    sigMovePol = QtCore.Signal(int, object)

    def __init__(self):
        super().__init__()
        self.stopped = threading.Event()

    @property
    def running(self) -> bool:
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
        log.debug("SERVER Bound to port %d", self.PORT)

        while not self.stopped.is_set():
            try:
                message: str = socket.recv_string(flags=zmq.NOBLOCK)
            except zmq.error.Again:
                time.sleep(0.01)
                continue
            else:
                if "?" in message:  # Query
                    message: list[str] = [s.strip() for s in message.split("?")]
                    command, args = message[0].upper(), "".join(message[1:])
                    self.sigRequest.emit(command, args)

                    log.debug(
                        "SERVER Received query: %s %s, waiting for response",
                        command,
                        args,
                    )

                    while self._ret_val is None:
                        time.sleep(0.01)
                    return_str = str(self._ret_val)
                    self.set_value(None)

                    log.debug("SERVER Sending response: %s", return_str)
                    socket.send_string(return_str)

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
                    elif command == "MOVEPOL":
                        args = args.split(",")
                        if len(args) == 1:
                            pol_num = args[0]
                            uid = None
                        elif len(args) == 2:
                            pol_num, uid = args
                        self.sigMovePol.emit(int(pol_num), uid)
                    else:
                        self.sigCommand.emit(command, args)

        socket.close()
        self.sigSocketClosed.emit()
