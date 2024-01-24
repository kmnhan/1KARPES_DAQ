import os
import threading
import time
import zipfile

import erlab.io
import numpy as np
import xarray as xr
from erlab.interactive.imagetool import BaseImageTool, ItoolMenuBar
from erlab.interactive.imagetool.controls import ItoolControlsBase
from plugins import Motor
from qtpy import QtCore, QtWidgets


class MotorThread(threading.Thread):
    """Simple thread implementation of non-blocking motion."""

    def __init__(self, motor_cls: type[Motor], target: float):
        super().__init__()

        self.motor_cls = motor_cls
        self.target = target

    def run(self):
        motor = self.motor_cls()
        motor.pre_motion()
        motor.move(self.target)
        if self.motor_cls.__name__ == "Delta":
            motor.post_motion(reset=False)
        else:
            motor.post_motion()


class MotorControls(ItoolControlsBase):
    quick_move_dims = ["X", "Y", "Z", "Polar", "Tilt", "Azi", "Delta"]

    def __init__(self, *args, **kwargs):
        self.workers: list[MotorThread] = []
        self.busy: bool = True
        super().__init__(*args, **kwargs)

    def initialize_layout(self):
        self.setLayout(QtWidgets.QVBoxLayout(self))
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(3)

    def initialize_widgets(self):
        super().initialize_widgets()
        self.move_btn = QtWidgets.QPushButton("Move to cursor")
        self.move_btn.clicked.connect(self.move_to_cursor)

        self.checkbox_widget = QtWidgets.QWidget()
        self.checkbox_widget.setLayout(QtWidgets.QHBoxLayout())
        self.checkbox_widget.layout().setContentsMargins(0, 0, 0, 0)
        self.checkbox_widget.layout().setSpacing(3)

        self.checkboxes: tuple[QtWidgets.QCheckBox, ...] = (
            QtWidgets.QCheckBox(),
            QtWidgets.QCheckBox(),
            QtWidgets.QCheckBox(),
        )
        for check in self.checkboxes:
            self.checkbox_widget.layout().addWidget(check)
            check.setChecked(True)
            check.toggled.connect(self.update)

        self.layout().addWidget(self.move_btn)
        self.layout().addWidget(self.checkbox_widget)

    def connect_signals(self):
        super().connect_signals()
        self.slicer_area.sigIndexChanged.connect(self.update)
        self.slicer_area.sigCurrentCursorChanged.connect(self.update)
        self.slicer_area.sigBinChanged.connect(self.update)
        self.slicer_area.sigDataChanged.connect(self.data_changed)
        self.slicer_area.sigShapeChanged.connect(self.update)

    def disconnect_signals(self):
        super().disconnect_signals()
        self.slicer_area.sigIndexChanged.disconnect(self.update)
        self.slicer_area.sigCurrentCursorChanged.disconnect(self.update)
        self.slicer_area.sigBinChanged.disconnect(self.update)
        self.slicer_area.sigDataChanged.disconnect(self.data_changed)
        self.slicer_area.sigShapeChanged.disconnect(self.update)

    @property
    def valid_dims(self) -> list[str]:
        return [d for d in self.data.dims if d in self.quick_move_dims]

    @property
    def enabled_dims(self) -> list[str]:
        return [check.text() for check in self.checkboxes if check.isVisible()]

    @property
    def cursor_pos(self) -> dict[str, float]:
        return {
            dim: float(
                self.array_slicer._values[self.slicer_area.current_cursor][
                    self.data.dims.index(dim)
                ]
            )
            for dim in self.enabled_dims
        }

    @QtCore.Slot()
    def move_to_cursor(self):
        for w in self.workers:
            w.join()

        self.workers = []
        for k, v in self.cursor_pos.items():
            motor_cls = Motor.plugins[k]
            self.workers.append(MotorThread(motor_cls, v))
            self.workers[-1].start()

    @QtCore.Slot()
    def update(self):
        super().update()
        if self.busy:
            self.move_btn.setEnabled(False)
        else:
            self.move_btn.setDisabled(len(self.enabled_dims) == 0)

    @QtCore.Slot()
    def data_changed(self):
        for i, check in enumerate(self.checkboxes):
            try:
                dim = self.valid_dims[i]
            except IndexError:
                check.setVisible(False)
            else:
                check.setText(dim)
                check.setVisible(True)

    def reset(self):
        for spin in self.spins:
            spin.setValue(1)


