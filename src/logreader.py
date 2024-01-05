import datetime
import os
import sys
from collections.abc import Callable

import pandas as pd

if sys.platform == "darwin":
    # debug on macOS
    CRYO_DIR = os.path.expanduser("~/sample_logs/Cryocooler_Log")
    MG15_DIR = os.path.expanduser("~/sample_logs/MG15_Log")
else:
    CRYO_DIR = "D:/Cryocooler_Log"
    MG15_DIR = "D:/MG15_Log"


def parse_mg15_time(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s[:10] + "T" + s[11:])


def parse_mg15_time_old(s: float) -> datetime.datetime:
    return datetime.datetime.strptime(str(int(float(s))), "%y%m%d%H%M%S")


def parse_cryo_time(v: str | float) -> datetime.datetime:
    try:
        # convert labview timestamp
        return datetime.datetime.fromtimestamp(float(v) - 2082844800.0)
    except ValueError:
        # for older data, time is given in iso format
        return datetime.datetime.fromisoformat(v)


def datetime_to_filename(dt: datetime.datetime) -> str:
    """Returns the csv file name corresponding to given input time."""
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
        )
    except pd.errors.ParserError:
        return pd.read_csv(
            filename,
            header=None,
            sep="\t",
            index_col=0,
            usecols=(0, 1, 2),
            names=("Time", "IG Main", "IG Middle"),
            converters={0: parse_mg15_time_old},
        )


def parse_single_cryo(filename):
    """Read data from a cryocooler log file to a `pandas.DataFrame`."""
    header_rows = []
    with open(filename, "r") as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith(lines[0][:10]):
                header_rows.append(i)

    # for now, discard data above the last header
    return pd.read_csv(
        filename,
        skiprows=header_rows[-1],
        index_col=0,
        header=0,
        usecols=lambda x: x not in ["Running Time (s)", "Date&Time", "Clear"],
        skip_blank_lines=True,
        converters={1: parse_cryo_time},
    ).rename_axis("Time")


def get_log(
    startdate: datetime.datetime,
    enddate: datetime.datetime,
    directory: str,
    converter: Callable,
    error: bool = True,
) -> pd.DataFrame | None:
    """Read all log data in `directory` between `startdate` and `enddate` into a `pandas.DataFrame`."""
    dataframes = []
    for fname in map(
        datetime_to_filename, pd.date_range(start=startdate.date(), end=enddate.date())
    ):
        try:
            dataframes.append(converter(os.path.join(directory, fname)))
        except FileNotFoundError:
            pass
    if len(dataframes) == 0:
        if error:
            raise ValueError("No log files were found in specified range.")
        else:
            return None
    return pd.concat(dataframes)[slice(startdate, enddate)]


def get_cryocooler_log(startdate, enddate, error=False):
    return get_log(startdate, enddate, CRYO_DIR, parse_single_cryo, error=error)


def get_pressure_log(startdate, enddate, error=False):
    return get_log(startdate, enddate, MG15_DIR, parse_single_mg15, error=error)
