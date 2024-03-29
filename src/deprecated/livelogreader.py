import os
import shutil
import tempfile

CRYO_LOG: str = "D:/Cryocooler_Log/DoNotTouch/LoggingNow.csv"
MG15_LOG: str = "D:/MG15_Log/Don'tTouch/realtimelog.csv"

CRYO_COLS: dict[int, str] = {
    # 0: "time",
    2: "1K Cold finger",
    3: "Sample stage",
    4: "He pump",
    5: "4K plate",
    10: "2K plate",
    11: "Tilt bracket",
}
MG15_COLS: dict[int, str] = {
    # 0: "time",
    1: "IG Main",
    2: "IG Middle",
}


def get_last_row(path) -> str:
    with tempfile.TemporaryDirectory() as tmpdirname:
        result = None
        while result is None:
            try:
                tmp = shutil.copy(path, tmpdirname)
                with open(tmp, "rb") as f:
                    f.seek(-2, os.SEEK_END)
                    while f.read(1) != b"\n":
                        f.seek(-2, os.SEEK_CUR)
                    result = f.readline().decode().rstrip()
            except OSError:  # empty file, retry until it is no longer empty
                continue
    return result


def get_temperature() -> dict[str, str]:
    dat = get_last_row(CRYO_LOG).split(",")
    return {name: dat[idx] for idx, name in CRYO_COLS.items()}


def get_pressure() -> dict[str, str]:
    dat = get_last_row(MG15_LOG).split(",")
    return {name: dat[idx] for idx, name in MG15_COLS.items()}
