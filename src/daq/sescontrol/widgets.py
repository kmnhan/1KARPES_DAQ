import datetime
import gc
import logging
import os
import sys
import time
import uuid
from collections.abc import Callable, Sequence

import humanize
import numpy as np
import numpy.typing as npt
import pyqtgraph as pg

sys.coinit_flags = 2

from erlab.interactive.imagetool import manager
from qtpy import QtCore, QtGui, QtWidgets, uic

from sescontrol.liveviewer import LiveImageTool, WorkFileImageTool
from sescontrol.plugins import Motor
from sescontrol.scan import MotorPosWriter, ScanWorker, gen_data_name, restore_names
from sescontrol.ses_win import SES_ACTIONS, SESController, get_file_info, next_index

# pywinauto imports must come after Qt imports
# https://github.com/pywinauto/pywinauto/issues/472#issuecomment-489816553

try:
    os.chdir(sys._MEIPASS)
except:  # noqa: E722
    pass

log = logging.getLogger("scan")


class SingleMotorSetup(QtWidgets.QGroupBox):
    valueChanged = QtCore.Signal(float, float, float, int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        self.setCheckable(True)

        self.setLayout(QtWidgets.QVBoxLayout(self))

        self.combo = QtWidgets.QComboBox(self)
        self.layout().addWidget(self.combo)

        motors = QtWidgets.QWidget(self)
        self.layout().addWidget(motors)
        motors.setLayout(QtWidgets.QFormLayout(motors))

        self.motor_coord = np.linspace(0, 1, 11)
        self.start, self.end, self.delta, self.nstep = (
            pg.SpinBox(compactHeight=False, value=self.motor_coord[0]),
            pg.SpinBox(compactHeight=False, value=self.motor_coord[-1]),
            pg.SpinBox(
                compactHeight=False,
                value=self.motor_coord[1] - self.motor_coord[0],
            ),
            pg.SpinBox(
                compactHeight=False,
                value=len(self.motor_coord),
                int=True,
                step=1,
                min=2,
            ),
        )
        motors.layout().addRow("Start", self.start)
        motors.layout().addRow("End", self.end)
        motors.layout().addRow("Delta", self.delta)
        motors.layout().addRow("Num", self.nstep)

        self.start.sigValueChanged.connect(self.boundschanged)
        self.end.sigValueChanged.connect(self.boundschanged)
        self.nstep.sigValueChanged.connect(self.countchanged)
        self.delta.sigValueChanged.connect(self.deltachanged)

    def _refresh_values(self):
        for w in (self.start, self.end, self.delta, self.nstep):
            w.blockSignals(True)

        self.start.setValue(self.motor_coord[0])
        self.end.setValue(self.motor_coord[-1])
        self.delta.setValue(self.motor_coord[1] - self.motor_coord[0])
        self.nstep.setValue(len(self.motor_coord))

        for w in (self.start, self.end, self.delta, self.nstep):
            w.blockSignals(False)

        self.valueChanged.emit(
            self.start.value(), self.end.value(), self.delta.value(), self.nstep.value()
        )

    @property
    def npoints(self) -> int:
        if self.isChecked():
            return len(self.motor_coord)
        else:
            return 1

    @property
    def name(self) -> str:
        return self.combo.currentText()

    @property
    def motor_properties(self) -> tuple[str, np.ndarray] | None:
        if self.isChecked():
            return (self.combo.currentText(), self.motor_coord)
        else:
            return None

    def set_limits(self, minimum: float | None, maximum: float | None):
        if minimum is None:
            minimum = -np.inf
        if maximum is None:
            maximum = np.inf
        self.start.setMinimum(minimum)
        self.end.setMinimum(minimum)
        self.start.setMaximum(maximum)
        self.end.setMaximum(maximum)

    def set_default_delta(self, value: float):
        """Set initial value for delta and whether to allow changes."""
        self.start.setSingleStep(value)
        self.end.setSingleStep(value)
        self.delta.setValue(value)

    @QtCore.Slot()
    def countchanged(self):
        delta = self.delta.value()

        self.motor_coord = np.linspace(
            self.start.value(),
            self.start.value() + delta * (self.nstep.value() - 1),
            self.nstep.value(),
        )

        self._refresh_values()

    @QtCore.Slot()
    def boundschanged(self):
        if self.start.value() == self.end.value():
            self.end.setValue(self.end.value() + self.delta.value())
            return
        self.deltachanged()

    @QtCore.Slot()
    def deltachanged(self):
        if self.delta.value() == 0:
            self.delta.setValue(1e-3)
            return
        delta = self.delta.value()
        difference = self.end.value() - self.start.value()

        if np.sign(difference) != np.sign(delta):
            self.delta.setValue(-delta)
            return

        nstep = round(difference / delta) + 1
        if nstep <= 1:
            self.motor_coord = np.array(
                [
                    self.start.value(),
                    self.start.value() + self.delta.value(),
                ]
            )
        else:
            self.motor_coord = np.linspace(
                self.start.value(), self.start.value() + delta * (nstep - 1), nstep
            )
        self._refresh_values()


class ArrayTableModel(QtCore.QAbstractTableModel):
    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self.set_array(np.array([[]]), [])

    def set_array(self, array: npt.NDArray, clabels: Sequence[str]):
        self.beginResetModel()
        self._array = array
        self._clabels = clabels
        self.endResetModel()

    def rowCount(self, parent=None):
        return self._array.shape[0]

    def columnCount(self, parent=None):
        return self._array.shape[1]

    def data(self, index: QtCore.QModelIndex, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if (
            role == QtCore.Qt.ItemDataRole.DisplayRole
            or role == QtCore.Qt.ItemDataRole.EditRole
        ):
            return str(self._array[index.row(), index.column()])
        elif role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return int(
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
        return None

    def setData(
        self, index: QtCore.QModelIndex, value, role=QtCore.Qt.ItemDataRole.EditRole
    ):
        if index.isValid() and role == QtCore.Qt.ItemDataRole.EditRole:
            try:
                self._array[index.row(), index.column()] = float(value)
            except ValueError:
                return False
            self.dataChanged.emit(index, index, [role])
            return True

        return False

    def flags(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags

        return (
            QtCore.Qt.ItemFlag.ItemIsEditable
            | QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
        )

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.ItemDataRole.DisplayRole,
    ):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if orientation == QtCore.Qt.Orientation.Horizontal:
                return str(self._clabels[section])
            elif orientation == QtCore.Qt.Orientation.Vertical:
                return str(section + 1)


class MotorDialog(*uic.loadUiType("sescontrol/motordialog.ui")):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle("Motor Coordinates")
        self.table.setModel(ArrayTableModel())
        self.table.model().dataChanged.connect(self.update)
        self.table.model().modelReset.connect(self.update)
        self.raster_check.toggled.connect(self.refresh_raster)
        self.reset_btn.clicked.connect(self.refresh_raster)

    @staticmethod
    def get_motion_array(
        motor_coords: dict[str, npt.NDArray], raster: bool = False
    ) -> npt.NDArray[np.float64]:
        """Given coordinates, returns all positions to be visited in a scan.

        Parameters
        ----------
        motor_coords : dict[str, npt.NDArray]
            Mapping of motor names to their coordinates.
        raster : bool, optional
            If True, the second axis is repeated in reverse order every odd iteration.
            Has no effect if the number of axes is not 2.

        Returns
        -------
        npt.NDArray[np.float64]
            N by M array, where N is the number of points and M is the number of axes.
        """
        numpoints: int = 1
        for v in motor_coords.values():
            numpoints *= len(v)

        out = np.zeros((numpoints, len(motor_coords)), dtype=np.float64)
        if len(motor_coords) == 1:
            out[:, 0] = next(iter(motor_coords.values()))
        elif len(motor_coords) == 2:
            coords = tuple(motor_coords.values())
            shape = tuple(c.size for c in coords)

            for i in range(shape[0]):
                out[i * shape[1] : (i + 1) * shape[1], 0] = coords[0][i]
                if raster or i % 2 == 0:
                    out[i * shape[1] : (i + 1) * shape[1], 1] = coords[1]
                else:
                    out[i * shape[1] : (i + 1) * shape[1], 1] = np.flip(coords[1])
        return out

    def set_motor_coords(self, motor_coords: dict[str, npt.NDArray]):
        self.motor_coords = motor_coords
        self.raster_check.setEnabled(len(self.motor_coords) == 2)
        self.refresh_raster()

    def refresh_raster(self):
        self.table.model().set_array(self.array, tuple(self.motor_coords.keys()))

    @property
    def edited(self) -> bool:
        """Get whether the table entry has been edited by the user."""
        return not np.allclose(self.array, self.modified_array)

    @property
    def rasterized(self) -> bool:
        return self.raster_check.isChecked()

    @property
    def array(self) -> npt.NDArray[np.float64]:
        return self.get_motion_array(self.motor_coords, self.rasterized)

    @property
    def modified_array(self) -> npt.NDArray[np.float64]:
        return self.table.model()._array.astype(np.float64)

    def update(self):
        self.reset_btn.setEnabled(self.edited)
        arr = self.table.model()._array
        labels = self.table.model()._clabels
        plot_kw = {
            "symbol": "o",
            "pen": "#0380fc",
            "symbolSize": 6,
            "symbolPen": "#0380fc",
            "symbolBrush": "#0380fc",
        }
        self.pw.clear()
        if arr.shape[1] == 0:
            pass
        elif arr.shape[1] == 1:
            self.pw.setLabel("left", labels[0])
            self.pw.setLabel("bottom", "Iteration")
            self.pw.plot(arr[:, 0], **plot_kw)
        elif arr.shape[1] == 2:
            self.pw.setLabel("left", labels[1])
            self.pw.setLabel("bottom", labels[0])
            self.pw.plot(arr[:, 0], arr[:, 1], **plot_kw)
        self.pw.showGrid(x=True, y=True, alpha=0.5)


class RenameDialog(*uic.loadUiType("sescontrol/renamedialog.ui")):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle("Rename Files")
        self.accepted.connect(self.restore)

    def populate(self):
        base_dir, base_file, valid_ext, _, _ = get_file_info()

        self.line_dir.setText(base_dir)
        self.line_name.setText(base_file)
        self.line_ext.setText(", ".join(valid_ext))

    @QtCore.Slot()
    def restore(self):
        return restore_names(
            extensions=list(self.line_ext.text().split(", ")),
            directory=self.line_dir.text(),
            basename=self.line_name.text(),
        )


class ScanType(*uic.loadUiType("sescontrol/scantype.ui")):
    sigStopPoint = QtCore.Signal()
    sigCancelStopPoint = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)

        for i, motor in enumerate(self.motors):
            motor.combo.currentTextChanged.connect(
                lambda *, ind=i: self.motor_changed(ind)
            )
            motor.toggled.connect(lambda *, ind=i: self.motor_changed(ind))
        self.update_motor_list()

        self.start_btn.clicked.connect(self.start_scan)
        self.stop_point_btn.clicked.connect(self.handle_stop_point)

        self.pos_logger = MotorPosWriter()
        self.threadpool = QtCore.QThreadPool.globalInstance()
        self.threadpool.start(self.pos_logger)

        self.current_file: str | None = None
        self.start_time: float | None = None
        self.step_times: list[float] = []

        self._workfileitool: WorkFileImageTool | None = None
        self._itools: dict[str, LiveImageTool] = {}
        self._active_itool: str | None = None

        self.motor_dialog: MotorDialog = MotorDialog()

        self.rename_dialog: RenameDialog = RenameDialog()

        # Timer to update remaining time for current scan
        self.timeleft_update_timer = QtCore.QTimer(self)
        self.timeleft_update_timer.setInterval(1000)
        self.timeleft_update_timer.timeout.connect(self.update_remaining_time)

        # Current iteration, used for progress bar
        self._niter: int = 0

    @QtCore.Slot()
    def _workfile_viewer_closed(self):
        self._workfileitool = None

    @QtCore.Slot()
    def show_workfile_viewer(self):
        if self._workfileitool is None:
            self._workfileitool = WorkFileImageTool()
            self._workfileitool.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
            self._workfileitool.destroyed.connect(self._workfile_viewer_closed)
        self._workfileitool.show()

    def new_itool(self):
        uid: str = str(uuid.uuid4())
        tool = LiveImageTool()
        tool.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self._itools[uid] = tool
        self._active_itool = uid
        tool.destroyed.connect(lambda: self._itools.pop(uid))

    @property
    def itool(self) -> LiveImageTool | None:
        """Get the last created LiveImageTool."""
        if self._active_itool:
            return self._itools[self._active_itool]
        return None

    @property
    def valid_axes(self) -> list[str]:
        """Get all enabled motor plugins."""
        return [k for k, v in Motor.plugins.items() if v.enabled]

    @property
    def motors(self) -> tuple[SingleMotorSetup, SingleMotorSetup]:
        """Motor widgets."""
        return self.motor1, self.motor2

    @property
    def numpoints(self) -> int:
        """Total number of acquisition points."""
        return int(self.motor1.npoints * self.motor2.npoints)

    @property
    def has_motor(self) -> bool:
        """Whether at least one motor is enabled."""
        return self.motors[0].isChecked() or self.motors[1].isChecked()

    @property
    def time_per_step(self) -> float:
        if len(self.step_times) <= 1:
            return np.inf
        return np.mean(np.diff(self.step_times))

    def update_motor_list(self):
        for i, m in enumerate(self.motors):
            m.combo.blockSignals(True)
            m.combo.clear()
            m.combo.addItems(self.valid_axes)
            m.combo.setCurrentIndex(i)
            m.combo.blockSignals(False)
            m.setChecked(False)

    def motor_changed(self, index):
        # apply motion limits
        #!TODO: this is stupid
        self.update_motor_limits(index)

    def update_motor_limits(self, index: int):
        """Get motor limits from corresponding plugin and update values."""
        try:
            plugin: Motor = Motor.plugins[self.motors[index].name]
        except KeyError:
            return
        else:
            plugin_instance = plugin()
            plugin_instance.pre_motion()
            mn, mx = plugin_instance.minimum, plugin_instance.maximum
            # properly cast into float in case the return type is incompatible
            if mn is not None:
                mn = float(mn)
            if mx is not None:
                mx = float(mx)

            motor = self.motors[index]
            motor.set_limits(mn, mx)
            if plugin_instance.delta is not None:
                motor.set_default_delta(float(plugin_instance.delta))
            motor.delta.setDisabled(plugin_instance.fix_delta)

            plugin_instance.post_motion()

    @QtCore.Slot()
    def handle_stop_point(self):
        if self.stop_point_btn.text() == "Cancel Stop":
            self.sigCancelStopPoint.emit()
            self.stop_point_btn.setText("Stop After Point")
        else:
            self.sigStopPoint.emit()
            self.stop_point_btn.setText("Cancel Stop")

    def is_startable(self):
        ses = SESController()
        path = (
            ses._ses_app.window(handle=ses._hwnd).menu().get_menu_path("Sequence->Run")
        )
        if not path[-1].is_enabled():
            QtWidgets.QMessageBox.critical(
                self,
                "Cannot start scan",
                "The sequence menu is disabled. A window may be open.",
            )
            return False
        return True

    def start_scan(self):
        if not self.is_startable():
            return

        # get motor arguments only if enabled
        motor_args: list[tuple[str, np.ndarray]] = [
            m.motor_properties for m in self.motors if m.isChecked()
        ]
        if len(motor_args) == 2:
            if motor_args[0][0] == motor_args[1][0]:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Duplicate Axes",
                    "The second motor axes must be different from the first.",
                )
                return

        motor_coords: dict[str, npt.NDArray] = {}
        for ma in motor_args:
            motor_coords[ma[0]] = ma[1]

        self.motor_dialog.set_motor_coords(motor_coords)

        if len(motor_coords) != 0:
            # Open motor edit dialog
            ret = self.motor_dialog.exec()
            if not ret:
                # Cancelled
                return

        motion_array: npt.NDArray[np.float64] = self.motor_dialog.modified_array
        motion_edited: bool = self.motor_dialog.edited
        motion_raster: bool = self.motor_dialog.rasterized

        # Get file information
        base_dir, base_file, valid_ext, _, sequences = get_file_info()
        data_idx = next_index(base_dir, base_file, valid_ext)

        seq_is_da: list[bool] = [
            seq["run mode"] == "ARPES Mapping" for seq in sequences
        ]
        has_da = any(seq_is_da)
        only_da = all(seq_is_da)

        if only_da:
            self._active_itool = None
        else:
            self.new_itool()
            if motion_edited:
                # If the motion array was edited, coords may not be uniform
                iter_coords = {"Iteration": np.arange(self.numpoints)}
                self.itool.set_params(
                    iter_coords, motion_raster, base_dir, base_file, data_idx
                )
            else:
                self.itool.set_params(
                    motor_coords, motion_raster, base_dir, base_file, data_idx
                )

        # Prepare before start
        self.pre_process()

        motors: list[str] = list(motor_coords.keys())
        if self.has_motor:
            self.initialize_logging(
                dirname=base_dir, base_file=base_file, data_idx=data_idx, motors=motors
            )
        scan_worker = ScanWorker(
            motors, motion_array, base_dir, base_file, data_idx, valid_ext, has_da
        )
        scan_worker.signals.sigStepFinished.connect(self.step_finished)
        scan_worker.signals.sigStepFinished.connect(self.update_live)
        scan_worker.signals.sigStepStarted.connect(self.step_started)
        scan_worker.signals.sigFinished.connect(self.post_process)
        self.stop_btn.clicked.connect(scan_worker.force_stop)
        # self.stop_point_btn.clicked.connect(scan_worker.stop_after_point)
        self.sigStopPoint.connect(scan_worker.stop_after_point)
        self.sigCancelStopPoint.connect(scan_worker.cancel_stop_after_point)

        self.current_file = scan_worker.data_name

        self.start_time = time.perf_counter()
        self.step_times.append(0.0)
        self.threadpool.start(scan_worker)

    @QtCore.Slot()
    def update_remaining_time(self):
        if self.start_time is None:
            return

        text: str = f"{self.current_file}"
        if self._niter == 1:
            text += " started"
        else:
            after_point = (
                self.numpoints - self._niter
            ) * self.time_per_step  # Time left excluding current point
            last_step_finished = (
                self.start_time + self.step_times[-1]
            )  # When the last step finished
            point_remaining = self.time_per_step - (
                time.perf_counter() - last_step_finished
            )  # Time left for current point

            total_remaining_str: str = humanize.naturaldelta(
                datetime.timedelta(seconds=after_point + point_remaining)
            )
            point_remaining_str: str = humanize.naturaldelta(
                datetime.timedelta(seconds=point_remaining)
            )
            step_str: str = humanize.precisedelta(
                datetime.timedelta(seconds=self.time_per_step)
            )

            text += " | "
            text += f"{total_remaining_str} left ({step_str} per point)"
            text += " | "
            text += f"{point_remaining_str} left for this point"

        self.line.setText(text)

    @QtCore.Slot(int)
    def step_started(self, niter: int):
        self._niter = niter
        text: str = f"{self.current_file}"
        if niter == 1:
            text += " started"
        else:
            steptime: float = self.time_per_step
            timeleft: float = (self.numpoints - (niter - 1)) * steptime

            timeleft: str = humanize.naturaldelta(datetime.timedelta(seconds=timeleft))
            steptime: str = humanize.precisedelta(datetime.timedelta(seconds=steptime))

            text += " | "
            text += f"{timeleft} left ({steptime} per point)"
        self._base_progress_text = text
        self.update_remaining_time()
        self.timeleft_update_timer.start()

    @QtCore.Slot(int, object)
    def step_finished(self, niter: int, pos: tuple[float, ...]):
        self.timeleft_update_timer.stop()
        self.step_times.append(time.perf_counter() - self.start_time)

        # Display status
        text: str = f"{self.current_file} | "

        motor_info: list[str] = []
        for p, motor in zip(pos, self.motors, strict=False):
            motor_info.append(f"{motor.name} = {p:.3f}")
        text += ", ".join(motor_info)
        text += " done"
        if niter < self.numpoints:
            text += ", moving to next point..."

        self.line.setText(text)
        self.progress.setValue(niter)

        if self.has_motor:
            # Enter log entry
            entry = [niter] + [float(p) for p in pos]
            self.pos_logger.write_pos([str(x) for x in entry])

    @QtCore.Slot(int, object)
    def update_live(self, niter, *args):
        if self.itool is None:
            return
        self.itool.trigger_fetch(niter)

        if self.numpoints == 1 and manager.is_running():
            # Do not show window here, it will be shown after the scan
            return

        if not self.itool.isVisible():
            self.itool.show()

    @QtCore.Slot()
    def pre_process(self):
        # disable scan window during scan
        for m in self.motors:
            m.setDisabled(True)
        self.start_btn.setDisabled(True)
        self.stop_btn.setDisabled(False)
        self.stop_point_btn.setDisabled(False)
        if self.itool is not None:
            self.itool.set_busy(True)

        self.progress.setRange(0, self.numpoints)
        self.progress.setTextVisible(True)

    @QtCore.Slot()
    def post_process(self):
        self.timeleft_update_timer.stop()
        total_time = humanize.precisedelta(
            datetime.timedelta(seconds=time.perf_counter() - self.start_time)
        )
        self.line.setText(f"{self.current_file} | Finished in {total_time}")

        for m in self.motors:
            m.setDisabled(False)
        self.start_btn.setDisabled(False)
        self.stop_btn.setDisabled(True)
        self.stop_point_btn.setText("Stop After Point")
        self.stop_point_btn.setDisabled(True)
        if self.itool is not None:
            self.itool.set_busy(False)

            if len(self.itool.motor_controls.valid_dims) == 0:
                self.itool.to_manager()

        self.current_file = None
        self._niter = 0
        self.progress.reset()
        self.progress.setTextVisible(False)
        self.start_time = None
        self.step_times = []

    def initialize_logging(
        self,
        dirname: str | os.PathLike,
        base_file: str,
        data_idx: int,
        motors: Sequence[str],
    ):
        self.pos_logger.set_file(dirname, base_file, data_idx)
        header = ["", *list(motors)]
        self.pos_logger.write_header(header)

    @QtCore.Slot()
    def fix_files(self):
        self.rename_dialog.populate()
        self.rename_dialog.exec()

    def closeEvent(self, event: QtGui.QCloseEvent):
        if self.isEnabled() and not self.start_btn.isEnabled():
            # If the widget is enabled but the start button is disabled, there is an
            # ongoing measurement
            ret = QtWidgets.QMessageBox.question(
                self, "A measurement is still running", "Force close?"
            )
            if not ret == QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
        self.pos_logger.stop()
        super().closeEvent(event)


class SESShortcuts(QtWidgets.QWidget):
    """
    A widget that provides shortcuts for SES.exe control.

    Attributes
    ----------
    sigAliveChanged
        A signal emitted when the SES connection status changes.

    """

    sigAliveChanged = QtCore.Signal(bool)

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(250)
        self.setLayout(QtWidgets.QHBoxLayout(self))
        self.layout().setContentsMargins(0, 0, 0, 0)

        self.create_buttons()

        self.sigAliveChanged.connect(self.set_buttons_enabled)

        self.ses: SESController = SESController()

        self.alive_check_timer = QtCore.QTimer(self)
        self.alive_check_timer.setInterval(1000)
        self.alive_check_timer.timeout.connect(self.check_alive)
        self.check_alive()
        self.alive_check_timer.start()

    @QtCore.Slot()
    def check_alive(self):
        alive = self.ses.alive
        if self.buttons[0].isEnabled() != alive:
            self.sigAliveChanged.emit(alive)

    @QtCore.Slot()
    def reconnect(self):
        if not self.ses.alive:
            self.ses.try_connect()

    @QtCore.Slot(str)
    @QtCore.Slot(str, object)
    def try_click(self, path: str, match: Callable[[str], bool] | None = None):
        if path == SES_ACTIONS["Calibrate Voltages"][0]:
            ret = QtWidgets.QMessageBox.warning(
                self,
                "Reminder for MCP protection",
                "Check the slit number and photon flux!",
            )
            if ret == QtWidgets.QMessageBox.StandardButton.Cancel:
                return
        try:
            self.ses.click_menu(path, match)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, str(e), "SES control failed")
            self.check_alive()

    @QtCore.Slot(bool)
    def set_buttons_enabled(self, value: bool):
        for btn in self.buttons:
            btn.setEnabled(value)

    def create_buttons(self):
        self.buttons: list[QtWidgets.QPushButton] = []
        for label, args in SES_ACTIONS.items():
            btn = QtWidgets.QPushButton(label)

            btn.clicked.connect(lambda *, args=args: self.try_click(*args))
            self.layout().addWidget(btn)
            btn.setMinimumWidth(btn.fontMetrics().boundingRect(btn.text()).width() + 14)
            self.buttons.append(btn)
