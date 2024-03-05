import csv
import datetime
import logging
import multiprocessing
import os
import queue
import sys
import time
import tomllib
from collections.abc import Sequence
from multiprocessing import shared_memory

import numpy as np
import pyqtgraph as pg
import qtawesome as qta
from qtpy import QtCore, QtGui, QtWidgets, uic

from moee import EncoderThread, MMCommand, MMStatus, MMThread

try:
    os.chdir(sys._MEIPASS)
except:
    pass

CONFIG_FILE = "D:/MotionController/piezomotors.toml"

log = logging.getLogger("moee")


class LoggingProc(multiprocessing.Process):
    """Process for logging manipulator motion.

    Parameters
    ----------
    log_dir
        Directory where the log file will be stored. The filename will be automatically
        determined from the current date and time.

    """

    def __init__(self, log_dir: str | os.PathLike):
        super().__init__()
        self.log_dir = log_dir
        self._stopped = multiprocessing.Event()
        self.queue = multiprocessing.Manager().Queue()

    def run(self):
        self._stopped.clear()
        while not self._stopped.is_set():
            time.sleep(0.2)

            if self.queue.empty():
                continue

            # retrieve message from queue
            dt, msg = self.queue.get()
            try:
                with open(
                    os.path.join(self.log_dir, dt.strftime("%y%m%d") + ".csv"),
                    "a",
                    newline="",
                ) as f:
                    writer = csv.writer(f)
                    writer.writerow([dt.isoformat()] + msg)
            except PermissionError:
                # put back the retrieved message in the queue
                n_left = int(self.queue.qsize())
                self.queue.put((dt, msg))
                for _ in range(n_left):
                    self.queue.put(self.queue.get())
                continue

    def stop(self):
        n_left = int(self.queue.qsize())
        if n_left != 0:
            print(
                f"Failed to write {n_left} log "
                + ("entries:" if n_left > 1 else "entry:")
            )
            for _ in range(n_left):
                dt, msg = self.queue.get()
                print(f"{dt} | {msg}")
        self._stopped.set()
        self.join()

    def add_content(self, content: str | list[str]):
        now = datetime.datetime.now()
        if isinstance(content, str):
            content = [content]
        self.queue.put((now, content))


class StautsIconWidget(qta.IconWidget):
    def __init__(self, *icons: Sequence[str | dict | QtGui.QIcon], parent=None):
        super().__init__(parent=parent)
        self._icons: list[QtGui.QIcon] = []
        for icn in icons:
            if isinstance(icn, str):
                self._icons.append(qta.icon(icn))
            elif isinstance(icn, dict):
                self._icons.append(qta.icon(**icn))
            elif isinstance(icn, QtGui.QIcon):
                self._icons.append(icn)
            else:
                raise TypeError(f"Unrecognized icon type `{type(icn)}`")
        self._state: int = 0
        self.setState(self._state)

    def setText(self, *args, **kwargs):
        return

    def icons(self) -> Sequence[QtGui.QIcon]:
        return self._icons

    def state(self) -> int:
        return self._state

    def nstates(self) -> int:
        return len(self.icons())

    def setState(self, state: int):
        self._state = int(state)
        self.setIcon(self.icons()[self._state])

    def setIconSize(self, size: QtCore.QSize, update: bool = False):
        super().setIconSize(size)
        if update:
            self.update()

    def update(self, *args, **kwargs):
        self._icon = self.icons()[self._state]
        return super().update(*args, **kwargs)


class MotorStatus(StautsIconWidget):
    def __init__(self, parent=None):
        super().__init__(
            qta.icon("mdi6.circle-outline", color="#e50000"),
            qta.icon("mdi6.loading", color="#15b01a", animation=qta.Spin(self)),
            parent=parent,
        )
        self.setIconSize(QtCore.QSize(20, 20), update=True)

    def setState(self, value: bool):
        super().setState(1 if value else 0)


