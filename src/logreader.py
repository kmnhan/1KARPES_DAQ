import pandas as pd
import datetime
import os
from collections.abc import Callable

CRYO_DIR = "D:/Cryocooler_Log"
MG15_DIR = "D:/MG15_Log"


def parse_mg15_time(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s[:10] + "T" + s[11:])


def parse_labview_timestamp(v: float) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(float(v) - 2082844800.0)


def datetime_to_filename(dt: datetime.datetime) -> str:
    """Returns the csv file name corresponding to given input time."""
    return str(dt.year)[2:] + str(dt.month).zfill(2) + str(dt.day).zfill(2) + ".csv"


def parse_single_mg15(filename):
    """Read data from a pressure log file to a `pandas.DataFrame`."""
    return pd.read_csv(
        filename,
        header=None,
        index_col=0,
        usecols=(0, 1),
        names=("Time", "IG Main"),
        converters={0: parse_mg15_time},
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
        usecols=lambda x: x not in ["Date&Time", "Clear"],
        skip_blank_lines=True,
        converters={1: parse_labview_timestamp},
    ).rename_axis("Time")


def get_log(
    startdate: datetime.datetime,
    enddate: datetime.datetime,
    directory: str,
    converter: Callable,
) -> pd.DataFrame:
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
        raise ValueError("No log files were found in specified range.")
    return pd.concat(dataframes)[slice(startdate, enddate)]


def get_cryocooler_log(startdate, enddate):
    return get_log(startdate, enddate, CRYO_DIR, parse_single_cryo)


def get_pressure_log(startdate, enddate):
    return get_log(startdate, enddate, MG15_DIR, parse_single_mg15)
