import configparser
import os
import threading
import time
import zipfile

import erlab.io
import numpy as np
import xarray as xr
from erlab.interactive.imagetool import BaseImageTool, ItoolMenuBar
from erlab.interactive.imagetool.controls import ItoolControlsBase
from qtpy import QtCore, QtWidgets

from sescontrol.plugins import Motor
from sescontrol.ses_win import SES_DIR


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
        if self.motor_cls.__name__ == "Beam":
            motor.post_motion(reset=False)
        else:
            motor.post_motion()


class MotorControls(ItoolControlsBase):
    quick_move_dims = ["X", "Y", "Z", "Polar", "Tilt", "Azi", "Beam"]

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
                timeout = time.perf_counter() + 20
                while time.perf_counter() < timeout:
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
                axis=[wave.ndim + i for i in range(len(self._motor_args))],
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

            # assign equal coordinates, energy axis might be mismatched in some cases
            wave = wave.assign_coords(
                {d: self.array_slicer._obj.coords[d] for d in wave.dims}
            )

            # assign motor coordinates
            wave = wave.expand_dims(
                {
                    name: [coord[ind]]
                    for ind, (name, coord) in zip(indices, self._motor_args)
                }
            )

            # this will slice the target array at the coordinates we wish to insert the received data
            target_slices = {
                name: self.array_slicer._obj.coords[name] == coord[ind]
                for ind, (name, coord) in zip(indices, self._motor_args)
            }
            # we want to know the dims of target array before assigning new values
            target = self.array_slicer._obj.loc[target_slices]

            # transpose to target shape on assign
            self.array_slicer._obj.loc[target_slices] = wave.transpose(
                *target.dims
            ).values
            # We take the values because coordinates on target array are float32,
            # whereas we have assigned float64. This results in comparison failure.

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


class WorkFileImageTool(BaseImageTool):
    def __init__(self, parent=None):
        super().__init__(data=np.ones((2, 2, 2), dtype=np.float32), parent=parent)

        self.workdir = os.path.join(SES_DIR, "work")

        for d in self.docks:
            d.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)

        widget = QtWidgets.QWidget()
        widget.setLayout(QtWidgets.QVBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)

        lowerwidget = QtWidgets.QWidget()
        lowerwidget.setLayout(QtWidgets.QHBoxLayout())
        lowerwidget.layout().setContentsMargins(0, 0, 0, 0)

        self.region_combo = QtWidgets.QComboBox()
        self.region_combo.currentTextChanged.connect(self.reload)

        self.norm_check = QtWidgets.QCheckBox("Norm")
        self.norm_check.toggled.connect(self.reload)

        self.reload_btn = QtWidgets.QPushButton("Load")
        self.reload_btn.clicked.connect(self.reload)

        lowerwidget.layout().addWidget(self.norm_check)
        lowerwidget.layout().addWidget(self.reload_btn)
        widget.layout().addWidget(self.region_combo)
        widget.layout().addWidget(lowerwidget)

        load_dock = QtWidgets.QDockWidget("Work file", self)
        load_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
        )
        load_dock.setWidget(self.widget_box(widget))
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, load_dock)

        self.regions: list[str] = []
        self.regionscan_timer = QtCore.QTimer(self)
        self.regionscan_timer.setInterval(500)
        self.regionscan_timer.timeout.connect(self.update_regions)
        self.regionscan_timer.start()

        self.mnb = ItoolMenuBar(self.slicer_area, self)

    def update_regions(self):
        """Scan for regions in work directory."""
        regions: list[str] = []
        for f in os.listdir(self.workdir):
            if f.startswith("Spectrum_") and f.endswith("_Norm.bin"):
                regions.append(f[9:-9])
        if set(regions) == set(self.regions):
            return
        else:
            self.regions = regions
            self.region_combo.clear()
            self.region_combo.addItems(self.regions)

    def reload(self):
        region: str = self.region_combo.currentText()

        if self.norm_check.isChecked():
            binfile: str = f"Spectrum_{region}_Norm.bin"
        else:
            binfile: str = f"Spectrum_{region}.bin"
        binfile = os.path.join(self.workdir, binfile)

        if not os.path.isfile(binfile):
            print("File not found, abort")
            return

        arr = np.fromfile(binfile, dtype=np.float32)

        ini_file = os.path.join(self.workdir, f"Spectrum_{region}.ini")
        if os.path.isfile(ini_file):
            region_info = parse_ini(ini_file)["spectrum"]
            shape, coords = get_shape_and_coords(region_info)
            arr = xr.DataArray(
                arr.reshape(shape), coords=coords, name=region_info["name"]
            )
        else:
            arr = xr.DataArray(arr)

        if self.array_slicer._obj.shape == arr.shape:
            self.array_slicer._obj[:] = arr.values
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
        else:
            self.slicer_area.set_data(arr)

        self.setWindowTitle(f"work: {region}")


def get_shape_and_coords(region_info: dict) -> tuple[tuple[int, ...], dict]:
    shape: list[int] = []
    coords = dict()
    for d in ("depth", "height", "width"):
        n = int(region_info[d])
        offset = float(region_info[f"{d}offset"])
        delta = float(region_info[f"{d}delta"])
        shape.append(n)
        coords[region_info[f"{d}label"]] = np.linspace(
            offset, offset + (n - 1) * delta, n
        )
    return tuple(shape), coords


def parse_ini(filename):
    parser = configparser.ConfigParser(strict=False)
    out = dict()
    with open(filename, "r") as f:
        parser.read_file(f)
        for section in parser.sections():
            out[section] = dict(parser.items(section))
    return out
