import configparser
import os
import shutil
import tempfile
import threading
import time
import zipfile

import erlab.io
import numpy as np
import xarray as xr
from erlab.interactive.imagetool import BaseImageTool, ItoolMenuBar
from erlab.interactive.imagetool.controls import ItoolControlsBase
from qtpy import QtCore, QtGui, QtWidgets
from sescontrol.plugins import Motor
from sescontrol.ses_win import SES_DIR


class CasePreservingConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr):
        return str(optionstr)


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
        motor_coords: dict[str, np.ndarray],
        base_dir: str,
        base_file: str,
        data_idx: int,
        niter: int,
    ):
        super().__init__()
        self.signals = DataFetcherSignals()

        self._motor_coords = motor_coords
        self._base_dir = base_dir
        self._base_file = base_file
        self._data_idx = data_idx
        self._niter = niter

    def run(self):
        if len(self._motor_coords) == 0:
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
                    from erlab.io.plugins.da30 import load_zip

                    wave = load_zip(filename)
                else:
                    wave = erlab.io.load_experiment(filename)

            except PermissionError:
                time.sleep(0.01)

            except FileNotFoundError:
                filename = filename.replace("_scan_", "")

            else:
                break

        if isinstance(wave, xr.Dataset):
            # select first sequence
            wave: xr.DataArray = list(wave.data_vars.values())[0]

        wave = wave.rename(
            {k: v for k, v in self.COORDS_MAPPING.items() if k in wave.dims}
        )

        # Bin 2D scan to save memory
        if len(self._motor_coords) > 1:
            wave = wave.coarsen(
                {d: 4 for d in wave.dims if d != "theta"}, boundary="trim"
            ).mean()

        if self._niter == 1:
            # Reserve space for future scans
            wave = wave.expand_dims(
                self._motor_coords,
                axis=[wave.ndim + i for i in range(len(self._motor_coords))],
            ).copy()

            # Fill reserved space with nan
            for name, coord in self._motor_coords.items():
                wave.loc[{name: wave.coords[name] != coord[0]}] = np.nan

        self.signals.sigDataFetched.emit(self._niter, wave)


