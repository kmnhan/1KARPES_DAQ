import configparser
import logging
import os
import shutil
import tempfile
import threading
import time
import zipfile

import erlab.io
import numpy as np
import xarray as xr
from erlab.interactive.imagetool import (
    BaseImageTool,
    ImageTool,
    ItoolMenuBar,
    itool,
    manager,
)
from erlab.interactive.imagetool.controls import ItoolControlsBase
from qtpy import QtCore, QtGui, QtWidgets

from sescontrol.plugins import Motor
from sescontrol.scan import TEMPFILE_PREFIX, gen_data_name
from sescontrol.ses_win import SES_DIR

log = logging.getLogger("scan")

WORK_DIR = os.path.join(SES_DIR, "work")


class CasePreservingConfigParser(configparser.ConfigParser):
    # https://stackoverflow.com/questions/1611799
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
    QUICK_MOVE_DIMS: tuple[str] = (
        "X",
        "Y",
        "Z",
        "Polar",
        "Tilt",
        "Azi",
        "Beam",
    )  #: Dimensions that are applied in move to cursor action

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
        return [d for d in self.data.dims if d in self.QUICK_MOVE_DIMS]

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


class DataFetcherSignals(QtCore.QObject):
    sigDataFetched = QtCore.Signal(int, object)


class DataFetcher(QtCore.QRunnable):
    COORDS_MAPPING = {
        "Kinetic Energy [eV]": "eV",
        "Energy [eV]": "eV",
        "Y-Scale [deg]": "alpha",
        "Thetax [deg]": "alpha",
        "Thetay [deg]": "beta",
        "ThetaY": "beta",
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
                self._base_dir,
                gen_data_name(self._base_file, self._data_idx, ext=".pxt"),
            )
            if not os.path.isfile(filename):
                filename = filename.replace(".pxt", ".zip")
                timeout = time.perf_counter() + 20
                while time.perf_counter() < timeout:
                    if os.path.isfile(filename):
                        if os.stat(filename).st_size != 0:
                            try:
                                with tempfile.TemporaryDirectory() as tmpdir:
                                    file_copied = shutil.copy(filename, tmpdir)
                                    with zipfile.ZipFile(file_copied, "r") as _:
                                        # Do nothing, just trying to open the file
                                        # Will this break the file if SES is writing to it?
                                        # Requires extensive testing
                                        pass
                            except zipfile.BadZipFile:
                                pass
                            else:
                                break
                    time.sleep(0.2)
        else:
            filename = os.path.join(
                self._base_dir,
                gen_data_name(
                    self._base_file,
                    self._data_idx,
                    slice_idx=self._niter,
                    prefix=True,
                    ext=".pxt",
                ),
            )
            if not os.path.isfile(filename):
                filename = os.path.join(
                    self._base_dir,
                    gen_data_name(
                        self._base_file,
                        self._data_idx,
                        slice_idx=self._niter,
                        prefix=False,
                        ext=".pxt",
                    ),
                )

        if not os.path.isfile(filename):
            log.debug("DataFetcher failed to find file, exiting")
            return

        start_t = time.perf_counter()
        while True:
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    file_copied = shutil.copy(filename, tmpdir)

                    if os.path.splitext(filename)[-1] == ".zip":
                        from erlab.io.plugins.da30 import load_zip

                        wave = load_zip(file_copied)

                    else:
                        from erlab.io.igor import load_experiment

                        wave = load_experiment(file_copied)

            except PermissionError:
                time.sleep(0.05)

            except FileNotFoundError:
                filename = filename.replace(TEMPFILE_PREFIX, "")
                time.sleep(0.01)

            else:
                break

            if time.perf_counter() - start_t > 20:
                log.error("DataFetcher timed out after 20 seconds, exiting")
                return

        if isinstance(wave, xr.Dataset):
            # If the file contains multiple scans, take the first one
            wave: xr.DataArray = next(iter(wave.data_vars.values()))

        wave = wave.rename(
            {k: v for k, v in self.COORDS_MAPPING.items() if k in wave.coords}
        )

        # Bin 2D scan to save memory
        # Since we've installed more RAM, we can skip this step for now

        # if len(self._motor_coords) > 1:
        #     wave = wave.coarsen(
        #         {d: 4 for d in wave.dims if d != "theta"}, boundary="trim"
        #     ).mean()

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


