import datetime
import io

import pandas as pd


def parse_mg15_time(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s[:10] + "T" + s[11:])


def parse_mg15_time_old(s: float) -> datetime.datetime:
    return datetime.datetime.strptime(str(int(float(s))), "%y%m%d%H%M%S")


def parse_cryo_time(v: str | float) -> datetime.datetime:
    try:
        # Preserve the LabVIEW epoch conversion in the system's local time.
        return datetime.datetime.fromtimestamp(float(v) - 2082844800.0)
    except ValueError:
        return datetime.datetime.fromisoformat(v)


def _parse_iso_index(index: pd.Index) -> pd.DatetimeIndex:
    result = pd.to_datetime(index, format="ISO8601", errors="raise")
    # pandas treats empty strings and "NaT" as missing even with errors="raise";
    # the scalar parsers rejected these instead of silently losing log rows.
    if result.hasnans:
        raise ValueError("Log timestamps must not be empty or missing.")
    return result


def parse_single_mg15(filename):
    """Read a pressure log, parsing modern ISO timestamps in a single batch."""
    start_position = filename.tell() if hasattr(filename, "tell") else None
    options = {
        "header": None,
        "index_col": 0,
        "usecols": (0, 1, 2),
        "names": ("Time", "IG Main", "IG Middle"),
        "dtype": {"Time": str},
    }
    try:
        frame = pd.read_csv(filename, **options)
    except pd.errors.ParserError:
        if start_position is not None:
            filename.seek(start_position)
        frame = pd.read_csv(filename, sep="\t", **options)
        frame.index = pd.DatetimeIndex(
            [parse_mg15_time_old(value) for value in frame.index]
        )
    else:
        frame.index = _parse_iso_index(frame.index)
    return frame.rename_axis("time")


def parse_single_cryo(filename):
    """Read the last cryocooler header section from a single buffered file read."""
    if hasattr(filename, "read"):
        lines = filename.readlines()
    else:
        with open(filename) as stream:
            lines = stream.readlines()
    if not lines:
        raise ValueError("The cryocooler log is empty.")
    header_rows = [
        i
        for i, line in enumerate(lines)
        if line.startswith((lines[0][:10], "Time", "Running"))
    ]
    last_header = header_rows[-1]
    legacy = not lines[last_header].startswith("Time")
    frame = pd.read_csv(
        io.StringIO("".join(lines[last_header:])),
        index_col=0,
        header=0,
        usecols=lambda column: column not in ["Running Time (s)", "Date&Time", "Clear"],
        skip_blank_lines=True,
        dtype={1 if legacy else 0: str},
    )
    if frame.index.hasnans:
        raise ValueError("Log timestamps must not be empty or missing.")
    if legacy:
        frame.index = pd.DatetimeIndex(
            [parse_cryo_time(value) for value in frame.index]
        )
    else:
        try:
            frame.index = _parse_iso_index(frame.index)
        except ValueError:
            # Some older files use the modern header but still contain LabVIEW
            # numeric times. Keep that compatibility off the modern fast path.
            frame.index = pd.DatetimeIndex(
                [parse_cryo_time(value) for value in frame.index]
            )
    return frame.rename_axis("time")
