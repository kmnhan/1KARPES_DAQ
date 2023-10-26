import os

import erlab.io
import numpy as np
import xarray as xr
from erlab.interactive.imagetool import BaseImageTool

from erlab.interactive.imagetool.core import ImageSlicerArea
from erlab.interactive.imagetool.controls import (
    ItoolBinningControls,
    ItoolColormapControls,
    ItoolCrosshairControls,
)
from qtpy import QtCore, QtWidgets


class DataFetcherSignals(QtCore.QObject):
    sigDataFetched = QtCore.Signal(int, object)


class DataFetcher(QtCore.QRunnable):
    def __init__(
        self,
        motor_args: list[tuple[str, np.ndarray]],
        base_dir: str,
        base_file: str,
        data_idx: int,
        niter: int,
    ):
        super().__init__()
        self.signals = DataFetcherSignals()

        self._motor_args = motor_args
        self._base_dir = base_dir
        self._base_file = base_file
        self._data_idx = data_idx
        self._niter = niter

    def run(self):
        filename = os.path.join(
            self._base_dir,
            "_scan_"
            + self._base_file
            + f"{str(self._data_idx).zfill(4)}_S{str(self._niter).zfill(5)}.pxt",
        )
        if not os.path.isfile(filename):
            filename = filename.replace("_scan_", "")
        wave = erlab.io.load_experiment(filename)

        if isinstance(wave, xr.Dataset):
            # select first sequence
            wave: xr.DataArray = list(wave.data_vars.values())[0]

        # binning
        wave = wave.coarsen({d: 4 for d in wave.dims}, boundary="trim").mean()

        if self._niter == 1:
            wave = wave.expand_dims(
                {name: coord for name, coord in self._motor_args},
                axis=[wave.ndim + i for i in range(len(self._motor_args))],
            ).copy()

            for name, coord in self._motor_args:
                wave.loc[{name: wave.coords[name] != coord[0]}] = np.nan

        self.signals.sigDataFetched.emit(self._niter, wave)


class LiveImageTool(QtWidgets.QWidget):
    def __init__(self, parent=None, threadpool: QtCore.QThreadPool | None = None):
        super().__init__(parent=parent)
        if threadpool is None:
            threadpool = QtCore.QThreadPool()
        self.threadpool = threadpool

        self.setLayout(QtWidgets.QVBoxLayout(self))
        self.layout().setContentsMargins(0, 0, 0, 0)

        self.controls = QtWidgets.QWidget(self)
        self.slicer_area = ImageSlicerArea(
            self, data=np.ones((2, 2, 2), dtype=np.float32)
        )

        self.controls.setLayout(QtWidgets.QHBoxLayout(self.controls))
        self.controls.layout().addWidget(ItoolCrosshairControls(self.slicer_area))
        self.controls.layout().addWidget(ItoolColormapControls(self.slicer_area))
        self.controls.layout().addWidget(ItoolBinningControls(self.slicer_area))

        self.layout().addWidget(self.controls)
        self.layout().addWidget(self.slicer_area)

        # self.setWindowFlags(self.windowFlags() | QtCore.Qt.CustomizeWindowHint)
        # self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)

    @property
    def array_slicer(self):
        return self.slicer_area.array_slicer

    def set_params(
        self,
        motor_args: list[tuple[str, np.ndarray]],
        base_dir: str,
        base_file: str,
        data_idx: int,
    ):
        self._motor_args = motor_args
        self._base_dir = base_dir
        self._base_file = base_file
        self._data_idx = data_idx

    def trigger_fetch(self, niter: int):
        data_fetcher = DataFetcher(
            self._motor_args, self._base_dir, self._base_file, self._data_idx, niter
        )
        data_fetcher.signals.sigDataFetched.connect(self.update_data)
        self.threadpool.start(data_fetcher)

    @QtCore.Slot(int, object)
    def update_data(self, niter: int, wave: xr.DataArray):
        if niter == 1:
            return self.slicer_area.set_data(wave)

        else:
            indices = list(
                np.unravel_index(
                    niter - 1, [len(coord) for _, coord in self._motor_args]
                )
            )
            if (len(indices) == 2) and ((indices[0] % 2) != 0):
                # if outer loop is odd, inner loop is reversed
                indices[-1] = len(self._motor_args[-1][1]) - 1 - indices[-1]

            self.array_slicer._obj.loc[
                {
                    name: self.array_slicer._obj.coords[name] == coord[ind]
                    for ind, (name, coord) in zip(indices, self._motor_args)
                }
            ] = wave.assign_coords(
                {d: self.array_slicer._obj.coords[d] for d in wave.dims}
            )

            for prop in (
                "nanmax",
                "nanmin",
                "absnanmax",
                "absnanmin",
                # "coords",
                # "coords_uniform",
                # "incs",
                # "incs_uniform",
                # "lims",
                # "lims_uniform",
                "data_vals_T",
            ):
                self.array_slicer.reset_property_cache(prop)
            self.slicer_area.refresh_all()
