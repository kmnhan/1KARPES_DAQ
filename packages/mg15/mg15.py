import datetime
import struct
import threading
import time

from pymodbus.client import ModbusTcpClient
from qtpy import QtCore

GAUGE_STATE: dict[int, str] = {
    0: "Status OK",
    1: "Wait for emission",
    2: "Emission OFF",
    3: "Short cathode",
    4: "Pressure too high (out of vacuum gauge range)",
    5: "Anode voltage failure",
    6: "Bias voltage failure",
    7: "Reflector voltage failure",
    8: "Degas failure",
    9: "Gauge not calibrated",
    10: "No emission",
    11: "Offset calibration",
    12: "Low vacuum (out of vacuum gauge range)",
    13: "High vacuum (out of vacuum gauge range)",
    14: "There is no meaningful vacuum value to display",
    15: "No hardware for passive vacuum gauge",
    16: "Passive gauge EEPROM failure",
    17: "Filament failure",
    18: "Degassing",
    19: "Sensor break for active vacuum gauge",
}
SETPOINT_SOURCE: dict[int, str] = {
    1: "Vacuum channel 1",
    2: "Vacuum channel 2",
    3: "Vacuum channel 3",
    4: "Vacuum channel 4",
    5: "Vacuum channel 5",
    6: "Vacuum channel 6",
    7: "Vacuum channel 7",
    100: "Always ON",
    101: "Always OFF",
}
ACTIVE_GAUGE_TYPE: dict[int, str] = {
    0: "CTR90",
    1: "TTR90",
    2: "TTR211",
    3: "PTR225",
    4: "ITR90",
    5: "ITR100",
    6: "MKS870",
    7: "PTR90",
    8: "ANALOG_IN",
    9: "MKS_937A",
    10: "PG105",
    11: "MG13_14",
    12: "PKR251/360/361",
    13: "PCR280/TPR28x",
    14: "ATMION",
    15: "User Defined Vacuum Gauge",
    16: "IKR360/361",
}
PASSIVE_GAUGE_TYPE: dict[int, str] = {
    0: "UHV8A",
    1: "IE514",
    2: "IE414",
    3: "UHV24",
    4: "UHV24p",
    5: "MKS274",
    6: "NR_F_UHV",
    7: "G8130",
    8: "User Defined Passive Vacuum Gauge",
    9: "BARION basic II",
}
MBAR_TO_TORR: float = 76000 / 101325
MBAR_TO_PA: float = 100.0
MBAR_TO_PSIA: float = MBAR_TO_PA * (0.0254**2) / (0.45359237 * 9.80665)


def uint16_to_boolean_array(uint16_value) -> list[bool]:
    # Convert uint16 to binary, remove the '0b' prefix, and pad with zeros
    return [bit == "1" for bit in f"{uint16_value:b}".zfill(16)]


def uint8_to_ieee754(array) -> float:
    # Convert two uint16 into single uint32, then unpack to float (IEEE-754)
    return struct.unpack(">f", struct.pack(">I", (array[0] << 16) | array[1]))[0]


class MG15Connection(QtCore.QThread):
    sigRead = QtCore.Signal(object, object, bool)

    def __init__(self, address: str):
        super().__init__()
        self.set_address(address)
        self.stopped = threading.Event()

    @QtCore.Slot(str)
    def set_address(self, address: str):
        if self.isRunning():
            self.mutex.lock()
        self.address = address
        if self.isRunning():
            self.mutex.unlock()

    def run(self):
        self.mutex = QtCore.QMutex()
        self.stopped.clear()

        client = ModbusTcpClient(self.address, port=502)  # Create client object
        client.connect()  # connect to device, reconnect automatically

        while not self.stopped.is_set():
            registers: list[int] = client.read_holding_registers(0, 125).registers
            registers += client.read_holding_registers(125, 76).registers
            remote_enabled: bool = bool(
                client.read_holding_registers(1100, 1).registers[0]
            )

            self.sigRead.emit(datetime.datetime.now(), registers, remote_enabled)
            time.sleep(0.175)

        client.close()  # Disconnect device


class MG15(QtCore.QObject):
    sigUpdated = QtCore.Signal()

    def __init__(self, address: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connection = MG15Connection(address)
        self.connection.sigRead.connect(self.update)
        # self.connect()

    @QtCore.Slot(object, object, bool)
    def update(self, updatetime: datetime.datetime, registers: list[int], remote: bool):
        self.updated: datetime.datetime = updatetime
        self.registers: list[int] = registers
        self.remote_enabled: bool = remote
        self.sigUpdated.emit()

    @property
    def states(self) -> list[str]:
        return [self.get_state(ch) for ch in range(1, 7 + 1)]

    @property
    def setpoints(self) -> list[tuple[float, float]]:
        return [self.get_setpoint(num) for num in range(1, 10 + 1)]

    @property
    def setpoints_enabled(self) -> list[bool]:
        return uint16_to_boolean_array(self.registers[21])[::-1][:10]

    @property
    def setpoints_source(self) -> list[str]:
        return [self.get_setpoint_source(num) for num in range(1, 10 + 1)]

    def pressures(self, unit: str) -> list[float]:
        return [self.get_pressure(ch, unit) for ch in range(1, 7 + 1)]

    def get_pressure(self, channel: int, unit: str) -> float:
        return getattr(self, f"get_pressure_{unit}")(channel)

    def get_pressure_mbar(self, channel: int) -> float:
        if self.get_state(channel) == GAUGE_STATE[0]:
            idx = channel - 1
            return uint8_to_ieee754(self.registers[3 * idx : 3 * idx + 2])
        else:
            return float("nan")

    def get_pressure_torr(self, channel: int) -> float:
        return self.get_pressure_mbar(channel) * MBAR_TO_TORR

    def get_pressure_pa(self, channel: int) -> float:
        return self.get_pressure_mbar(channel) * MBAR_TO_PA

    def get_pressure_psia(self, channel: int) -> float:
        return self.get_pressure_mbar(channel) * MBAR_TO_PSIA

    def get_state(self, channel: int) -> str:
        idx = channel - 1
        return GAUGE_STATE[self.registers[3 * idx + 2]]

    def get_emission(self, channel: int) -> bool:
        idx = channel - 1
        if idx < 4:
            return self.registers[72 + idx * 20]
        else:
            return self.registers[149 + (idx - 4) * 17]

    def get_setpoint(self, number: int) -> tuple[float, float]:
        idx = number - 1
        vals = self.registers[4 * idx + 22 : 4 * idx + 26]
        return uint8_to_ieee754(vals[:2]), uint8_to_ieee754(vals[2:])

    def get_setpoint_enabled(self, number: int) -> bool:
        return self.setpoints_enabled[number - 1]

    def get_setpoint_source(self, number: int) -> str:
        return SETPOINT_SOURCE[self.registers[62 + number - 1]]

    def set_address(self, address: str):
        self.connection.set_address(address)

    def connect(self):
        if not self.connection.isRunning():
            self.connection.start()

    def disconnect(self):
        self.connection.stopped.set()
        self.connection.wait()

    def reconnect(self):
        self.disconnect()
        self.connect()
