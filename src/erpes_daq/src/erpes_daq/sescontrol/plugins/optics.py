from __future__ import annotations

import contextlib
import time
import uuid
from typing import Self

import numpy as np
import zmq

from erpes_daq.sescontrol.plugins import Motor

OPTICS_PORT: int = 42633


class _SingletonBase:
    """Base class for singletons.

    This class implements the singleton pattern, ensuring that only one instance of the
    class is created and used throughout the application.
    """

    __instance: _SingletonBase | None = None

    def __new__(cls):
        if not isinstance(cls.__instance, cls):
            cls.__instance = super().__new__(cls)
        return cls.__instance

    @classmethod
    def instance(cls) -> Self:
        """Return the registry instance."""
        return cls()


class OpticsClient(_SingletonBase):
    def __init__(self):
        self.connected: bool = False

    def connect(self):
        if not self.connected:
            context = zmq.Context.instance()
            if not context:
                context = zmq.Context()
            self.socket = context.socket(zmq.PAIR)
            self.socket.connect(f"tcp://localhost:{OPTICS_PORT}")
            self.connected = True

    def disconnect(self):
        if self.connected:
            self.socket.close()
            self.connected = False

    @contextlib.contextmanager
    def connection(self):
        """Context manager for socket connection.

        If the connection is already established, the existing socket is returned and
        nothing is done on exit. Otherwise, the socket is closed after the block is
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
            return self.socket.recv_string()

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

    def request_move(self, axis: str | int, target: float) -> str:
        unique_id: str = str(uuid.uuid4())
        self.write(f"MOVE {axis},{target},{unique_id}")
        return unique_id

    # def status(self, controller: int | None = None) -> int:
    #     if controller is None:
    #         return self.query_int("STATUS?")
    #     return self.query_int(f"STATUS? {controller}")

    def wait_motion_finish(self, unique_id: str):
        while not bool(self.query_int(f"CMD? {unique_id}")):
            time.sleep(0.01)

    def clear_uid(self, unique_id: str):
        self.write(f"CLR {unique_id}")


class _MotorizedOptic(Motor):
    """Base class for all motorized optics."""

    enabled: bool = True
    fix_delta: bool = False
    delta: float = 45.0
    AXIS: int | None = None  # motor index

    def __init__(self) -> None:
        super().__init__()
        self.client = OpticsClient()

    def refresh_state(self):
        self.enabled: bool = self.client.enabled(self.AXIS)

    def pre_motion(self):
        self.client.connect()

        # Get bounds (mm)
        self.minimum, self.maximum = self.client.bounds(self.AXIS)

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

        return target

    def post_motion(self):
        self.client.disconnect()


class HWP(_MotorizedOptic):
    AXIS = 0


class QWP(_MotorizedOptic):
    AXIS = 1


class Pol(_MotorizedOptic):
    # -1 0 1 2
    # rc lh lc lv

    minimum: float = -1
    maximum: float = 2
    delta: float = 2

    pol_to_angles: dict[int, tuple[float, float]] = {
        -1: (0.0, 45.0),
        0: (45.0, 0.0),
        1: (45.0, 45.0),
        2: (0.0, 0.0),
    }

    def refresh_state(self):
        self.enabled: bool = self.client.enabled(0)
        # Allow without QWP

    def pre_motion(self):
        self.client.connect()

    def move(self, target: float) -> float:
        target_int: int = round(target)
        if target_int not in self.pol_to_angles:
            return np.nan

        qwp_enabled: bool = self.client.enabled(1)

        if not qwp_enabled:
            if target_int == -1:
                # RCP to LH
                target_int = 0
            elif target_int == 0:
                # LCP to LV
                target_int = 2

        hwp, qwp = self.pol_to_angles[target_int]

        uid_hwp: str = self.client.request_move(0, hwp)
        if qwp_enabled:
            uid_qwp: str = self.client.request_move(1, qwp)

        self.client.wait_motion_finish(uid_hwp)

        if qwp_enabled:
            self.client.wait_motion_finish(uid_qwp)

        return target

    def post_motion(self):
        self.client.disconnect()
