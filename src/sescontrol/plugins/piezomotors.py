import enum
import math
import time

import zmq

from . import Motor


class MMStatus(enum.IntEnum):
    Moving = 1
    Done = 2
    Aborted = 3
    Error = 4


class _PiezoMotor(Motor):
    """Base class for all piezomotors."""

    enabled = True
    fix_delta = False
    delta = 0.1
    PORT: int = 42625
    AXIS: str | None = None  # motor name

    def pre_motion(self):
        self._connect()

        # get bounds (mm)
        self.minimum = self._query_float(f"? MIN {self.AXIS}")
        self.maximum = self._query_float(f"? MAX {self.AXIS}")

        # get tolerance (mm)
        self.tolerance = self._query_float(f"? TOL {self.AXIS}")

    def move(self, target: float) -> float:
        # send move command
        self.socket.send(f"MOVE {self.AXIS} {target}".encode())
        self.socket.recv()

        # check if within tolerance

        # may be outside tolerance due to noise level... skip check and rely on move finish
        # this will only work for single controller, single motor scan, fix later

        # while True:
        #     time.sleep(0.01)
        #     if abs(self._get_pos(self.AXIS) - target) < self.tolerance:
        #         break

        # wait for motion to completely finish
        self._wait_move_finish()  # this line may not be necessary
        pos = self._get_pos(self.AXIS)

        print(pos, target, abs(pos-target), self.tolerance)

        # get final position
        return self._get_pos(self.AXIS)

    def post_motion(self):
        self._disconnect()

    def _disconnect(self):
        self.socket.close()

    def _connect(self):
        context = zmq.Context.instance()
        if not context:
            context = zmq.Context()
        self.socket = context.socket(zmq.REQ)
        self.socket.connect(f"tcp://localhost:{self.PORT}")

    def _wait_move_finish(self):
        while True:
            self.socket.send(b"? STATUS")
            msg = int(self.socket.recv().decode("utf-8"))
            if int(msg) != MMStatus.Moving:
                return

    def _query_float(self, cmd: str) -> float:
        self.socket.send(cmd.encode())
        return float(self.socket.recv().decode())

    def _get_pos(self, axis: str) -> float:
        return self._query_float(f"? {axis}")


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

    def pre_motion(self):
        self._connect()

        # get bounds (mm)
        xmin = self._query_float("? MIN X")
        xmax = self._query_float("? MAX X")
        ymax = self._query_float("? MAX Y")
        ymin = self._query_float("? MIN Y")

        # get current position
        self._wait_move_finish()
        self.x0 = self._get_pos("X")
        self.y0 = self._get_pos("Y")

        # get motor limits
        self.minimum = max(
            (xmin - self.x0) / math.sin(self.beam_incidence),
            (ymin - self.y0) / math.cos(self.beam_incidence),
        )
        self.maximum = min(
            (xmax - self.x0) / math.sin(self.beam_incidence),
            (ymax - self.y0) / math.cos(self.beam_incidence),
        )

        # get tolerance (mm)
        self.xtol = self._query_float("? TOL X")
        self.ytol = self._query_float("? TOL Y")

    def move(self, target: float) -> float:
        xtarget = self.x0 + target * math.sin(self.beam_incidence)
        ytarget = self.y0 + target * math.cos(self.beam_incidence)

        # send x move command
        self.socket.send(f"MOVE X {xtarget}".encode())
        self.socket.recv()

        # send y move command
        self.socket.send(f"MOVE Y {ytarget}".encode())
        self.socket.recv()

        # check if both within tolerance
        # while True:
        #     time.sleep(0.01)
        #     if abs(self._get_pos("X") - target) < self.xtol:
        #         if abs(self._get_pos("Y") - target) < self.ytol:
        #             break

        # wait for motion to completely finish
        self._wait_move_finish()  # this line may not be necessary

        # get final position
        return target

    def post_motion(self, reset: bool = True):
        if reset:
            # go back to initial position
            self.socket.send(f"MOVE X {self.x0}".encode())
            self.socket.recv()
            self.socket.send(f"MOVE Y {self.y0}".encode())
            self.socket.recv()
        self._disconnect()