class LiveImageTool(ImageTool):
    sigClosed = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(data=np.ones((2, 2, 2), dtype=np.float32), parent=parent)

        self.threadpool = QtCore.QThreadPool.globalInstance()

        for d in self.docks:
            d.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)

        self.motor_controls = MotorControls(self.slicer_area)

        motor_dock = QtWidgets.QDockWidget("Motors", self)
        motor_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
        )
        motor_dock.setWidget(self.widget_box(self.motor_controls))
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, motor_dock)

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

            # Assign equal coordinates since the energy axis values might be slightly
            # different probably due to rounding errors in SES software corrections
            wave = wave.assign_coords(
                {d: self.array_slicer._obj.coords[d] for d in wave.dims}
            )

            # Assign motor coordinates
            wave = wave.expand_dims(
                {
                    name: [coord[ind]]
                    for ind, (name, coord) in zip(
                        indices, self._motor_coords.items(), strict=True
                    )
                }
            )

            # These will slice the target array at the coordinates we wish to insert the
            # received data
            target_slices = {
                name: self.array_slicer._obj.coords[name] == coord[ind]
                for ind, (name, coord) in zip(
                    indices, self._motor_coords.items(), strict=True
                )
            }

            # We want to know the dims of target array before assigning new values since
            # the user might have transposed it
            target_dims = self.array_slicer._obj.loc[target_slices].dims

            # Transpose to target shape on assignment
            if target_dims != wave.dims:
                self.array_slicer._obj.loc[target_slices] = wave.transpose(
                    *target_dims
                ).values
            else:
                self.array_slicer._obj.loc[target_slices] = wave.values

            # Reset _data to include new slice
            # This allows filter actions such as normalization work properly
            self.slicer_area._data = self.array_slicer._obj

            self.array_slicer.clear_dim_cache(include_vals=True)
            self.slicer_area.refresh_all(only_plots=True)

    @QtCore.Slot()
    def to_manager(self):
        if manager.is_running():
            itool(
                self.slicer_area.data.rename(self.windowTitle()),
                state=self.slicer_area.state,
            )
            self.close()

    def closeEvent(self, event: QtGui.QCloseEvent):
        # Setting the data to small array before closing might help with garbage
        # collection, not so sure
        self.slicer_area.set_data(np.ones((2, 2), dtype=np.float32))
        self.sigClosed.emit(self)
        super().closeEvent(event)


class WorkFileFetcherSignals(QtCore.QObject):
    sigUpdate = QtCore.Signal(object)


class WorkFileFetcher(QtCore.QRunnable):
    def __init__(self, region: str, norm: bool) -> None:
        super().__init__()
        self.signals = WorkFileFetcherSignals()
        self.region = region
        self.norm = norm

    def run(self):
        try:
            shape, kwargs = get_workfile_shape_kwargs(self.region)
        except Exception:
            log.exception("Exception while fetching workfile shape")
            return

        try:
            arr = get_workfile_array(self.region, shape, kwargs, norm=False)
        except Exception:
            log.exception("Exception while fetching workfile array")
            arr = None

        if arr is None:
            log.info("Workfile not found or corrupt, aborting workfile update")
            return

        if not self.norm:
            self.signals.sigUpdate.emit(arr)
            return

        try:
            arr_norm = get_workfile_array(
                self.region, shape, kwargs, norm=True, as_array=True
            )
        except Exception:
            log.exception("Exception while fetching workfile norm array")
            arr_norm = None

        if arr.shape != arr_norm.shape:
            log.error(
                f"Array has shape {arr.shape} while norm array has "
                f"shape {arr_norm.shape}, only updating array"
            )
            arr_norm = None

        if arr_norm is None:
            self.signals.sigUpdate.emit(arr)

        arr = arr / arr_norm
        arr.values[~np.isfinite(arr.values)] = np.nan
        self.signals.sigUpdate.emit(arr)


