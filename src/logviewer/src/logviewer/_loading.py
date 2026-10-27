from __future__ import annotations

import os
from concurrent.futures import CancelledError
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import tomlkit
from qtpy import QtCore

from logviewer.logreader import CRYO_DIR, MG15_DIR

if TYPE_CHECKING:
    import datetime
    from collections.abc import Callable

    import pandas as pd

    from logviewer.logreader import LogLoader


@dataclass(frozen=True)
class LoadRequest:
    request_id: int
    start: datetime.datetime
    end: datetime.datetime
    max_workers: int | None
    config_file: str | None
    update: bool = True
    cryo_dir: str = CRYO_DIR
    pressure_dir: str = MG15_DIR


@dataclass
class LoadedLogs:
    df: pd.DataFrame | None
    df_mg15: pd.DataFrame | None
    plot_config: dict[str, Any] | None = None


def read_logs(
    loader: LogLoader,
    request: LoadRequest,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> LoadedLogs:
    """Read and prepare logs without accessing any GUI objects."""
    df, df_mg15 = loader.load(
        request.start,
        request.end,
        max_workers=request.max_workers,
        cryo_dir=request.cryo_dir,
        pressure_dir=request.pressure_dir,
        cancelled=cancelled,
    )
    if df is not None and df.empty:
        df = None
    if df_mg15 is not None and df_mg15.empty:
        df_mg15 = None
    if cancelled is not None and cancelled():
        raise CancelledError
    if df is None and df_mg15 is None:
        raise ValueError(
            f"No temperature or pressure data was found between "
            f"{request.start.isoformat(sep=' ')} and "
            f"{request.end.isoformat(sep=' ')}.\n"
            f"Temperature logs: {request.cryo_dir}\n"
            f"Pressure logs: {request.pressure_dir}"
        )
    plot_config = None
    if df is not None:
        config_file = request.config_file
        if config_file is None or not os.path.isfile(config_file):
            config_file = os.path.join(request.cryo_dir, "config.toml")
        with open(config_file) as stream:
            plot_config = tomlkit.load(stream)["plotting"]
    if cancelled is not None and cancelled():
        raise CancelledError
    return LoadedLogs(df, df_mg15, plot_config)


class LogLoadTask(QtCore.QThread):
    """Coordinate file loading and pass ownership of its result back to the GUI."""

    def __init__(
        self,
        loader: LogLoader,
        request: LoadRequest,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent)
        self.loader = loader
        self.request = request
        self.result: LoadedLogs | None = None
        self.error: Exception | None = None

    def run(self):
        try:
            self.result = read_logs(
                self.loader, self.request, cancelled=self.isInterruptionRequested
            )
        except Exception as error:
            self.error = error

    def result_or_raise(self) -> LoadedLogs:
        """Return completed data or re-raise the worker's original exception."""
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise RuntimeError("The log load finished without a result.")
        return self.result
