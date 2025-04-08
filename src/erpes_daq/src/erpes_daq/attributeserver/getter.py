"""Loads and parses attributes from shared memory."""

import datetime
import logging
import socket
import struct
from multiprocessing import shared_memory
from typing import Any

import numpy as np

log = logging.getLogger("attrs")

SLIT_TABLE: tuple[tuple[int, float, bool], ...] = (
    (100, 0.05, False),
    (200, 0.1, False),
    (300, 0.2, False),
    (400, 0.3, False),
    (500, 0.2, True),
    (600, 0.3, True),
    (700, 0.5, True),
    (800, 0.8, True),
    (900, 1.5, True),
)

TEMPERATURE_KEYS: tuple[str, ...] = (
    "TA",
    "TB",
    "TC",
    "TD",
    "T1",
    "T2",
    "T3",
    "T4",
    "T5",
    "T6",
    "T7",
    "T8",
    "T0",
)

OPTICS_KEYS: tuple[str, ...] = ("hwp", "qwp")

MANIPULATOR_AXES: tuple[str, ...] = ("ch1", "ch2", "ch3", "ch4", "ch5", "ch6")

PORT_POSITION: int = 18001
PORT_PRESSURE: int = 18002
PORT_TEMPERATURE: int = 18003

SERVER_IP: str = "192.168.0.193"


def get_from_server(
    port: int, size: int, double: bool = True, timeout: float = 5.0
) -> list[np.float32 | np.float64]:
    if double:
        fmt = f"{size}d"
        nbytes = size * 8
    else:
        fmt = f"{size}f"
        nbytes = size * 4

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.settimeout(timeout)

    # Connect to the server
    client_socket.connect((SERVER_IP, port))

    # Receive the data from the server
    data = client_socket.recv(nbytes)

    if data == b"":
        raise ValueError("Server on monitoring PC failed to read shared memory")
    return list(struct.unpack(fmt, data))


def get_shm_or_remote(shm_func, port: int, size: int, double: bool = True):
    """Fetch from shared memory if available.

    First, tries to fetch from shared memory. If the shared memory is not available,
    fetches fetches from the server on the monitoring computer. The servers running on
    the monitoring computer are in `dell_server.py`.
    """
    try:
        return shm_func()
    except FileNotFoundError as e:
        try:
            return get_from_server(port, size, double=double)
        except (TimeoutError, ValueError) as ee:
            raise e from ee


def dict_to_header(d: dict[str, str]) -> str:
    return "".join([f"{k}={v}\n" for k, v in d.items()])


def get_shared_list(name: str) -> list[Any]:
    sl = shared_memory.ShareableList(name=name)
    out = list(sl)
    sl.shm.close()
    return out


def get_shared_int(name: str) -> int:
    shm = shared_memory.SharedMemory(name=name)
    out = int(shm.buf[0])
    shm.close()
    return out


def get_shared_array(name: str, num: int, dtype: str) -> list:
    shm = shared_memory.SharedMemory(name=name)
    out = list(np.ndarray((num,), dtype=dtype, buffer=shm.buf))
    shm.close()
    return out


def get_shared_float(name: str) -> float:
    shm = shared_memory.SharedMemory(name=name)
    out = float(np.ndarray((1,), dtype="f8", buffer=shm.buf)[0])
    shm.close()
    return out


def get_pressures_shm() -> list[np.float32]:
    return get_shared_array("Pressures", 3, "f4")


def get_positions_shm() -> list[np.float64]:
    return get_shared_array("MotorPositions", len(MANIPULATOR_AXES), "f8")


def get_temperatures_shm() -> list[np.float64]:
    return get_shared_array("Temperatures", len(TEMPERATURE_KEYS), "f8")


def get_pressures() -> list[np.float32]:
    return get_shm_or_remote(get_pressures_shm, PORT_PRESSURE, 3, double=False)


def get_positions() -> list[np.float64]:
    return get_shm_or_remote(get_positions_shm, PORT_POSITION, len(MANIPULATOR_AXES))


def get_temperatures() -> list[np.float64]:
    return get_shm_or_remote(
        get_temperatures_shm, PORT_TEMPERATURE, len(TEMPERATURE_KEYS)
    )


def get_pressure_strings() -> list[str]:
    return [np.format_float_scientific(v, 3) for v in get_pressures()]


def get_position_strings() -> list[str]:
    return [str(np.round(v, 4)) for v in get_positions()]


def get_temperature_strings() -> list[str]:
    return [str(v) for v in get_temperatures()]


def get_seqstart() -> datetime.datetime:
    return datetime.datetime.fromtimestamp(get_shared_float("seq_start"))


def get_pressure_dict() -> dict[str, str]:
    return dict(
        zip(
            ("torr_main", "torr_middle", "torr_loadlock"),
            get_pressure_strings(),
            strict=True,
        )
    )


def get_position_dict() -> dict[str, str]:
    return dict(zip(MANIPULATOR_AXES, get_position_strings(), strict=True))


def get_temperature_dict() -> dict[str, str]:
    return dict(zip(TEMPERATURE_KEYS, get_temperature_strings(), strict=True))


def get_seqstart_dict() -> dict[str, str]:
    return {"seq_start": get_seqstart().isoformat()}


def get_slit_dict() -> dict[str, str]:
    idx = get_shared_int("slit_idx")
    return {
        "slit_number": str(SLIT_TABLE[idx][0]),
        "slit_width": str(SLIT_TABLE[idx][1]),
        "slit_aperture": str(SLIT_TABLE[idx][2]),
    }


def get_waveplate_dict() -> dict[str, str]:
    try:
        ang_list: list[np.float64] = get_shared_array("Optics", len(OPTICS_KEYS), "f8")
    except FileNotFoundError:
        ang_list = [np.nan] * len(OPTICS_KEYS)

    return dict(zip(OPTICS_KEYS, [np.round(v, 3) for v in ang_list], strict=True))


def get_attribute_dict() -> dict[str, str]:
    attrs = {"attrs_time": datetime.datetime.now().isoformat()}
    for fn in (
        get_seqstart_dict,
        get_temperature_dict,
        get_slit_dict,
        get_position_dict,
        get_pressure_dict,
        get_waveplate_dict,
    ):
        try:
            d = fn()
        except Exception:
            log.exception(
                "Getting attribute with function %s from shared memory failed",
                fn.__name__,
            )
        else:
            attrs |= d
    return attrs


def get_header() -> str:
    return dict_to_header(get_attribute_dict())
