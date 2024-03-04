import contextlib
import enum
import math
import time
import uuid

import zmq

from . import Motor


class MMStatus(enum.IntEnum):
    Moving = 1
    Done = 2
    Aborted = 3
    Error = 4


class ManiClient:

    def __init__(self, port: int):
        self.port: int = port
        self.connected: bool = False

    def connect(self):
        context = zmq.Context.instance()
        if not context:
            context = zmq.Context()
        self.socket = context.socket(zmq.PAIR)
        self.socket.connect(f"tcp://localhost:{self.port}")
        self.connected = True

    def disconnect(self):
        self.socket.close()
        self.connected = False

    @contextlib.contextmanager
    def connection(self):
        """Context manager for socket connection.

        If the connection is already established, the existing socket is returned and
        nothing is done on exit. Otherwise,  the socket is closed after the block is
        exited.
        """
        need_connect: bool = not self.connected
        if need_connect:
            self.connect()
        try:
            yield self.socket
        finally:
            if need_connect:
                self.disconnect()

    def query(self, cmd: str) -> str:
        with self.connection():
            self.socket.send_string(cmd)
            ret = self.socket.recv_string()
        return ret

    def write(self, cmd: str) -> None:
        with self.connection():
            self.socket.send_string(cmd)

    def query_float(self, cmd: str) -> float:
        return float(self.query(cmd))

    def query_int(self, cmd: str) -> int:
        return int(self.query(cmd))

    def query_sequence(self, cmd: str) -> tuple[str, ...]:
        return self.query(cmd).split(",")

    def query_floats(self, cmd: str) -> tuple[float, ...]:
        return tuple(float(r) for r in self.query_sequence(cmd))

    def enabled(self, axis: int | str) -> bool:
        return bool(int(self.query(f"ENABLED? {axis}")))

    def bounds(self, axis: int | str) -> tuple[float, float]:
        return self.query_floats(f"MINMAX? {axis}")

    def pos(self, axis: int | str) -> float:
        return self.query_float(f"POS? {axis}")

    def tolerance(self, axis: int | str) -> float:
        return self.query_float(f"TOL? {axis}")

    def abs_tolerance(self, axis: int | str) -> float:
        return self.query_float(f"ATOL? {axis}")

    def request_move(self, axis: str | int, target: float) -> str:
        unique_id: str = str(uuid.uuid4())
        self.write(f"MOVE {axis},{target},{unique_id}")
        return unique_id

    def status(self, controller: int | None = None) -> int:
        if controller is None:
            return self.query_int("STATUS?")
        else:
            return self.query_int(f"STATUS? {controller}")

    def wait_motion_finish(self, unique_id: str):
        while not bool(self.query_int(f"FIN? {unique_id}")):
            time.sleep(0.01)

    def clear_uid(self, unique_id: str):
        self.write(f"CLR {unique_id}")

    def wait_busy(self, axis: str | int | None = None):
        if axis is None:
            controller_idx = None
        else:  # axis name str | digit-like str | int
            if isinstance(axis, str):
                if axis.isdigit():
                    axis = int(axis)
                else:
                    names: tuple[str] = self.query_sequence("NAME?")
                    try:
                        axis = names.index(axis) + 1
                    except ValueError:
                        print("Axis not found")
                        return
            controller_idx = (axis - 1) // 3
        while self.status(controller_idx) == MMStatus.Moving:
            time.sleep(0.005)


class _PiezoMotor(Motor):
    """Base class for all piezomotors."""

    enabled: bool = True
    fix_delta: bool = False
    delta: float = 0.1
    PORT: int = 42625
    AXIS: str | int | None = None  # motor name

    def __init__(self) -> None:
        super().__init__()
        self.client = ManiClient(port=self.PORT)

    def refresh_state(self):
        self.enabled: bool = self.client.enabled(self.AXIS)

    def pre_motion(self):
        self.client.connect()

        # Get bounds (mm)
        self.minimum, self.maximum = self.client.bounds(self.AXIS)

        # Get tolerance (mm)
        self.tolerance = self.client.abs_tolerance(self.AXIS)

    def move(self, target: float) -> float:
        self.refresh_state()
        if not self.enabled:
            print("ERROR: AXIS NOT FOUND")
            # TODO: add some kind of motor exception handling to sescontrol

        # Send move command
        unique_id: str = self.client.request_move(self.AXIS, target)
        print(f"requested move, uid {unique_id}")

        # Wait for motion finish
        self.client.wait_motion_finish(unique_id)
        print("motion finished")


        self.client.clear_uid(unique_id)
        print("uid cleared")

        # get final position
        # return self._get_pos(self.AXIS)

        # log the target position instead of the real position, target position should
        # be added to data header
        return target

    def post_motion(self):
        self.client.disconnect()


class X(_PiezoMotor):
    AXIS = "X"


class Y(_PiezoMotor):
    AXIS = "Y"


class Z(_PiezoMotor):
    AXIS = "Z"


class Polar(_PiezoMotor):
    AXIS = "Polar"


class Tilt(_PiezoMotor):
    AXIS = "Tilt"


class Azi(_PiezoMotor):
    AXIS = "Azi"


class Beam(_PiezoMotor):
    beam_incidence: float = math.radians(50)

    def refresh_state(self):
        self.enabled: bool = self.client.enabled("X") and self.client.enabled("Y")

    def pre_motion(self):
        self.client.connect()

        # get bounds (mm)
        xmin, xmax = self.client.bounds("X")
        ymin, ymax = self.client.bounds("Y")

        # get current position
        self.client.wait_busy()
        self.x0, self.y0 = self.client.pos("X"), self.client.pos("Y")

        # get motor limits
        self.minimum = max(
            (xmin - self.x0) / math.sin(self.beam_incidence),
            (ymin - self.y0) / math.cos(self.beam_incidence),
        )
        self.maximum = min(
            (xmax - self.x0) / math.sin(self.beam_incidence),
            (ymax - self.y0) / math.cos(self.beam_incidence),
        )

    def move(self, target: float) -> float:
        xtarget = self.x0 + target * math.sin(self.beam_incidence)
        ytarget = self.y0 + target * math.cos(self.beam_incidence)

        # send x move command
        uid_x: str = self.client.request_move("X", xtarget)
        # send y move command
        uid_y: str = self.client.request_move("Y", ytarget)

        self.client.wait_motion_finish(uid_x)
        self.client.wait_motion_finish(uid_y)

        return target

    def post_motion(self, reset: bool = True):
        if reset:
            # go back to initial position
            self.client.request_move("X", self.x0)
            self.client.request_move("Y", self.y0)
        self._disconnect()
