import logging
import time

import pyftdi.ftdi
import usb.core
import usb.util

log = logging.getLogger("elliptec")


def build_message(address: int, command: str, data: str | bytes | None = None) -> bytes:
    """Build a message to be sent to the device.

    Message starts with the address of the device (1 byte), followed by the command to
    be executed (2 bytes), optionally followed by data (n bytes).

    If data is a string, it will be encoded to bytes using ASCII encoding.
    """
    if address < 0 or address > 15:
        raise ValueError("Address must be in the range 0-15.")
    message = f"{address:X}{command}".encode("ascii")
    if data:
        if isinstance(data, str):
            data = data.encode("ascii")
        message += data
    return message


class ElliptecFtdiDeviceBase(pyftdi.ftdi.Ftdi):
    """Base class for communicating with Elliptec devices over FTDI.

    A child class that implements the specific commands for the device can be found in
    the elliptec.commands module.

    """

    _device: usb.core.Device

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def connect(self) -> None:
        """Connect to the device."""
        self._device = usb.core.find(idVendor=0x0403, idProduct=0x6015)

        if self._device is None:
            raise RuntimeError("USB device not found")

        self.open_from_device(self._device)

        self.set_baudrate(9600)
        self.set_line_property(bits=8, stopbit=1, parity="N")

        # Pre purge dwell 50ms
        time.sleep(0.05)

        # Purge RX and TX buffers
        self.purge_buffers()

        # Post purge dwell 50ms
        time.sleep(0.05)

        # Reset the device
        self.reset()

        # No flow control
        self.set_flowctrl("")

        log.info("Connected to device")

    def disconnect(self) -> None:
        """Disconnect from the device."""
        self.close()
        usb.util.dispose_resources(self._device)
        log.info("Disconnected from device")

    def write_command(
        self, address: int, command: str, data: str | bytes | None = None
    ):
        time.sleep(0.05)
        self.purge_buffers()
        time.sleep(0.05)
        message = build_message(address, command, data)

        log.debug("Writing command: %s", message)
        self.write_data(message)

    def read_command(self, timeout: float = 2.0) -> tuple[int, str, bytes]:
        end_time: float = time.perf_counter() + timeout
        response: bytes = b""
        while time.perf_counter() < end_time:
            # Try to read one byte
            chunk = self.read_data(1)
            if chunk:
                response += chunk
                if response.endswith(b"\r\n"):  # Response is complete
                    log.debug("Read response: %s", response)
                    return (
                        int(response[:1], base=16),
                        response[1:3].decode("ascii"),
                        response[3:-2],  # Strip trailing \r\n
                    )
            else:
                # Brief sleep to avoid busy-wait
                time.sleep(0.01)
        raise TimeoutError("Response not received within the timeout period.")

    def query_command(
        self,
        address: int,
        command: str,
        data: str | bytes | None = None,
        timeout: float = 2.0,
    ) -> tuple[int, str, bytes]:
        self.write_command(address, command, data)
        return self.read_command(timeout)

    def query_command_check(
        self,
        address: int,
        command: str,
        out_command: str | list[str],
        data: str | bytes | None = None,
        timeout: float = 2.0,
    ) -> tuple[str, bytes]:
        if isinstance(out_command, str):
            out_command = [out_command]

        ret_addr, ret_cmd, response = self.query_command(
            address, command, data, timeout=timeout
        )

        if ret_addr != address:
            raise RuntimeError(
                f"Address mismatch in response: expected {address}, got {ret_addr}"
            )
        if ret_cmd not in out_command:
            raise RuntimeError(f"Unexpected command {ret_cmd} in response.")
        return ret_cmd, response