def get_workfile_shape_kwargs(region: str) -> tuple[int | tuple[int, ...], dict]:
    """Get the shape and coordinates of a workfile region.

    For DA maps, the region info is saved with the ``.ini`` file present in the workfile
    folder. For other type of scans, we look for the ``Ses.ini`` file in the SES folder
    and try to read the detector settings from there. A single integer is returned,
    which corresponds to the number of x channels used by the detector.

    Since the detector slices will not change often, this is kinda unnecessary but
    exists for future proofing and to avoid hardcoding the number of slices.
    """
    ini_file = os.path.join(WORK_DIR, f"Spectrum_{region}.ini")

    with tempfile.TemporaryDirectory() as tmpdir:
        if os.path.isfile(ini_file):
            region_info = parse_ini(shutil.copy(ini_file, tmpdir))["spectrum"]
            shape, coords = get_shape_and_coords(region_info)
            kwargs = {"coords": coords, "name": region_info["name"]}
            return shape, kwargs

        else:
            ses_config = configparser.ConfigParser(strict=False)
            ses_ini_file = os.path.join(SES_DIR, r"ini\Ses.ini")

            with open(shutil.copy(ses_ini_file, tmpdir)) as f:
                ses_config.read_file(f)

            # Number of points on angle axis
            nslices = int(ses_config["Instrument Settings"]["Detector.Slices"])
            return nslices, {}


