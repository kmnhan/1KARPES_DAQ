import contextlib
import datetime
import os
import sys
from collections.abc import Callable

import pandas as pd

if sys.platform == "darwin":
    # debug on macOS
    CRYO_DIR = "/Volumes/143.248.11.28/Logs/Cryocooler"
    MG15_DIR = "/Volumes/143.248.11.28/Logs/Pressure"
else:
    CRYO_DIR = "D:/Logs/Cryocooler"
    MG15_DIR = "D:/Logs/Pressure"


def parse_mg15_time(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s[:10] + "T" + s[11:])


def parse_mg15_time_old(s: float) -> datetime.datetime:
    return datetime.datetime.strptime(str(int(float(s))), "%y%m%d%H%M%S")


def parse_cryo_time(v: str | float) -> datetime.datetime:
    try:
        # convert labview timestamp
        return datetime.datetime.fromtimestamp(float(v) - 2082844800.0)
    except ValueError:
        return datetime.datetime.fromisoformat(v)


def datetime_to_filename(dt: datetime.datetime) -> str:
    """Return the csv file name corresponding to given input time."""
    return str(dt.year)[2:] + str(dt.month).zfill(2) + str(dt.day).zfill(2) + ".csv"


def parse_single_mg15(filename):
    """Read data from a pressure log file to a `pandas.DataFrame`."""
    try:
        return pd.read_csv(
            filename,
            header=None,
            index_col=0,
            usecols=(0, 1, 2),
            names=("Time", "IG Main", "IG Middle"),
            converters={0: parse_mg15_time},
        ).rename_axis("time")
    except pd.errors.ParserError:
        return pd.read_csv(
            filename,
            header=None,
            sep="\t",
            index_col=0,
            usecols=(0, 1, 2),
            names=("Time", "IG Main", "IG Middle"),
            converters={0: parse_mg15_time_old},
        ).rename_axis("time")


def parse_single_cryo(filename):
    """Read data from a cryocooler log file to a `pandas.DataFrame`."""
    header_rows = []
    legacy = False
    with open(filename) as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith((lines[0][:10], "Time", "Running")):
                header_rows.append(i)
        if not lines[header_rows[-1]].startswith("Time"):
            legacy = True

    # for now, discard data above the last header
    time_col = 1 if legacy else 0
    return pd.read_csv(
        filename,
        skiprows=header_rows[-1],
        index_col=0,
        header=0,
        usecols=lambda x: x not in ["Running Time (s)", "Date&Time", "Clear"],
        skip_blank_lines=True,
        converters={time_col: parse_cryo_time},
    ).rename_axis("time")


def get_log(
    startdate: datetime.datetime,
    enddate: datetime.datetime,
    directory: str,
    converter: Callable,
    error: bool = True,
) -> pd.DataFrame | None:
    """Read log files.

    Reads all log data in `directory` between `startdate` and `enddate` into a pandas
    DataFrame. The `converter` function is used to parse the log files.
    """
    dataframes = []
    for fname in map(
        datetime_to_filename, pd.date_range(start=startdate.date(), end=enddate.date())
    ):
        with contextlib.suppress(FileNotFoundError):
            dataframes.append(converter(os.path.join(directory, fname)))
    if len(dataframes) == 0:
        if error:
            raise ValueError("No log files were found in specified range.")
        return None
    return pd.concat(dataframes).sort_index()[slice(startdate, enddate)]


def get_cryocooler_log(startdate, enddate, error=False):
    return get_log(startdate, enddate, CRYO_DIR, parse_single_cryo, error=error)


def get_pressure_log(startdate, enddate, error=False):
    return get_log(startdate, enddate, MG15_DIR, parse_single_mg15, error=error)
