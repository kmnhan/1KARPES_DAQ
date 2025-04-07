import binascii
import logging
import typing

import construct

from opticscontrol.elliptec.communicate import ElliptecFtdiDeviceBase
from opticscontrol.elliptec.parsers import Info, Long, MotorInfo

log = logging.getLogger("elliptec")

STATUS: dict[int, str] = {
    0: "OK",
    1: "Communication time out",
    2: "Mechanical time out",
    3: "Command error or not supported",
    4: "Value out of range",
    5: "Module isolated",
    6: "Module out of isolation",
    7: "Initializing error",
    8: "Thermal error",
    9: "Busy",
    10: "Sensor Error",
    11: "Motor Error",
    12: "Out of range",
    13: "Over Current error",
}  #: A mapping from status codes to their meanings.


MOTION_TIMEOUT: float = (
    20.0  #: The default timeout for motion commands such as move and home.
)


class ElliptecFtdiDevice(ElliptecFtdiDeviceBase):
    """Class for communicating with Elliptec devices over FTDI.

    Usage
    -----
    >>> device = ElliptecFtdiDevice()
    >>> device.connect()
    >>> device.info(0)
    >>> device.disconnect()

    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pulse_unit_cache: dict[int, int] = {}

    def info(self, address: int) -> construct.Container:
        _, _, response = self.query_command_check(address, "in", out_command="IN")
        return Info.parse(response)

    def pulse_unit(self, address: int, use_cache: bool = True) -> int:
        """Get the pulse unit of the device.

        The pulse unit is the number of pulses per mm or radian. Results are cached.

        If use_cache is False, the cache will be ignored and the value will be re-read
        from the device. The cache is updated with the new value.
        """
        if (address not in self._pulse_unit_cache) or not use_cache:
            self._pulse_unit_cache[address] = self.info(address).pulse
        return self._pulse_unit_cache[address]

    def status(self, address: int) -> int:
        """Get the status number of the device."""
        _, _, response = self.query_command_check(address, "gs", out_command="GS")
        return int(response, base=16)

    def status_text(self, address: int) -> str:
        """Get the status text of the device."""
        return STATUS.get(self.status(address), "Unknown")

    def motor1_info(self, address: int) -> int:
        """Get the motor 1 info of the device."""
        _, _, response = self.query_command_check(address, "i1", out_command="I1")
        return MotorInfo.parse(binascii.unhexlify(response))

    def isolate(self, address: int, minutes: int) -> None:
        """Isolate the device for a given number of minutes."""
        if minutes < 0 or minutes > 255:
            raise ValueError("Minutes must be between 0 and 255.")
        self.write_command(address, "is", data=f"{minutes:02X}")

    def home(
        self, address: int, direction: typing.Literal["cw", "ccw"] = "cw"
    ) -> tuple[int, int] | None:
        """Home the device.

        Direction is unused for non-rotary devices.
        """
        if direction not in ("cw", "ccw"):
            raise ValueError("Direction must be either 'cw' or 'ccw'.")

        ret_addr, ret_cmd, response = self.query_command(
            address,
            command="ho",
            data="0" if direction == "cw" else "1",
            timeout=MOTION_TIMEOUT,
        )
        if ret_cmd != "PO":
            print(f"Home command returned unexpected command {ret_cmd}.")
            return None
        return ret_addr, Long.parse(binascii.unhexlify(response))

    def move_abs(self, address: int, position: int) -> tuple[int, int] | None:
        """Move the device to an absolute position in pulses.

        Blocks until the move is complete, and returns the final position in pulses.
        """
        ret_addr, ret_cmd, response = self.query_command(
            address, command="ma", data=f"{position:08X}", timeout=MOTION_TIMEOUT
        )
        if ret_cmd != "PO":
            print(f"Move command returned unexpected command {ret_cmd}.")
            return None
        return ret_addr, Long.parse(binascii.unhexlify(response))

    def move_abs_physical(
        self, address: int, position: float
    ) -> tuple[int, float] | None:
        """Move the device to an absolute position in physical units (mm or radians)."""
        out = self.move_abs(address, round(position * self.pulse_unit(address)))
        if out is None:
            return None
        ret_addr, raw_pos = out
        return ret_addr, raw_pos / self.pulse_unit(address)

    def move_rel(self, address: int, distance: int) -> tuple[int, int]:
        """Move the device a relative distance in pulses.

        Blocks until the move is complete, and returns the final position in pulses.
        """
        ret_addr, ret_cmd, response = self.query_command(
            address, command="mr", data=f"{distance:08X}", timeout=MOTION_TIMEOUT
        )
        if ret_cmd != "PO":
            print(f"Move command returned unexpected command {ret_cmd}.")
            return None
        return ret_addr, Long.parse(binascii.unhexlify(response))

    def position(self, address: int) -> tuple[int, float]:
        """Get the position of the device in pulses."""
        ret_addr, _, response = self.query_command_check(address, "gp", out_command="PO")
        return ret_addr, Long.parse(binascii.unhexlify(response))

    def position_physical(self, address: int) -> tuple[int, float]:
        """Get the position of the device in physical units."""
        ret_addr, raw_pos = self.position(address)
        return ret_addr, raw_pos / self.pulse_unit(address)
