import datetime
import os
import sys
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
import pandas as pd

from logviewer._parsing import (
    parse_cryo_time,
    parse_mg15_time,
    parse_mg15_time_old,
    parse_single_cryo,
    parse_single_mg15,
)

if sys.platform == "darwin":
    # debug on macOS
    CRYO_DIR = "/Volumes/143.248.11.28/Logs/Cryocooler"
    MG15_DIR = "/Volumes/143.248.11.28/Logs/Pressure"
else:
    CRYO_DIR = "D:/Logs/Cryocooler"
    MG15_DIR = "D:/Logs/Pressure"


def datetime_to_filename(dt: datetime.datetime) -> str:
    """Return the csv file name corresponding to given input time."""
    return dt.strftime("%y%m%d.csv")


def log_index_to_unix_seconds(index: pd.Index) -> np.ndarray:
    """Convert local log times to plot coordinates independently of pandas units."""
    # pandas 3 infers microseconds where pandas 2 used nanoseconds. Request the
    # unit explicitly before scaling, retaining the logs' local time convention.
    return index.to_numpy(dtype="datetime64[ns]").astype(float) * 1e-9 + time.timezone


_Signature = tuple[int, int, int]


@dataclass(frozen=True, eq=False)
class _ParserIdentity:
    # Callable instances may be unhashable or compare equal despite owning
    # different state. Keep a strong reference and compare readers by identity.
    parser: Callable

    def __hash__(self) -> int:
        return id(self.parser)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ParserIdentity) and self.parser is other.parser


_CacheKey = tuple[_ParserIdentity, str]


def _signature(path: str) -> _Signature:
    stat = os.stat(path)
    return stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns


def _check_cancelled(cancelled: Callable[[], bool] | None):
    if cancelled is not None and cancelled():
        raise CancelledError


@dataclass(frozen=True)
class _CacheEntry:
    signature: _Signature
    frame: pd.DataFrame
    size: int


def _read_log_file(
    path: str,
    parser: Callable,
    cancelled: Callable[[], bool] | None,
    cached: _CacheEntry | None,
) -> tuple[pd.DataFrame, _Signature | None, int | None] | None:
    """Retry a changing live file once, without caching an unstable snapshot."""
    try:
        for attempt in range(2):
            _check_cancelled(cancelled)
            before = _signature(path)
            if attempt == 0 and cached is not None and cached.signature == before:
                return cached.frame, before, cached.size
            try:
                frame = parser(path)
            except Exception:
                _check_cancelled(cancelled)
                if attempt == 0 and _signature(path) != before:
                    continue
                raise
            _check_cancelled(cancelled)
            after = _signature(path)
            if before == after:
                return frame, after, None
            if attempt == 1:
                return frame, None, None
    except FileNotFoundError:
        return None
    except CancelledError:
        raise
    except Exception as exc:
        exc.add_note(f"Log file: {path}")
        raise
    return None