class LiveImageTool(BaseImageTool):
    sigClosed = QtCore.Signal(object)

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
        motor_coords: dict[str, np.ndarray],
        raster: bool,
        base_dir: str,
        base_file: str,
        data_idx: int,
    ):
        self._motor_coords = motor_coords
        self._raster = raster
        self._base_dir = base_dir
        self._base_file = base_file
        self._data_idx = data_idx

        self.setWindowTitle(self._base_file + f"{str(self._data_idx).zfill(4)}")

        if len(self._motor_coords) == 0:
            self.motor_controls.setDisabled(True)

    def trigger_fetch(self, niter: int):
        data_fetcher = DataFetcher(
            self._motor_coords, self._base_dir, self._base_file, self._data_idx, niter
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
                    niter - 1, [len(coord) for coord in self._motor_coords.values()]
                )
            )
            if (not self._raster) and (len(indices) == 2) and ((indices[0] % 2) != 0):
                # if outer loop is odd, inner loop is reversed
                indices[-1] = (
                    len(tuple(self._motor_coords.values())[-1]) - 1 - indices[-1]
                )

            # assign equal coordinates, energy axis might be mismatched in some cases
            wave = wave.assign_coords(
                {d: self.array_slicer._obj.coords[d] for d in wave.dims}
            )

            # assign motor coordinates
            wave = wave.expand_dims(
                {
                    name: [coord[ind]]
                    for ind, (name, coord) in zip(indices, self._motor_coords.items())
                }
            )

            # this will slice the target array at the coordinates we wish to insert the received data
            target_slices = {
                name: self.array_slicer._obj.coords[name] == coord[ind]
                for ind, (name, coord) in zip(indices, self._motor_coords.items())
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

    def closeEvent(self, event: QtGui.QCloseEvent):
        self.slicer_area.set_data(np.ones((2, 2), dtype=np.float32))
        self.sigClosed.emit(self)
        super().closeEvent(event)


class WorkFileUpdateThread(QtCore.QThread):
    sigUpdate = QtCore.Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.region = None
        self.workdir = None

    def set_params(self, region, workdir):
        self.region, self.workdir = region, workdir

    def run(self):
        try:
            shape, kwargs = get_workfile_shape_kwargs(self.region, self.workdir)
        except Exception as e:
            print("Exception while fetching workfile shape", e)
            self.sigUpdate.emit(None, None)
            return

        try:
            arr = get_workfile_array(
                self.region, self.workdir, shape, kwargs, norm=False
            )
        except Exception as e:
            print("Exception while fetching workfile array", e)
            arr = None

        try:
            arr_norm = get_workfile_array(
                self.region, self.workdir, shape, kwargs, norm=True
            )
        except Exception as e:
            print("Exception while fetching workfile norm array", e)
            arr_norm = None

        self.sigUpdate.emit(arr, arr_norm)


def get_workfile_shape_kwargs(region, workdir) -> tuple[int | tuple[int], dict]:
    ini_file = os.path.join(workdir, f"Spectrum_{region}.ini")

    tmpdir = tempfile.TemporaryDirectory()

    if os.path.isfile(ini_file):
        region_info = parse_ini(shutil.copy(ini_file, tmpdir.name))["spectrum"]
        shape, coords = get_shape_and_coords(region_info)
        kwargs = {"coords": coords, "name": region_info["name"]}
        return shape, kwargs
    else:
        ses_config = configparser.ConfigParser(strict=False)
        ses_ini_file = os.path.join(SES_DIR, "ini\Ses.ini")

        with open(shutil.copy(ses_ini_file, tmpdir.name), "r") as f:
            ses_config.read_file(f)

        nslices = int(ses_config["Instrument Settings"]["Detector.Slices"])
        return nslices, {}


def get_workfile_array(
    region: str, workdir: str, shape: int | tuple[int], kwargs: dict, norm: bool = False
) -> xr.DataArray | None:
    if norm:
        binfile: str = f"Spectrum_{region}_Norm.bin"
    else:
        binfile: str = f"Spectrum_{region}.bin"

    binfile = os.path.join(workdir, binfile)

    if not os.path.isfile(binfile):
        return None

    tmpdir = tempfile.TemporaryDirectory()
    arr = np.fromfile(shutil.copy(binfile, tmpdir.name), dtype=np.float32)

    if isinstance(shape, int):
        return xr.DataArray(arr.reshape(shape, (int(len(arr) / shape))), **kwargs)
    else:
        return xr.DataArray(arr.reshape(shape), **kwargs)


# def get_workfile(region: str, workdir: str, norm: bool = False) -> xr.DataArray | None:
#     if norm:
#         binfile: str = f"Spectrum_{region}_Norm.bin"
#     else:
#         binfile: str = f"Spectrum_{region}.bin"

#     binfile = os.path.join(workdir, binfile)

#     if not os.path.isfile(binfile):
#         return None

#     tmpdir = tempfile.TemporaryDirectory()
#     arr = np.fromfile(shutil.copy(binfile, tmpdir.name), dtype=np.float32)

#     ini_file = os.path.join(workdir, f"Spectrum_{region}.ini")

#     if os.path.isfile(ini_file):
#         region_info = parse_ini(shutil.copy(ini_file, tmpdir.name))["spectrum"]
#         shape, coords = get_shape_and_coords(region_info)
#         arr = xr.DataArray(arr.reshape(shape), coords=coords, name=region_info["name"])

#     else:
#         ses_config = configparser.ConfigParser(strict=False)
#         ses_ini_file = os.path.join(SES_DIR, "ini\Ses.ini")

#         with open(shutil.copy(ses_ini_file, tmpdir.name), "r") as f:
#             ses_config.read_file(f)

#         nslices = int(ses_config["Instrument Settings"]["Detector.Slices"])

#         arr = xr.DataArray(arr.reshape(nslices, (int(len(arr) / nslices))))

#     tmpdir.cleanup()

#     return arr


# class WorkFileListUpdateThread(QtCore.QThread):
#     sigUpdate = QtCore.Signal(list[str])

#     def __init__(self) -> None:
#         super().__init__()
#         self.workdir = None

#     def set_workdir(self, workdir):
#         self.workdir = workdir

#     def run(self):
#         regions: list[str] = []
#         for f in os.listdir(self.workdir):
#             if f.startswith("Spectrum_") and f.endswith("_Norm.bin"):
#                 regions.append(f[9:-9])
#         self.sigUpdate.emit(regions)


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

        self.autoupdate_check = QtWidgets.QCheckBox("Auto update")
        self.autoupdate_check.toggled.connect(self.toggle_update_timer)

        self.reload_btn = QtWidgets.QPushButton("Load")
        self.reload_btn.clicked.connect(self.reload)

        lowerwidget.layout().addWidget(self.norm_check)
        lowerwidget.layout().addWidget(self.reload_btn)
        widget.layout().addWidget(self.region_combo)
        widget.layout().addWidget(lowerwidget)
        widget.layout().addWidget(self.autoupdate_check)

        load_dock = QtWidgets.QDockWidget("Work file", self)
        load_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
        )
        load_dock.setWidget(self.widget_box(widget))
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, load_dock)

        self.regions: list[str] = []
        self.regionscan_timer = QtCore.QTimer(self)
        self.regionscan_timer.setInterval(250)
        self.regionscan_timer.timeout.connect(self.update_regions)
        self.regionscan_timer.start()

        self.update_timer = QtCore.QTimer(self)
        self.update_timer.setInterval(250)
        self.update_timer.timeout.connect(self.reload)

        self.mnb = ItoolMenuBar(self.slicer_area, self)

        self.workfilethread = WorkFileUpdateThread()
        self.workfilethread.sigUpdate.connect(self.update_data)

    def toggle_update_timer(self):
        if self.autoupdate_check.isChecked():
            self.update_timer.start()
        else:
            self.update_timer.stop()

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

    @QtCore.Slot()
    def reload(self):
        if self.workfilethread.isRunning():
            self.workfilethread.wait()

        self.workfilethread.set_params(self.region_combo.currentText(), self.workdir)
        self.workfilethread.start()

    @QtCore.Slot(object, object)
    def update_data(self, arr, arr_norm):
        if arr is None:
            print("File not found or corrupt, cancel workfile update")
            return

        if self.norm_check.isChecked():
            if arr_norm is not None:
                arr = arr / arr_norm
                del arr_norm

        if check_same_coord_limits(self.array_slicer._obj, arr):
            if self.array_slicer._obj.shape == arr.shape:
                self.array_slicer._obj[:] = arr.values
            else:
                self.array_slicer._obj[:] = arr.transpose(
                    *self.array_slicer._obj.dims
                ).values

            self.array_slicer.clear_val_cache(include_vals=True)
            self.slicer_area.refresh_all()

        else:
            if set(self.array_slicer._obj.dims) == set(arr.dims):
                self.array_slicer.set_data(arr.transpose(*self.array_slicer._obj.dims))
            else:
                self.slicer_area.set_data(arr)

        self.setWindowTitle(f"Work : {self.region_combo.currentText()}")


def check_same_coord_limits(arr1, arr2):
    if arr1.ndim != arr2.ndim:
        return False
    if set(arr1.shape) != set(arr2.shape):
        return False
    if set(arr1.dims) != set(arr2.dims):
        return False

    for d in arr1.dims:
        if not np.isclose(arr1.coords[d][0], arr2.coords[d][0]):
            return False
        if not np.isclose(arr1.coords[d][-1], arr2.coords[d][-1]):
            return False
    return True


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


def parse_ini(filename: str | os.PathLike) -> dict:
    parser = CasePreservingConfigParser(strict=False)
    out = {}
    with open(filename) as f:
        parser.read_file(f)
        for section in parser.sections():
            out[section] = dict(parser.items(section))
    return out
