"""Loads and parses attributes from shared memory."""

import datetime
import logging
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

MANIPULATOR_AXES: tuple[str, ...] = ("ch1", "ch2", "ch3", "ch4", "ch5", "ch6")


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


def get_pressure_list() -> list[str]:
    return [
        np.format_float_scientific(v, 3) for v in get_shared_array("Pressures", 3, "f4")
    ]


def get_position_list() -> list[str]:
    return [str(np.round(v, 4)) for v in get_shared_array("MotorPositions", 6, "f8")]


def get_temperature_list() -> list[str]:
    return [
        str(v) for v in get_shared_array("Temperatures", len(TEMPERATURE_KEYS), "f8")
    ]


def get_seqstart() -> datetime.datetime:
    return datetime.datetime.fromtimestamp(get_shared_float("seq_start"))


def get_pressure_dict() -> dict[str, str]:
    return dict(
        zip(
            ("torr_main", "torr_middle", "torr_loadlock"),
            get_pressure_list(),
            strict=True,
        )
    )


def get_position_dict() -> dict[str, str]:
    return dict(zip(MANIPULATOR_AXES, get_position_list(), strict=True))


def get_temperature_dict() -> dict[str, str]:
    return dict(zip(TEMPERATURE_KEYS, get_temperature_list(), strict=True))


def get_seqstart_dict() -> dict[str, str]:
    return {"seq_start": get_seqstart().isoformat()}


def get_slit_dict() -> dict[str, str]:
    idx = get_shared_int("slit_idx")
    return {
        "slit_number": str(SLIT_TABLE[idx][0]),
        "slit_width": str(SLIT_TABLE[idx][1]),
        "slit_aperture": str(SLIT_TABLE[idx][2]),
    }


def get_attribute_dict() -> dict[str, str]:
    attrs = {"attrs_time": datetime.datetime.now().isoformat()}
    for fn in (
        get_seqstart_dict,
        get_temperature_dict,
        get_slit_dict,
        get_position_dict,
        get_pressure_dict,
    ):
        try:
            d = fn()
        except Exception:
            log.exception("Getting attribute from shared memory failed")
        else:
            attrs |= d
    return attrs


def get_header() -> str:
    return dict_to_header(get_attribute_dict())