class LogLoader:
    """Load daily logs concurrently and reuse unchanged files in a bounded cache.

    A loader belongs to one coordinating thread at a time. Workers only read their
    own files; the coordinator owns the cache and assembles the returned frames.
    The cache budget counts pandas' estimated deep data and index memory usage.
    """

    def __init__(self, cache_max_bytes: int = 128 * 1024**2):
        if not isinstance(cache_max_bytes, int) or cache_max_bytes < 0:
            raise ValueError("cache_max_bytes must be a nonnegative integer")
        self.cache_max_bytes = cache_max_bytes
        self._cache: OrderedDict[_CacheKey, _CacheEntry] = OrderedDict()
        self._cache_bytes = 0

    @property
    def cache_bytes(self) -> int:
        """Return the estimated memory occupied by cached daily frames."""
        return self._cache_bytes

    def clear_cache(self):
        self._cache.clear()
        self._cache_bytes = 0

    def _discard(self, key: _CacheKey):
        entry = self._cache.pop(key, None)
        if entry is not None:
            self._cache_bytes -= entry.size

    def _remember(
        self,
        key: _CacheKey,
        frame: pd.DataFrame,
        signature: _Signature,
        size: int | None,
    ):
        if size is None:
            size = int(frame.memory_usage(index=True, deep=True).sum())
        self._discard(key)
        if size > self.cache_max_bytes or self.cache_max_bytes == 0:
            return
        while self._cache and self._cache_bytes + size > self.cache_max_bytes:
            _, entry = self._cache.popitem(last=False)
            self._cache_bytes -= entry.size
        self._cache[key] = _CacheEntry(signature, frame, size)
        self._cache_bytes += size

    def _load_sources(
        self,
        startdate: datetime.datetime,
        enddate: datetime.datetime,
        sources: list[tuple[str, Callable]],
        *,
        max_workers: int | None,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[pd.DataFrame | None]:
        if max_workers is not None and (
            not isinstance(max_workers, int) or max_workers < 1
        ):
            raise ValueError("max_workers must be a positive integer or None")
        _check_cancelled(cancelled)
        keys: list[list[_CacheKey]] = [[] for _ in sources]
        frames: dict[_CacheKey, pd.DataFrame] = {}
        pending: list[_CacheKey] = []
        for date in pd.date_range(start=startdate.date(), end=enddate.date()):
            for source_index, (directory, parser) in enumerate(sources):
                _check_cancelled(cancelled)
                path = os.path.abspath(
                    os.path.join(directory, datetime_to_filename(date))
                )
                key = _ParserIdentity(parser), path
                keys[source_index].append(key)
                pending.append(key)

        if pending:
            # None deliberately selects ThreadPoolExecutor's own default. Explicit
            # settings need no more threads than there are pending file reads.
            options = (
                {}
                if max_workers is None
                else {"max_workers": min(max_workers, len(pending))}
            )
            with ThreadPoolExecutor(**options) as executor:
                futures = []
                try:
                    for parser_identity, path in pending:
                        _check_cancelled(cancelled)
                        futures.append(
                            executor.submit(
                                _read_log_file,
                                path,
                                parser_identity.parser,
                                cancelled,
                                self._cache.get((parser_identity, path)),
                            )
                        )
                    for key, future in zip(pending, futures, strict=True):
                        _check_cancelled(cancelled)
                        result = future.result()
                        _check_cancelled(cancelled)
                        if result is None:
                            self._discard(key)
                            continue
                        frame, read_signature, cached_size = result
                        frames[key] = frame
                        if read_signature is None:
                            self._discard(key)
                        else:
                            self._remember(key, frame, read_signature, cached_size)
                except BaseException:
                    for future in futures:
                        future.cancel()
                    raise

        results = []
        for source_keys in keys:
            _check_cancelled(cancelled)
            parts = [frames[key] for key in source_keys if key in frames]
            if not parts:
                results.append(None)
                continue
            # A single-frame concat may share storage in some pandas versions.
            # Keep the caller's result independent of the cached daily frame.
            merged = parts[0].copy(deep=True) if len(parts) == 1 else pd.concat(parts)
            results.append(merged.sort_index(kind="stable").loc[startdate:enddate])
        return results

    def load(
        self,
        startdate: datetime.datetime,
        enddate: datetime.datetime,
        *,
        max_workers: int | None = None,
        cryo_dir: str = CRYO_DIR,
        pressure_dir: str = MG15_DIR,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
        """Load temperature and pressure files using one shared worker pool."""
        temperature, pressure = self._load_sources(
            startdate,
            enddate,
            [(cryo_dir, parse_single_cryo), (pressure_dir, parse_single_mg15)],
            max_workers=max_workers,
            cancelled=cancelled,
        )
        return temperature, pressure


def get_log(
    startdate: datetime.datetime,
    enddate: datetime.datetime,
    directory: str,
    converter: Callable,
    error: bool = True,
    *,
    max_workers: int | None = None,
) -> pd.DataFrame | None:
    """Read log files.

    Reads all log data in `directory` between `startdate` and `enddate` into a pandas
    DataFrame. The `converter` function is used to parse the log files.
    """
    frame = LogLoader(cache_max_bytes=0)._load_sources(
        startdate, enddate, [(directory, converter)], max_workers=max_workers
    )[0]
    if frame is None and error:
        raise ValueError("No log files were found in specified range.")
    return frame


def get_cryocooler_log(startdate, enddate, error=False, *, max_workers=None):
    return get_log(
        startdate,
        enddate,
        CRYO_DIR,
        parse_single_cryo,
        error=error,
        max_workers=max_workers,
    )


def get_pressure_log(startdate, enddate, error=False, *, max_workers=None):
    return get_log(
        startdate,
        enddate,
        MG15_DIR,
        parse_single_mg15,
        error=error,
        max_workers=max_workers,
    )
