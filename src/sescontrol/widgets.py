import datetime
import sys
import time

import humanize
import numpy as np
import pyqtgraph as pg

sys.coinit_flags = 2

from qtpy import QtCore, QtGui, QtWidgets, uic

from sescontrol.liveviewer import LiveImageTool
from sescontrol.plugins import Motor
from sescontrol.scan import MotorPosWriter, ScanWorker
from sescontrol.ses_win import SESController, get_file_info, next_index

# pywinauto imports must come after Qt imports
# https://github.com/pywinauto/pywinauto/issues/472#issuecomment-489816553


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
        if self.delta.isEnabled():
            self.boundschanged()
            return
        else:
            delta = self.delta.value()
            self.motor_coord = delta * np.arange(
                self.start.value() / delta,
                self.start.value() / delta + self.nstep.value(),
            )
            self._refresh_values()

    @QtCore.Slot()
    def boundschanged(self):
        if self.start.value() == self.end.value():
            self.end.setValue(self.end.value() + self.delta.value())
            return
        if self.delta.isEnabled():
            self.motor_coord = np.linspace(
                self.start.value(), self.end.value(), self.nstep.value()
            )
        else:
            self.deltachanged()
            return
        self._refresh_values()

    @QtCore.Slot()
    def deltachanged(self):
        if self.delta.value() == 0:
            self.delta.setValue(1e-3)
            return
        delta = self.delta.value()
        self.motor_coord = delta * np.arange(
            self.start.value() / delta, self.end.value() / delta + 1
        )
        if len(self.motor_coord) == 1:
            self.motor_coord = np.array(
                [self.start.value(), self.start.value() + self.delta.value()]
            )
        self._refresh_values()


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
        self.threadpool = QtCore.QThreadPool()
        self.threadpool.start(self.pos_logger)

        self.current_file: str | None = None
        self.start_time: float | None = None
        self.step_times: list[float] = []

        self._itools: list[LiveImageTool | None] = []

    @property
    def itool(self):
        return self._itools[-1]

    @itool.setter
    def itool(self, imagetool: LiveImageTool):
        self._itools.append(imagetool)

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
        return self.motor1.npoints * self.motor2.npoints

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

    def start_scan(self):
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

        # get file information
        base_dir, base_file, valid_ext, _ = get_file_info()
        data_idx = next_index(base_dir, base_file, valid_ext)

        if self.damap_check.isChecked():
            self.itool = None
        else:
            self.itool = LiveImageTool(threadpool=self.threadpool)
            self.itool.set_params(motor_args, base_dir, base_file, data_idx)

        # prepare before start
        self.pre_process()

        if self.has_motor:
            self.initialize_logging(
                dirname=base_dir,
                filename=f"{base_file}{str(data_idx).zfill(4)}_motors.csv",
                prefix="_scan_",
                motor_args=motor_args,
            )
        scan_worker = ScanWorker(
            motor_args,
            base_dir,
            base_file,
            data_idx,
            valid_ext,
            self.damap_check.isChecked(),
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

    @QtCore.Slot(int)
    def step_started(self, niter: int):
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
        self.line.setText(text)

    @QtCore.Slot(int, object, object)
    def step_finished(self, niter: int, pos0, pos1):
        self.step_times.append(time.perf_counter() - self.start_time)

        # display status
        text: str = f"{self.current_file} | "

        motor_info: list[str] = []
        for pos, motor in zip((pos0, pos1), self.motors):
            if pos is not None:
                motor_info.append(f"{motor.name} = {pos0:.3f}")
        text += ", ".join(motor_info)
        text += " done"
        if niter < self.numpoints:
            text += ", moving to next point..."

        self.line.setText(text)
        self.progress.setValue(niter)
        if self.has_motor:
            # enter log entry
            entry = [niter, np.float32(pos0)]
            if pos1 is not None:
                entry.append(np.float32(pos1))
            self.pos_logger.write_pos([str(x) for x in entry])

    @QtCore.Slot(int, object, object)
    def update_live(self, niter, *args):
        if self.itool is None:
            return
        self.itool.trigger_fetch(niter)
        if not self.itool.isVisible():
            self.itool.show()

    @QtCore.Slot()
    def pre_process(self):
        # disable scan window during scan
        for m in self.motors:
            m.setDisabled(True)
        self.start_btn.setDisabled(True)
        self.damap_check.setDisabled(True)
        self.stop_btn.setDisabled(False)
        self.stop_point_btn.setDisabled(False)
        if self.itool is not None:
            self.itool.set_busy(True)

        self.progress.setRange(0, self.numpoints)
        self.progress.setTextVisible(True)

    @QtCore.Slot()
    def post_process(self):
        total_time = humanize.precisedelta(
            datetime.timedelta(seconds=time.perf_counter() - self.start_time)
        )
        self.line.setText(f"{self.current_file} | Finished in {total_time}")

        for m in self.motors:
            m.setDisabled(False)
        self.start_btn.setDisabled(False)
        self.damap_check.setDisabled(False)
        self.stop_btn.setDisabled(True)
        self.stop_point_btn.setText("Stop After Point")
        self.stop_point_btn.setDisabled(True)
        if self.itool is not None:
            self.itool.set_busy(False)

        self.current_file = None
        self.progress.reset()
        self.progress.setTextVisible(False)
        self.start_time = None
        self.step_times = []

    def initialize_logging(
        self,
        dirname,
        filename: str,
        prefix: str,
        motor_args: list[tuple[str, np.ndarray]],
    ):
        self.pos_logger.set_file(dirname, filename, prefix)
        header = [""]
        for motor in motor_args:
            header.append(motor[0])
        self.pos_logger.write_header(header)

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
        for win in self._itools:
            if win:
                win.close()
        self.pos_logger.stop()
        self.threadpool.waitForDone()
        super().closeEvent(event)


class SESShortcuts(QtWidgets.QWidget):

    sigAliveChanged = QtCore.Signal(bool)

    SES_ACTIONS: dict[str, tuple[str, str]] = {
        "Calibrate Voltages": ("Calibration", "Voltages..."),
        "File Options": ("Setup", "File Options..."),
        "Sequence Setup": ("Sequence", "Setup..."),
        "Control Theta": ("DA30", "Control Theta..."),
        "Center Deflection": ("DA30", "Center Deflection"),
    }

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(250)
        self.setWindowTitle("SES Shortcuts")
        self.setLayout(QtWidgets.QHBoxLayout(self))

        self.create_buttons()

        self.sigAliveChanged.connect(self.set_buttons_enabled)

        self.ses: SESController = SESController()

        self.reconnect_timer = QtCore.QTimer(self)
        self.reconnect_timer.setInterval(500)
        self.reconnect_timer.timeout.connect(self.check_alive)
        self.check_alive()
        self.reconnect_timer.start()

    @QtCore.Slot()
    def check_alive(self):
        alive = self.ses.alive
        if self.buttons[0].isEnabled() != alive:
            self.sigAliveChanged.emit(alive)
        if not self.ses.alive:
            self.ses.try_connect()

    @QtCore.Slot(object)
    def try_click(self, menu_path: tuple[str, str]):
        if menu_path == self.SES_ACTIONS["Calibrate Voltages"]:
            QtWidgets.QMessageBox.warning(
                self,
                "Reminder for MCP protection",
                "Check the slit number and photon flux!",
            )
        try:
            self.ses.click_menu(menu_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                str(e),
                f"SES control failed",
            )
            self.check_alive()

    @QtCore.Slot(bool)
    def set_buttons_enabled(self, value: bool):
        for btn in self.buttons:
            btn.setEnabled(value)

    def create_buttons(self):
        self.buttons: list[QtWidgets.QPushButton] = []
        for label, path in self.SES_ACTIONS.items():
            btn = QtWidgets.QPushButton(label, self)
            btn.clicked.connect(lambda *, path=path: self.try_click(path))
            self.layout().addWidget(btn)
            self.buttons.append(btn)
