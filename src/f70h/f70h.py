import logging

import pyvisa

log = logging.getLogger("F70H")

F70H_STATE = {
    0: "Local Off",
    1: "Local On",
    2: "Remote Off",
    3: "Remote On",
    4: "Cold Head Run",
    5: "Cold Head Pause",
    6: "Fault Off",
    7: "Oil Fault Off",
}

F70H_ALARM_BITS = {
    "Motor Temperature": 1,
    "Phase Sequence/Fuse": 2,
    "Helium Temperature": 3,
    "Water Temperature": 4,
    "Water Flow": 5,
    "Oil Level": 6,
    "Pressure": 7,
}


class F70HInstrument:
    def __init__(self, resource_name: str):
        self.instrument = pyvisa.ResourceManager().open_resource(
            resource_name, baud_rate=9600
        )
        self.instrument.write_termination = "\r"
        self.instrument.read_termination = "\r"

    @property
    def temperature(self) -> tuple[int, int, int]:
        # He discharge, water outlet, water inlet temperature in degrees C
        return tuple(int(t) for t in self.query("TEA")[:3])

    @property
    def pressure(self) -> int:
        # Compressor return pressure in psig
        return int(self.query("PR1")[0])

    @property
    def status(self) -> str:
        return f"{int(self.query('STA')[0], 16):0>16b}"

    @property
    def operating_hours(self) -> float:
        return float(self.query("ID1")[1])

    def query(self, cmd: str):
        return parse_message(self.instrument.query(make_command(cmd)))

    def turn_on(self) -> None:
        self.query("ON1")

    def turn_off(self) -> None:
        self.query("OFF")

    def reset(self) -> None:
        self.query("RST")

    def check_alarms(self) -> None:
        bits = self.status
        for k, v in F70H_ALARM_BITS.items():
            if bits[-v - 1] == "1":
                log.error(f"{k} alarm")


# Some code adapted from https://github.com/TUM-E21-ThinFilms/Sumitomo-F70H
def _compute_checksum(data) -> int:
    crcmask = 0xA001
    i = 0
    ln = 0
    crc = 0xFFFF
    while ln < len(data):
        crc = (0x0000 | (data[ln] & 0xFF)) ^ crc
        while i < 8:
            lsb = crc & 0x1
            crc = crc >> 1
            if lsb == 1:
                crc = crc ^ crcmask
            i = i + 1
        i = 0
        ln = ln + 1
    return crc


def checksum_message(message: str) -> str:
    checksum = _compute_checksum([ord(s) for s in message])
    return f"{checksum:#06x}"[2:].upper()


def make_command(command: str) -> str:
    message = ("$" + command).upper()
    return message + checksum_message(message)


def parse_message(message: str) -> list[str]:
    data = message[5:-5]

    checksum = message[-4:]
    checksum_msg = checksum_message(message[:-4])

    if checksum != checksum_msg:
        log.error(
            f"Checksum error for {message[1:4]}: {checksum} != {checksum_msg}, received {data}"
        )
        return None

    return data.split(",")
