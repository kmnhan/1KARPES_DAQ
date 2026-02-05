from __future__ import annotations

import contextlib
import time
import uuid
from typing import Self

import numpy as np
import zmq

from erpes_daq.sescontrol.plugins import Motor

OPTICS_PORT: int = 42633


class _OpticsClientSingleton:
    """Base class for singletons.

    This class implements the singleton pattern, ensuring that only one instance of the
    class is created and used throughout the application.
    """

    __instance: _OpticsClientSingleton | None = None

    def __new__(cls):
        if not isinstance(cls.__instance, cls):
            cls.__instance = super().__new__(cls)
        return cls.__instance

    @classmethod
    def instance(cls) -> Self:
        """Return the registry instance."""
        return cls()


class OpticsClient(_OpticsClientSingleton):
    def __init__(self):
        self.connected: bool = False

    def connect(self):
        if not self.connected:
            context = zmq.Context.instance()
            if not context:
                context = zmq.Context()
            self.socket = context.socket(zmq.PAIR)
            print("socket prepared, connecting...")
            self.socket.connect(f"tcp://localhost:{OPTICS_PORT}")
            print("socket connected!")
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
        with self.connection() as soc:
            soc.send_string(cmd)
            return soc.recv_string()

    def write(self, cmd: str) -> None:
        with self.connection() as soc:
            soc.send_string(cmd)

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

    def request_move_pol(self, pol_num: int) -> str:
        unique_id: str = str(uuid.uuid4())
        self.write(f"MOVEPOL {pol_num},{unique_id}")
        return unique_id

    def request_move_linpol(self, angle_deg: float) -> str:
        unique_id: str = str(uuid.uuid4())
        self.write(f"MOVELINPOL {angle_deg},{unique_id}")
        return unique_id

    # def status(self, controller: int | None = None) -> int:
    #     if controller is None:
    #         return self.query_int("STATUS?")
    #     return self.query_int(f"STATUS? {controller}")

    def wait_motion_finish(self, unique_id: str):
        while not bool(self.query_int(f"CMD? {unique_id}")):
            time.sleep(0.5)

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
    minimum: float = -1
    maximum: float = 2
    delta: float = 2

    def refresh_state(self):
        self.enabled: bool = self.client.enabled(0)
        # Allow without QWP

    def pre_motion(self):
        self.client.connect()

    def move(self, target: float) -> float:
        target_int: int = round(target)
        print(f"target {target_int}")
        if target_int not in (-1, 0, 1, 2):
            print("terminating with nan, invalid pol input")
            return np.nan

        qwp_enabled: bool = self.client.enabled(1)

        print(f"qwp enabled: {qwp_enabled}")

        if not qwp_enabled:
            if target_int == -1:
                # RCP to LH
                target_int = 0
            elif target_int == 1:
                # LCP to LV
                target_int = 2

        print("target_integer", target_int)

        uid = self.client.request_move_pol(target_int)
        self.client.wait_motion_finish(uid)
        self.client.clear_uid(uid)

        print("sleeping 0.2s to ensure beam stability")
        time.sleep(0.2)

        return target

    def post_motion(self):
        self.client.disconnect()


class LinearPol(_MotorizedOptic):
    minimum: float = -90.0
    maximum: float = 90.0
    delta: float = 5.0

    def refresh_state(self):
        self.enabled: bool = self.client.enabled(0)

    def pre_motion(self):
        self.client.connect()

    def move(self, target: float) -> float:
        target = float(target)
        if not (-90.0 <= target <= 90.0):
            print("terminating with nan, invalid angle input")
            return np.nan

        uid = self.client.request_move_linpol(float(target))
        self.client.wait_motion_finish(uid)
        self.client.clear_uid(uid)

        print("sleeping 0.2s to ensure beam stability")
        time.sleep(0.2)

        return target

    def post_motion(self):
        self.client.disconnect()
