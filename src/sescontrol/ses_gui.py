import csv
import glob
import os
import sys
import time
import zipfile
from collections import deque
from collections.abc import Iterable

sys.coinit_flags = 2

os.environ["QT_API"] = "pyqt6"
from qtpy import QtCore, QtWidgets, uic

# pywinauto imports must come after Qt imports
# https://github.com/pywinauto/pywinauto/issues/472#issuecomment-489816553


try:
    os.chdir(sys._MEIPASS)
except:
    pass

import numpy as np
import pywinauto
import pywinauto.win32functions
import win32.lib.pywintypes
from liveviewer import LiveImageTool
from plugins import Motor
from scanwidgets import SingleMotorSetup
from ses_win import SESController, get_file_info, get_ses_properties, next_index

SES_DIR = os.getenv("SES_BASE_PATH", "D:/SES_1.9.6_Win64")


"""
Limitations

Only `zip-format` must be selected in file options
Multiple DA maps in a single region not supported


"""


class MotorPosWriter(QtCore.QRunnable):
    def __init__(self):
        super().__init__()
        self._stopped: bool = False
        self.messages: deque[list[str]] = deque()
        self.dirname: str | os.PathLike | None = None
        self.filename: str | os.PathLike | None = None
        self.prefix: str | None = None

    def run(self):
        self._stopped = False
        while not self._stopped:
            time.sleep(0.2)
            if len(self.messages) == 0:
                continue
            msg = self.messages.popleft()
            try:
                # if file without prefix exists, the scan has finished but we have
                # remaining log entries to enter.
                fname = os.path.join(self.dirname, self.filename)
                if not os.path.isfile(fname):
                    fname = os.path.join(self.dirname, self.prefix + str(self.filename))
                with open(fname, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(msg)
            except PermissionError:
                self.messages.appendleft(msg)
                continue

    def stop(self):
        n_left = len(self.messages)
        if n_left != 0:
            print(
                f"Failed to write {n_left} " + ("entries:" if n_left > 1 else "entry:")
            )
            for msg in self.messages:
                print(",".join(msg))
        self._stopped = True

    def set_file(
        self, dirname: str | os.PathLike, filename: str | os.PathLike, prefix: str
    ):
        self.dirname = dirname
        self.filename = filename
        self.prefix = prefix

    def write_pos(self, content: str | list[str]):
        """Appends content to log file."""
        if isinstance(content, str):
            content = [content]
        self.messages.append(content)

    def write_header(self, header: str | list[str]):
        """Creates and appends a header to log file.

        If a file with the same name already exists, it will be removed.

        """

        file_name = os.path.join(self.dirname, self.prefix + str(self.filename))
        if os.path.isfile(file_name):
            os.remove(file_name)
        self.write_pos(header)


class ScanWorkerSignals(QtCore.QObject):
    sigStepFinished = QtCore.Signal(int, object, object)
    sigStepStarted = QtCore.Signal(int)
    sigFinished = QtCore.Signal()


class ScanWorker(QtCore.QRunnable):
    def __init__(
        self,
        motor_args: list[tuple[str, np.ndarray]],
        base_dir: str,
        base_file: str,
        data_idx: int,
        valid_ext: Iterable[str],
        has_da: bool,
    ):
        super().__init__()

        self.axes: list[Motor] = []
        self.coords: list[np.ndarray] = []
        for ma in motor_args:
            self.axes.append(Motor.plugins[ma[0]]())
            self.coords.append(ma[1])

        self.base_dir = base_dir
        self.base_file = base_file
        self.data_idx = data_idx
        self.valid_ext = valid_ext
        self.has_da = has_da

        self.signals = ScanWorkerSignals()
        self._pid, self._hwnd = get_ses_properties()
        self._ses_app = pywinauto.Application(backend="win32").connect(
            process=self._pid
        )

        self._stop: bool = False
        self._stopnow: bool = False

    def check_finished(self) -> bool:
        """Returns whether if sequence is finished."""
        path = (
            self._ses_app.window(handle=self._hwnd)
            .menu()
            .get_menu_path("Sequence->Run")
        )
        return path[-1].is_enabled()

    def click_sequence_button(self, button: str):
        """Click a button in the Sequence menu."""
        while True:
            try:
                path = (
                    self._ses_app.window(handle=self._hwnd)
                    .menu()
                    .get_menu_path(f"Sequence->{button}")
                )
                path[-1].ctrl.send_message(path[-1].menu.COMMAND, path[-1].item_id())
                pywinauto.win32functions.WaitGuiThreadIdle(path[-1].ctrl.handle)
            except win32.lib.pywintypes.error as e:
                print(e)
                continue
            else:
                break

    def stop_after_point(self):
        """Stop after acquiring current motor point."""
        self._stop = True

    def force_stop(self):
        """Force stop now."""
        self._stop = True
        self._stopnow = True

    def sequence_run_wait(self) -> int:
        """Run sequence and wait until it finishes."""

        workfiles = os.listdir(os.path.join(SES_DIR, "work"))

        # click run button
        self.click_sequence_button("Run")
        time.sleep(0.01)

        # keep checking for abort during scan
        aborted: bool = False
        while True:
            if (not aborted) and self._stopnow:
                self.click_sequence_button("Force Stop")
                aborted = True
            if self.check_finished():
                break
            time.sleep(0.001)

        if self.has_da:
            # DA maps take time to save even after scan ends, let's try to wait
            timeout_start = time.monotonic()
            fname = os.path.join(
                self.base_dir,
                f"{self.base_file}{str(self.data_idx).zfill(4)}.zip",
            )
            while True:
                time.sleep(0.2)
                if os.path.isfile(fname) and os.stat(fname).st_size != 0:
                    try:
                        with zipfile.ZipFile(fname, "r") as _:
                            # do nothing, just trying to open the file
                            pass
                    except zipfile.BadZipFile:
                        continue
                    else:
                        # zipfile is intact, check work folder to confirm
                        if len(workfiles) == len(
                            os.listdir(os.path.join(SES_DIR, "work"))
                        ):
                            break
                elif self._stop and time.monotonic() > timeout_start + 20:
                    # SES 상에서 stop after something 누른 다음 stop after point를 통해
                    # abort할 시에는 DA map이 영영 저장되지 않을 수도 있으니까 20초
                    # 기다려서 안 되면 그냥 안 되는갑다 하기
                    break
        if aborted:
            return 1
        return 0

    def run(self):
        if len(self.axes) == 0:
            # no motors, single scan
            self.signals.sigStepStarted.emit(1)
            self.sequence_run_wait()
            self.signals.sigStepFinished.emit(1, 0, 0)
        else:
            if len(self.axes) == 1:
                self.coords.append([[0]])

            for i, ax in enumerate(self.axes):
                ax.pre_motion()

                # last sanity check of bounds before motion
                if (ax.minimum is not None and min(self.coords[i]) < ax.minimum) or (
                    ax.maximum is not None and max(self.coords[i]) > ax.maximum
                ):
                    ax.post_motion()
                    self.signals.sigFinished.emit()
                    print("PARAMETERS OUT OF MOTOR BOUNDS")
                    return

            self._motion_loop()

            for ax in self.axes:
                ax.post_motion()

            # restore mangled filenames
            self._restore_filenames()

        self.signals.sigFinished.emit()

    def _rename_file(self, index: int):
        """Renames the data file to include the slice index.

        This function adjusts file names to maintain a constant file number during
        scans. File names are temporarily modified during scanning by adding a prefix,
        which is later restored using `restore_filenames` when all scans are completed.

        This is possible because SES determines the sequence number by parsing the name
        of the files in the data directory.

        Parameters
        ----------
        index : int
            Index of the scan to rename.

        """
        for ext in self.valid_ext:
            f = os.path.join(
                self.base_dir, f"{self.base_file}{str(self.data_idx).zfill(4)}{ext}"
            )
            new = os.path.join(
                self.base_dir,
                "_scan_"
                + self.base_file
                + str(self.data_idx).zfill(4)
                + f"_S{str(index).zfill(5)}"
                + ext,
            )
            if os.path.isfile(f):
                while True:
                    try:
                        os.rename(f, new)
                    except PermissionError:
                        time.sleep(0.001)
                        continue
                    else:
                        break

    def _restore_filenames(self):
        files = []
        for ext in list(self.valid_ext) + [".csv"]:
            files += glob.glob(
                os.path.join(self.base_dir, f"_scan_{self.base_file}*{ext}")
            )
        for f in files:
            new = f.replace(
                os.path.basename(f), os.path.basename(f).replace("_scan_", "")
            )
            while True:
                try:
                    os.rename(f, new)
                except PermissionError:
                    time.sleep(0.001)
                    continue
                except FileExistsError:
                    if f.endswith(".csv"):
                        with open(f, "r", newline="") as source_csv:
                            source_reader = csv.reader(source_csv)
                            with open(new, "a", newline="") as dest_csv:
                                dest_writer = csv.writer(dest_csv)
                                for row in source_reader:
                                    dest_writer.writerow(row)
                        os.remove(f)
                    break
                else:
                    break

    def _motion_loop(self):
        niter: int = 1
        for i, val0 in enumerate(self.coords[0]):
            if self._stopnow:
                # aborted before initial move
                break

            # move outer loop to val 0
            pos0 = self.axes[0].move(val0)

            if (i % 2) != 0:
                # if outer loop index is odd, inner loop is reversed
                coord1_iter = reversed(self.coords[1])
            else:
                coord1_iter = self.coords[1]
            for val1 in coord1_iter:
                if len(self.axes) == 2:
                    # move inner loop to val 1
                    pos1 = self.axes[1].move(val1)
                else:
                    pos1 = None

                self.signals.sigStepStarted.emit(niter)

                # execute sequence and wait until it finishes
                ret = self.sequence_run_wait()
                if ret == 1:
                    # aborted during scan, return
                    return

                # mangle filename so that SES ignores it
                self._rename_file(niter)
                self.signals.sigStepFinished.emit(niter, pos0, pos1)

                if self._stop:
                    # aborted after scan
                    return

                niter += 1


class ScanType(*uic.loadUiType("scantype.ui")):
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

        self.pos_logger = MotorPosWriter()
        self.threadpool = QtCore.QThreadPool()
        self.threadpool.start(self.pos_logger)

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

    def update_motor_list(self):
        for i, m in enumerate(self.motors):
            m.combo.blockSignals(True)
            m.combo.clear()
            m.combo.addItems(self.valid_axes)
            m.combo.setCurrentIndex(i)
            m.combo.blockSignals(False)
        self.motors[-1].setChecked(False)

    def motor_changed(self, index):
        # apply motion limits
        self.update_motor_limits(index)

        # # make two comboboxes mutually exclusive
        # self.motors[1 - index].combo.blockSignals(True)
        # self.motors[1 - index].combo.clear()
        # if self.motors[index].isChecked():
        #     self.motors[1 - index].combo.addItems(
        #         [
        #             ax
        #             for ax in self.valid_axes
        #             if ax != self.motors[index].combo.currentText()
        #         ]
        #     )
        # else:
        #     self.motors[1 - index].combo.addItems(self.valid_axes)
        # self.motors[1 - index].combo.blockSignals(False)

        # apply motion limits to other combobox (selection may have changed)
        # self.update_motor_limits(1 - index)

    def update_motor_limits(self, index: int):
        """Get motor limits from corresponding plugin and update values."""
        try:
            plugin = Motor.plugins[self.motors[index].combo.currentText()]
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
        self.stop_point_btn.clicked.connect(scan_worker.stop_after_point)

        self.threadpool.start(scan_worker)

    @QtCore.Slot(int, object, object)
    def step_finished(self, niter: int, pos0, pos1):
        # display status
        self.line.setText(f"{niter}/{self.numpoints} Finished, v1={pos0}, v2={pos1}")

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

    @QtCore.Slot()
    def post_process(self):
        for m in self.motors:
            m.setDisabled(False)
        self.start_btn.setDisabled(False)
        self.damap_check.setDisabled(False)
        self.stop_btn.setDisabled(True)
        self.stop_point_btn.setDisabled(True)
        if self.itool is not None:
            self.itool.set_busy(False)

    @QtCore.Slot(int)
    def step_started(self, niter: int):
        self.line.setText(f"{niter}/{self.numpoints} Started")

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

    def closeEvent(self, *args, **kwargs):
        for win in self._itools:
            if win:
                win.close()
        self.pos_logger.stop()
        self.threadpool.waitForDone()
        super().closeEvent(*args, **kwargs)


class SESShortcuts(QtWidgets.QWidget):
    SES_ACTIONS: dict[str, tuple[str, str]] = {
        "Calibrate Voltages": ("Calibration", "Voltages..."),
        "File Options": ("Setup", "File Options..."),
        "Sequence Setup": ("Sequence", "Setup..."),
        "Control Theta": ("DA30", "Control Theta..."),
        "Center Deflection": ("DA30", "Center Deflection"),
        "Run Sequence": ("Sequence", "Run"),
    }

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(250)
        self.setWindowTitle("SES Shortcuts")
        self.setLayout(QtWidgets.QVBoxLayout(self))
        self.connect()
        self.create_buttons()

        self.scantype = ScanType()
        self.scantype.show()
        self.scantype.activateWindow()

    @property
    def ses(self) -> SESController:
        return self._ses

    @ses.setter
    def ses(self, value: SESController):
        self._ses = value

    @QtCore.Slot()
    def connect(self):
        while True:
            try:
                self.ses = SESController()
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    str(e),
                    f"Make sure SES.exe is running and the main window is visible.",
                )
            else:
                break

    @QtCore.Slot(object)
    def try_click(self, menu_path: tuple[str, str]):
        try:
            self.ses.click_menu(menu_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                str(e),
                f"SES control failed",
            )
            self.connect()

    def create_buttons(self):
        for label, path in self.SES_ACTIONS.items():
            btn = QtWidgets.QPushButton(label, self)
            btn.clicked.connect(lambda *, path=path: self.try_click(path))
            self.layout().addWidget(btn)


if __name__ == "__main__":
    qapp = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)
    # qapp.setStyle("Fusion")
    # widget = SESShortcuts()
    widget = ScanType()
    widget.show()
    widget.activateWindow()
    qapp.exec()