class CustomMenuBar(ItoolMenuBar):
    """Menubar with the data load menu customized."""

    def _open_file(self):
        valid_files = {
            "xarray HDF5 Files (*.h5)": (xr.load_dataarray, dict(engine="h5netcdf")),
            "1KARPES Raw Data (*.pxt *.zip)": (erlab.io.load_experiment, dict()),
        }

        dialog = QtWidgets.QFileDialog(self)
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptOpen)
        dialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilters(valid_files.keys())

        if dialog.exec():
            files = dialog.selectedFiles()
            fn, kargs = valid_files[dialog.selectedNameFilter()]

            dat = fn(files[0], **kargs)

            self.slicer_area.set_data(dat)
            self.slicer_area.view_all()


class DataFetcherSignals(QtCore.QObject):
    sigDataFetched = QtCore.Signal(int, object)


class DataFetcher(QtCore.QRunnable):
    COORDS_MAPPING = {
        "Kinetic Energy [eV]": "eV",
        "Energy [eV]": "eV",
        "Y-Scale [deg]": "phi",
        "Thetax [deg]": "phi",
        "Thetay [deg]": "theta DA",
    }

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
        if len(self._motor_args) == 0:
            filename = os.path.join(
                self._base_dir, f"{self._base_file}{str(self._data_idx).zfill(4)}.pxt"
            )
            if not os.path.isfile(filename):
                filename = filename.replace(".pxt", ".zip")
                timeout = time.monotonic() + 20
                while time.monotonic() < timeout:
                    if os.path.isfile(filename):
                        if os.stat(filename).st_size != 0:
                            try:
                                with zipfile.ZipFile(filename, "r") as _:
                                    # do nothing, just trying to open the file
                                    pass
                            except zipfile.BadZipFile:
                                pass
                            else:
                                break
                    time.sleep(0.2)
        else:
            filename = os.path.join(
                self._base_dir,
                "_scan_"
                + self._base_file
                + f"{str(self._data_idx).zfill(4)}_S{str(self._niter).zfill(5)}.pxt",
            )
            if not os.path.isfile(filename):
                filename = filename.replace("_scan_", "")

        if not os.path.isfile(filename):
            print("File not found... skip display")
            return
        while True:
            try:
                if os.path.splitext(filename)[-1] == ".zip":
                    wave = erlab.io.da30.load_zip(filename)
                else:
                    wave = erlab.io.load_experiment(filename)
            except PermissionError:
                time.sleep(0.01)
            else:
                break

        if isinstance(wave, xr.Dataset):
            # select first sequence
            wave: xr.DataArray = list(wave.data_vars.values())[0]

        wave = wave.rename(
            {k: v for k, v in self.COORDS_MAPPING.items() if k in wave.dims}
        )

        # binning
        if len(self._motor_args) != 0:
            wave = wave.coarsen(
                {d: 4 for d in wave.dims if d != "theta"}, boundary="trim"
            ).mean()

        if self._niter == 1:
            # reserve space for future scans
            wave = wave.expand_dims(
                {name: coord for name, coord in self._motor_args},
                # axis=[wave.ndim + i for i in range(len(self._motor_args))],
            ).copy()

            # fill reserved space with nan
            for name, coord in self._motor_args:
                wave.loc[{name: wave.coords[name] != coord[0]}] = np.nan

        self.signals.sigDataFetched.emit(self._niter, wave)


class LiveImageTool(BaseImageTool):
    def __init__(self, parent=None, threadpool: QtCore.QThreadPool | None = None):
        super().__init__(data=np.ones((2, 2, 2), dtype=np.float32), parent=parent)

        if threadpool is None:
            threadpool = QtCore.QThreadPool()
        self.threadpool = threadpool

        for d in self.docks:
            d.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)

        self.motor_controls = MotorControls(self.slicer_area)

        motor_dock = QtWidgets.QDockWidget("Motors", self)
        motor_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
        )
        motor_dock.setWidget(self.widget_box(self.motor_controls))
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, motor_dock)

        self.mnb = CustomMenuBar(self.slicer_area, self)

    def set_busy(self, busy: bool):
        self.motor_controls.busy = busy

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

        self.setWindowTitle(self._base_file + f"{str(self._data_idx).zfill(4)}")

        if len(self._motor_args) == 0:
            self.motor_controls.setDisabled(True)

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