def get_workfile_array(
    region: str,
    shape: int | tuple[int],
    kwargs: dict,
    norm: bool = False,
    as_array: bool = False,
) -> xr.DataArray | np.ndarray | None:
    """Get the array from a workfile, given a region name.

    If shape is a single integer, the array is reshaped to that integer and the number
    of columns is calculated from the length of the array. If shape is a tuple, the
    array is reshaped to that shape.
    """
    if norm:
        binfile: str = f"Spectrum_{region}_Norm.bin"
    else:
        binfile: str = f"Spectrum_{region}.bin"

    binfile = os.path.join(WORK_DIR, binfile)

    if not os.path.isfile(binfile):
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        arr = np.fromfile(shutil.copy(binfile, tmpdir), dtype=np.float32)

    if isinstance(shape, int):
        arr = arr.reshape(shape, (int(len(arr) / shape)))
    else:
        arr = arr.reshape(shape)

    if as_array:
        return arr
    else:
        return xr.DataArray(arr, **kwargs)


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

        self.threadpool = QtCore.QThreadPool.globalInstance()

        for d in self.docks:
            d.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)

        widget = QtWidgets.QWidget()
        widget.setLayout(QtWidgets.QVBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)

        lowerwidget = QtWidgets.QWidget()
        lowerwidget.setLayout(QtWidgets.QHBoxLayout())
        lowerwidget.layout().setContentsMargins(0, 0, 0, 0)

        updatewidget = QtWidgets.QWidget()
        updatewidget.setLayout(QtWidgets.QHBoxLayout())
        updatewidget.layout().setContentsMargins(0, 0, 0, 0)

        self.region_combo = QtWidgets.QComboBox()
        self.region_combo.currentTextChanged.connect(self.reload)

        self.norm_check = QtWidgets.QCheckBox("Norm")
        self.norm_check.toggled.connect(self.reload)

        self.autoupdate_check = QtWidgets.QCheckBox("Auto update every")
        self.autoupdate_check.toggled.connect(self.refresh_update_timer)
        self.autoupdate_spin = QtWidgets.QDoubleSpinBox()
        self.autoupdate_spin.setMinimum(0.5)
        self.autoupdate_spin.setMaximum(60.0)
        self.autoupdate_spin.setValue(5.0)
        self.autoupdate_spin.setKeyboardTracking(False)
        self.autoupdate_spin.valueChanged.connect(self.refresh_update_timer)

        self.reload_btn = QtWidgets.QPushButton("Load")
        self.reload_btn.clicked.connect(self.reload)

        lowerwidget.layout().addWidget(self.norm_check)
        lowerwidget.layout().addWidget(self.reload_btn)
        updatewidget.layout().addWidget(self.autoupdate_check)
        updatewidget.layout().addWidget(self.autoupdate_spin)
        updatewidget.layout().addWidget(QtWidgets.QLabel("s"))
        widget.layout().addWidget(self.region_combo)
        widget.layout().addWidget(lowerwidget)
        widget.layout().addWidget(updatewidget)

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
        self.update_timer.timeout.connect(self.reload)

        self.mnb = ItoolMenuBar(self.slicer_area, self)

    @QtCore.Slot()
    def refresh_update_timer(self):
        self.update_timer.setInterval(round(self.autoupdate_spin.value() * 1000))
        if self.autoupdate_check.isChecked():
            self.update_timer.start()
        else:
            self.update_timer.stop()

    def update_regions(self):
        """Scan for regions in work directory."""
        regions: list[str] = [
            f[9:-9]
            for f in os.listdir(WORK_DIR)
            if f.startswith("Spectrum_") and f.endswith("_Norm.bin")
        ]

        if set(regions) == set(self.regions):
            # No change in regions, no need to update
            return
        else:
            self.regions = regions
            self.region_combo.clear()
            self.region_combo.addItems(self.regions)

    @QtCore.Slot()
    def reload(self):
        fetcher = WorkFileFetcher(
            self.region_combo.currentText(), self.norm_check.isChecked()
        )
        fetcher.signals.sigUpdate.connect(self.update_data)
        self.threadpool.start(fetcher)

    @QtCore.Slot(object)
    def update_data(self, arr):
        if check_same_coord_limits(self.array_slicer._obj, arr):
            if self.array_slicer._obj.shape == arr.shape:
                self.array_slicer._obj[:] = arr.values
            else:
                self.array_slicer._obj[:] = arr.transpose(
                    *self.array_slicer._obj.dims
                ).values

            self.array_slicer.clear_val_cache(include_vals=True)
            self.slicer_area.refresh_all(only_plots=True)

        else:
            if set(self.array_slicer._obj.dims) == set(arr.dims):
                self.slicer_area.set_data(arr.transpose(*self.array_slicer._obj.dims))
            else:
                self.slicer_area.set_data(arr)

        self.setWindowTitle(f"Work : {self.region_combo.currentText()}")


def check_same_coord_limits(arr1, arr2):
    """Check if two xarray DataArrays have the same coordinate limits.

    Returns True if the shape and dimensions are the same and the bounds of the
    coordinates for each dimension are the same.
    """
    if arr1.ndim != arr2.ndim:
        return False

    if set(arr1.shape) != set(arr2.shape):
        return False

    if set(arr1.dims) != set(arr2.dims):
        return False

    # Loose comparison for performance
    for d in arr1.dims:
        if not np.isclose(arr1.coords[d][0], arr2.coords[d][0]):
            return False

        if not np.isclose(arr1.coords[d][-1], arr2.coords[d][-1]):
            return False

    return True


def get_shape_and_coords(
    region_info: dict[str, str],
) -> tuple[tuple[int, ...], dict[str, np.ndarray]]:
    """Get the shape and coordinates of a workfile region.

    The input is a dictionary parsed from an .ini file in the work folder.
    """
    shape: list[int] = []
    coords: dict[str, np.ndarray] = {}
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
    """Parse an .ini file and return a dictionary of sections.

    The case of the keys is preserved.
    """
    parser = CasePreservingConfigParser(strict=False)
    out = {}
    with open(filename) as f:
        parser.read_file(f)
        for section in parser.sections():
            out[section] = dict(parser.items(section))
    return out
