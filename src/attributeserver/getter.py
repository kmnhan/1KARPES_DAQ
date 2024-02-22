"""Loads and parses attributes from shared memory."""

import datetime
from multiprocessing import shared_memory
from typing import Any

import numpy as np

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


def get_shared_float(name: str) -> float:
    shm = shared_memory.SharedMemory(name=name)
    out = float(np.ndarray((1,), dtype="f8", buffer=shm.buf)[0])
    shm.close()
    return out


def get_pressure_list() -> list[str]:
    return [np.format_float_scientific(v, 3) for v in get_shared_list("Pressures")]


def get_pressure_dict() -> dict[str, str]:
    return dict(zip(("torr_main", "torr_middle", "torr_loadlock"), get_pressure_list()))


def get_temperature_list() -> list[str]:
    return get_shared_list("Temperatures")


def get_temperature_dict() -> dict[str, str]:
    return {
        k: v.lstrip("+")
        for k, v in zip(
            ("TA", "TB", "TC", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T0"),
            get_temperature_list(),
        )
    }


def get_slit_dict() -> dict[str, str]:
    idx = get_shared_int("slit_idx")
    return {
        "slit_number": str(SLIT_TABLE[idx][0]),
        "slit_width": str(SLIT_TABLE[idx][1]),
        "slit_aperture": str(SLIT_TABLE[idx][2]),
    }


def get_seqstart() -> datetime.datetime:
    return datetime.datetime.fromtimestamp(get_shared_float("seq_start"))


def get_seqstart_dict() -> dict[str, str]:
    return {"seq_start": get_seqstart().isoformat()}


def get_attribute_dict() -> dict[str, str]:
    attrs = {}
    for fn in (
        get_temperature_dict,
        get_pressure_dict,
        get_slit_dict,
        get_seqstart_dict,
    ):
        try:
            d = fn()
        except FileNotFoundError as e:
            pass
            # print(f"Getting attribute from shared memory failed with error {e}")
        else:
            attrs |= d
    return attrs


def get_header() -> str:
    return dict_to_header(get_attribute_dict())