class SingleChannelWidget(*uic.loadUiType("channel.ui")):
    """Widget for a single channel. Internally, all positions are `raw` positions before
    applying calibration factors. This widget handles the necessary conversions."""

    sigMoveRequested = QtCore.Signal(int, int, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.sigEnabledChanged = self.checkbox.toggled
        self.sigEnabledChanged.connect(self.refresh_enabled)
        self.checkbox.setChecked(True)
        self.status = MotorStatus(self)
        self.layout().addWidget(self.status)
        self.left_btn.setIcon(qta.icon("mdi6.arrow-left"))
        self.right_btn.setIcon(qta.icon("mdi6.arrow-right"))
        self.step_spin.valueChanged.connect(self.target_spin.setSingleStep)
        self.step_spin.setValue(0.1)

        self.left_btn.clicked.connect(self.step_down)
        self.right_btn.clicked.connect(self.step_up)
        self.move_btn.clicked.connect(self.move)

        # internal variable to store raw position
        self.raw_position: int | float | None = None

        # read configuration & populate combobox
        with open(CONFIG_FILE, "rb") as f:
            self.config: dict = tomllib.load(f)

        self.combobox.clear()
        for k in self.config.keys():
            self.combobox.addItem(self.config[k].get("alias", k))
        self.combobox.currentTextChanged.connect(self.update_motor)
        self.update_motor()

    @property
    def enabled(self) -> bool:
        return self.checkbox.isChecked()

    @property
    def motor_serial(self) -> str:
        return tuple(self.config.keys())[self.combobox.currentIndex()]

    @property
    def current_config(self) -> dict:
        return self.config[self.motor_serial]

    @property
    def nominal_capacitance(self) -> float | None:
        return self.current_config.get("cap", None)

    @property
    def tolerance(self) -> int:
        tol = self.current_config.get("tol", None)
        if tol is None:
            return 4
        else:
            return round(abs(tol * 1e-3 / self.cal_A))

    @property
    def abs_tolerance(self) -> float:
        return abs(self.cal_A * self.tolerance)

    @property
    def current_pos(self) -> float:
        if self.enabled:
            return self.convert_pos(self.raw_position)
        else:
            return np.nan

    @property
    def minimum(self) -> float:
        return self.target_spin.minimum()

    @property
    def maximum(self) -> float:
        return self.target_spin.maximum()

    @property
    def name(self) -> str:
        return self.combobox.currentText()

    @QtCore.Slot(float)
    def set_target(self, value: float):
        self.target_spin.setValue(value)

    @QtCore.Slot()
    def target_current_pos(self):
        if self.enabled:
            self.set_target(self.current_pos)

    @QtCore.Slot()
    def refresh_enabled(self):
        """Refresh the enabled state of widgets."""
        self.set_channel_disabled(not self.enabled)

    def set_channel_disabled(self, value: bool):
        self.combobox.setDisabled(value)
        self.pos_lineedit.setDisabled(value)
        self.target_spin.setDisabled(value)
        self.left_btn.setDisabled(value)
        self.step_spin.setDisabled(value)
        self.right_btn.setDisabled(value)
        self.move_btn.setDisabled(value)

    def set_motion_busy(self, value: bool):
        """Disable some widgets during motion."""
        self.combobox.setDisabled(value)
        self.left_btn.setDisabled(value)
        self.right_btn.setDisabled(value)
        self.move_btn.setDisabled(value)
        self.target_spin.setDisabled(value)
        self.freq_spin.setDisabled(value)
        self.amp_bwd_spin.setDisabled(value)
        self.amp_fwd_spin.setDisabled(value)

    @QtCore.Slot()
    def update_motor(self):
        """Refresh calibration factors and set motion bounds."""
        self.cal_A = float(self.current_config.get("a", 1.0))
        self.cal_B = float(self.current_config.get("b", 0.0))
        self.cal_B -= float(self.current_config.get("origin", 0.0))

        bounds = (
            self.convert_pos(int(self.current_config.get("min", 0))),
            self.convert_pos(int(self.current_config.get("max", 65535))),
        )
        self.target_spin.setMinimum(min(bounds))
        self.target_spin.setMaximum(max(bounds))

        self.freq_spin.setValue(int(self.current_config.get("freq", 200)))
        self.amp_bwd_spin.setValue(int(self.current_config.get("voltage_0", 30)))
        self.amp_fwd_spin.setValue(int(self.current_config.get("voltage_1", 30)))

        if self.raw_position is not None:
            self.set_current_pos(self.raw_position)

    def convert_pos(self, pos: int | float) -> float:
        """Convert raw position integer to calibrated position."""
        return self.cal_A * pos + self.cal_B

    def convert_pos_inv(self, value: float) -> int:
        """Convert position value into nearest raw position integer."""
        return round((value - self.cal_B) / self.cal_A)

    @QtCore.Slot(float)
    @QtCore.Slot(int)
    def set_current_pos(self, pos: int | float):
        self.raw_position = pos
        self.pos_lineedit.setText(f"{self.convert_pos(self.raw_position):.4f}")

    @QtCore.Slot()
    def step_up(self):
        self.target_spin.stepBy(1)

    @QtCore.Slot()
    def step_down(self):
        self.target_spin.stepBy(-1)

    @QtCore.Slot()
    def move(self):
        self.move_to(self.target_spin.value())

    @QtCore.Slot(float)
    @QtCore.Slot(float, object)
    def move_to(self, value: float, unique_id: str | None = None):
        self.sigMoveRequested.emit(
            self.convert_pos_inv(value),
            self.freq_spin.value(),
            (self.amp_bwd_spin.value(), self.amp_fwd_spin.value()),
            unique_id,
        )


class DeltaWidget(QtWidgets.QWidget):
    """Widget for movement along beam direction."""

    sigStepped = QtCore.Signal(float)
    sigMoved = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setLayout(QtWidgets.QHBoxLayout(self))

        self.left_btn = QtWidgets.QPushButton()
        self.left_btn.setIcon(qta.icon("mdi6.arrow-left"))
        self.right_btn = QtWidgets.QPushButton()
        self.right_btn.setIcon(qta.icon("mdi6.arrow-right"))
        self.move_btn = QtWidgets.QPushButton("Move")

        self.step_spin = QtWidgets.QDoubleSpinBox()
        self.step_spin.setMinimum(0)
        self.step_spin.setMaximum(0.5)
        self.step_spin.setValue(0.1)
        self.step_spin.setDecimals(2)
        self.step_spin.setSingleStep(0.01)

        self.layout().addStretch()
        self.layout().addWidget(self.left_btn)
        self.layout().addWidget(self.step_spin)
        self.layout().addWidget(self.right_btn)
        self.layout().addWidget(self.move_btn)

        self.left_btn.clicked.connect(self.step_down)
        self.right_btn.clicked.connect(self.step_up)
        self.move_btn.clicked.connect(self.move)

    @QtCore.Slot()
    def step_up(self):
        self.sigStepped.emit(self.step_spin.value())

    @QtCore.Slot()
    def step_down(self):
        self.sigStepped.emit(-self.step_spin.value())

    @QtCore.Slot()
    def move(self):
        self.sigMoved.emit()


class MotionPlot(pg.PlotWidget):
    sigClosed = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Relative position")
        self.curve: pg.PlotDataItem = self.plot(pen="w")
        self.resize(300, 175)
        # self.setWindowFlags(self.windowFlags() | QtCore.Qt.CustomizeWindowHint)
        # self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)

    def closeEvent(self, *args, **kwargs):
        self.sigClosed.emit()
        super().closeEvent(*args, **kwargs)


class SingleControllerWidget(QtWidgets.QWidget):
    """
    Widget for a single controller that consists of three channels. Handles
    connection and communication with the controller, as well as plotting and queuing.

    On move, the motion parameters are placed in a queue. Each motion in the queue will
    be executed in the order it was placed. Checking for motion execution happens twice:
    when a new motion is added to the queue, and when a previous motion is finished.

    If there is a queued motion a thread `MMThread` is started. Once the motion is
    aborted or finished, the next motion in the queue is executed. If the queue is
    empty, the thread `EncoderThread` is started to read the position of the channels.

    Parameters
    ----------
    address
        IP address of the controller
    index
        Index of the controller. This is used to distinguish between diffent instances
        of the controller when emitting signals and writing logs.
    logwriter
        Logging process, by default None

    Signals
    -------
    sigPositionUpdated(int, float)
        Emitted when the position of a channel is updated. The first argument is the
        global index of the channel (0, 1, 2 for ch1, ch2, ch3 on controller 0 and 1, 2,
        3 for ch1, ch2, ch3 on controller 1 and so on), and the second is the updated
        position (calibration factors applied).

    """

    sigPositionUpdated = QtCore.Signal(int, float)

    def __init__(
        self,
        parent=None,
        *,
        address: str,
        index: int,
        logwriter: LoggingProc | None = None,
    ):
        self.address: str = address
        self.index: int = index
        self.logwriter: LoggingProc | None = logwriter

        super().__init__(parent)
        self.setLayout(QtWidgets.QVBoxLayout(self))

        # Add channels
        self.ch1 = SingleChannelWidget(self)
        self.ch2 = SingleChannelWidget(self)
        self.ch3 = SingleChannelWidget(self)
        for i, ch in enumerate(self.channels):
            self.layout().addWidget(ch)
            ch.checkbox.setText(f"Ch{i+1}")
            ch.sigEnabledChanged.connect(lambda *, idx=i: self.refresh_shm(idx))
        self.ch1.sigMoveRequested.connect(self.move_ch1)
        self.ch2.sigMoveRequested.connect(self.move_ch2)
        self.ch3.sigMoveRequested.connect(self.move_ch3)

        # Initialize unique IDs for tracking motion progress remotely
        self.started_uid: list[str] = []
        self.finished_uid: list[str] = []

        # Initialize thread object and connect appropriate signals
        self.mmthread = MMThread()
        self.mmthread.sigMoveStarted.connect(self.move_started)
        self.mmthread.sigMoveFinished.connect(self.move_finished)
        self.mmthread.sigPosRead.connect(self.set_position)
        self.mmthread.sigAvgPosRead.connect(self.set_position)
        self.mmthread.sigDeltaChanged.connect(self.update_plot)

        # Initialize motion queue
        self.queue = queue.Queue()

        # Setup plotting
        self.plot = MotionPlot()
        self.plot.setLabel("bottom", text="Time", units="s")
        self.plot.setLabel("left", text="Remaining", units="m")

        # Setup shared memory of enabled channels
        self.sl = shared_memory.ShareableList([ch.enabled for ch in self.channels])

        # Initialize position encoding thread.
        # This thread will read position when MMThread is not active.
        self.encoder = EncoderThread(mmthread=self.mmthread, sharedmem=self.sl.shm.name)

    @property
    def status(self) -> MMStatus:
        if self.mmthread.isRunning():
            return MMStatus.Moving
        elif self.mmthread.stopped:
            return MMStatus.Aborted
        else:
            return MMStatus.Done

    @property
    def channels(
        self,
    ) -> tuple[SingleChannelWidget, SingleChannelWidget, SingleChannelWidget]:
        return (self.ch1, self.ch2, self.ch3)

    @property
    def valid_channels(self) -> tuple[SingleChannelWidget, ...]:
        return tuple(ch for ch in self.channels if ch.enabled)

    @property
    def valid_channel_numbers(self) -> tuple[int, ...]:
        return tuple(i for i in range(1, 3 + 1) if self.is_channel_enabled(i))

    @property
    def current_positions(self) -> tuple[float, float, float]:
        return tuple(ch.current_pos for ch in self.channels)

    @QtCore.Slot()
    def connect(self):
        """Connect to motor controller. Displays a message box on failure."""
        try:
            self.connect_raise()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                str(e),
                f"Connection to {self.address} failed. Make sure the controller is "
                "on and connected. If the problem persists, try restarting the "
                "server process on the controller.",
            )

    @QtCore.Slot()
    def connect_raise(self):
        """Connect to motor controller. Raises an exception on failure."""
        try:
            self.mmthread.connect(self.address)
        except Exception as e:
            self.mmthread.sock.close()
            self.disable()
            raise e
        else:
            self.enable()
            # Start with all channels disabled
            for ch in self.channels:
                ch.checkbox.setChecked(False)
            self.start_encoding()

    @QtCore.Slot()
    def connect_silent(self):
        try:
            self.connect_raise()
        except:
            pass

    @QtCore.Slot()
    def disconnect(self):
        if self.isEnabled():
            self.stop()
            # Encoding must be stopped after mmthread is stopped
            self.stop_encoding()
            self.mmthread.disconnect()

    @QtCore.Slot()
    def reconnect(self):
        try:
            self.disconnect()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                str(e),
                f"Disconnecting {self.address} failed. If the problem persists, try "
                "restarting the server process on the controller.",
            )
        self.connect()

    def get_channel(self, channel: int) -> SingleChannelWidget:
        return self.channels[channel - 1]

    def is_channel_enabled(self, channel: int) -> bool:
        return self.get_channel(channel).enabled

    def disable(self):
        for ch in self.channels:
            ch.checkbox.setChecked(False)
        self.setDisabled(True)

    def enable(self):
        self.setEnabled(True)

    def write_log(self, entry: str | list[str]):
        if self.logwriter is not None:
            self.logwriter.add_content(entry)

    def refresh_shm(self, idx: int) -> None:
        self.sl[idx] = self.channels[idx].enabled

    @QtCore.Slot(object)
    def get_capacitance(self) -> list[str]:
        self.stop_encoding()
        valid_ch = self.valid_channels
        res = []
        for ch, n in zip(valid_ch, self.valid_channel_numbers):
            cap = self.mmthread.get_capacitance(n)
            res.append(f"{n}: Nominal {ch.nominal_capacitance}, Measured {cap:.4f} μF")
        # Reconnect due to controller bug
        # Position reading does not work after capacitance check
        self.reconnect()

        # Reconnect disables all channels for safety, re-enable valid channels
        for ch in valid_ch:
            ch.checkbox.setChecked(True)
        return res

    # @QtCore.Slot()
    # @QtCore.Slot(int)
    # def refresh_positions(self, navg: int = 1):
    #     for ch_num in (1, 2, 3):
    #         self.refresh_position(ch_num, navg=navg)

    # @QtCore.Slot()
    # def refresh_positions_averaged(self):
    #     self.refresh_positions(navg=10)

    # @QtCore.Slot(int)
    # @QtCore.Slot(int, int)
    # def refresh_position(self, channel: int, navg: int = 1):
    #     if self.is_channel_enabled(channel):
    #         if self.status != MMStatus.Moving:
    #             self.mmthread.reset(channel)
    #             self.mmthread.get_refreshed_position(channel, navg)

    @QtCore.Slot()
    def target_current_all(self):
        for ch in self.valid_channels:
            ch.target_current_pos()

    @QtCore.Slot(int, float)
    @QtCore.Slot(int, int)
    def set_position(self, channel: int, pos: int | float):
        ch: SingleChannelWidget = self.get_channel(channel)
        ch.set_current_pos(pos)
        ch_idx = int((channel - 1) + 3 * self.index)
        self.sigPositionUpdated.emit(ch_idx, ch.current_pos)

    @QtCore.Slot(int, object, object)
    def update_plot(self, channel: int, dt: list[float], delta: list[int]):
        delta_abs = -self.get_channel(channel).cal_A * np.asarray(delta)
        self.plot.curve.setData(x=dt, y=delta_abs * 1e-3)

    @QtCore.Slot()
    def start_encoding(self):
        # Start encoder thread.
        if self.isEnabled() and not self.encoder.isRunning():
            self.encoder.start()

    @QtCore.Slot()
    def stop_encoding(self):
        # Stop encoder thread.
        if self.isEnabled() and self.encoder.isRunning():
            self.encoder.stopped.set()
            self.encoder.wait()

    @QtCore.Slot(int, str)
    def move_started(self, channel: int, unique_id: str):
        if unique_id != "":
            self.started_uid.append(unique_id)

        # Disable input on channels
        for ch in self.channels:
            ch.set_motion_busy(True)

        # Display loading icon on running channel
        self.get_channel(channel).status.setState(True)

    @QtCore.Slot(int, str)
    def move_finished(self, channel: int, unique_id: str):
        if unique_id != "":
            self.started_uid.remove(unique_id)
            self.finished_uid.append(unique_id)

        # Mark motion as finished in queue
        self.queue.task_done()

        # Write log
        ch: SingleChannelWidget = self.get_channel(channel)
        self.write_log(
            [
                "End Move",
                str(int(channel + 3 * self.index)),
                ch.name,
                f"{ch.current_pos:.5f}",
            ]
        )

        # Return channels to normal state
        for ch in self.channels:
            ch.set_motion_busy(False)
        self.get_channel(channel).status.setState(False)

        # If queue has remaining items, move.
        # Otherwise, start position encoding thread.
        if not self.queue.empty():
            self._move()
        else:
            self.start_encoding()

    def is_started(self, unique_id: str) -> bool:
        if self.is_finished(unique_id):
            return True
        else:
            return unique_id in self.started_uid

    def is_finished(self, unique_id: str) -> bool:
        return unique_id in self.finished_uid

    def forget_uid(self, unique_id: str) -> None:
        if unique_id in self.finished_uid:
            self.finished_uid.remove(unique_id)

    @QtCore.Slot()
    def refresh_plot_visibility(self):
        if self.actionplotpos.isChecked():
            if not self.plot.isVisible():
                self.plot.show()
        else:
            if self.plot.isVisible():
                self.plot.hide()

    @QtCore.Slot(int, int, object)
    @QtCore.Slot(int, int, object, object)
    def move_ch1(
        self,
        target: int,
        frequency: int,
        amplitude: tuple[int, int],
        unique_id: str | None = None,
    ):
        return self.move(1, target, frequency, amplitude, unique_id)

    @QtCore.Slot(int, int, object)
    @QtCore.Slot(int, int, object, object)
    def move_ch2(
        self,
        target: int,
        frequency: int,
        amplitude: tuple[int, int],
        unique_id: str | None = None,
    ):
        return self.move(2, target, frequency, amplitude, unique_id)

    @QtCore.Slot(int, int, object)
    @QtCore.Slot(int, int, object, object)
    def move_ch3(
        self,
        target: int,
        frequency: int,
        amplitude: tuple[int, int],
        unique_id: str | None = None,
    ):
        return self.move(3, target, frequency, amplitude, unique_id)

    @QtCore.Slot(int, int, int, object)
    @QtCore.Slot(int, int, int, object, object)
    def move(
        self,
        channel: int,
        target: int,
        frequency: int,
        amplitude: tuple[int, int],
        unique_id: str | None = None,
    ) -> str:
        # Place motion parameters in queue
        if unique_id is None:
            unique_id: str = ""
        self.queue.put(
            dict(
                channel=channel,
                target=target,
                frequency=frequency,
                amplitude=amplitude,
                unique_id=unique_id,
            )
        )
        # If not busy, go on
        if self.status != MMStatus.Moving:
            self._move()
        return unique_id

    @QtCore.Slot()
    def _move(self):
        # Get motion parameters from first item in queue
        kwargs: dict = self.queue.get()
        ch_num: int = kwargs["channel"]
        ch: SingleChannelWidget = self.get_channel(ch_num)

        # Various sanity checks
        if not self.is_channel_enabled(ch_num):
            # This may happen when the channel is disabled after the motion was queued.
            log.warning(f"Move called on a disabled channel {ch_num} ignored.")
            self.queue.task_done()
            return
        if self.mmthread.isRunning():
            # This normally should not happen, but exists as a safety check.
            log.error(f"Move called while motion is ongoing. Ignored.")
            self.queue.task_done()
            return

        # Write motion start log
        self.write_log(
            [
                "Start Move",
                str(int(ch_num + 3 * self.index)),
                ch.name,
                f"{ch.convert_pos(kwargs['target']):.5f}",
            ]
        )

        # Stop encoder before motion start
        self.stop_encoding()

        # Set motion parameters
        kwargs["threshold"] = ch.tolerance
        if ch.abs_tolerance < 1e-3:
            kwargs["high_precision"] = True
        else:
            kwargs["high_precision"] = False

        self.mmthread.initialize_parameters(**kwargs)

        # Start motion
        self.mmthread.start()

    @QtCore.Slot()
    def empty_queue(self):
        """Clear all queued motion."""
        while not self.queue.empty():
            try:
                self.queue.get(block=False)
            except queue.Empty:
                continue
            else:
                self.queue.task_done()

    @QtCore.Slot()
    def stop(self):
        """Empty all items in queue and stop current motion."""
        self.empty_queue()
        self.stop_current()

    @QtCore.Slot()
    def stop_current(self):
        """Stops current motion. Will move on to the next queued motion."""
        self.mmthread.stopped = True
        self.mmthread.wait(2000)

    def closeEvent(self, event: QtGui.QCloseEvent):
        self.stop_encoding()
        self.plot.close()
        self.sl.shm.close()
        self.sl.shm.unlink()
        super().closeEvent(event)


if __name__ == "__main__":
    # MWE for debugging

    class MyWidget(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.channel = SingleChannelWidget()
            self.layout = QtWidgets.QVBoxLayout(self)
            self.layout.addWidget(self.channel)

    qapp = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    widget = MyWidget()
    widget.show()
    widget.activateWindow()
    qapp.exec()
