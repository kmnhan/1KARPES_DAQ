import queue
import sys
import threading
import time
import tomllib
from collections.abc import Sequence

import numpy as np
import pyqtgraph as pg
import qtawesome as qta
from moee import MMCommand, MMStatus, MMThread
from qtpy import QtCore, QtGui, QtWidgets, uic

CONFIG_FILE = "D:/MotionController/piezomotors.toml"


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
    sigMoveRequested = QtCore.Signal(int, int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.checkbox.toggled.connect(
            lambda: self.set_channel_disabled(not self.enabled)
        )
        self.status = MotorStatus(self)
        self.layout().addWidget(self.status)
        self.left_btn.setIcon(qta.icon("mdi6.arrow-left"))
        self.right_btn.setIcon(qta.icon("mdi6.arrow-right"))
        self.step_spin.valueChanged.connect(self.target_spin.setSingleStep)
        self.step_spin.setValue(0.1)

        self.left_btn.clicked.connect(self.step_down)
        self.right_btn.clicked.connect(self.step_up)
        self.move_btn.clicked.connect(self.move)

        # internal variables
        self.raw_position: int | None = None

        # read configuration & populate combobox
        with open(CONFIG_FILE, "rb") as f:
            self.config = tomllib.load(f)

        self.combobox.clear()
        for k in self.config.keys():
            self.combobox.addItem(self.config[k].get("alias", k))
        self.combobox.currentTextChanged.connect(self.update_motor)
        self.update_motor()

    @property
    def enabled(self) -> bool:
        return self.checkbox.isChecked()

    @property
    def current_config(self) -> dict:
        return self.config[tuple(self.config.keys())[self.combobox.currentIndex()]]

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
    def current_pos(self) -> float:
        if self.enabled:
            return self.convert_pos(self.raw_position)
        else:
            return np.nan

    @property
    def name(self) -> str:
        return self.combobox.currentText()

    @QtCore.Slot()
    def target_current_pos(self):
        self.target_spin.setValue(self.convert_pos(self.raw_position))

    def set_channel_disabled(self, value: bool):
        self.combobox.setDisabled(value)
        self.pos_lineedit.setDisabled(value)
        self.target_spin.setDisabled(value)
        self.left_btn.setDisabled(value)
        self.step_spin.setDisabled(value)
        self.right_btn.setDisabled(value)
        self.move_btn.setDisabled(value)

    def set_motion_busy(self, value: bool):
        self.combobox.setDisabled(value)
        self.left_btn.setDisabled(value)
        self.right_btn.setDisabled(value)
        self.move_btn.setDisabled(value)
        self.target_spin.setDisabled(value)
        self.freq_spin.setDisabled(value)
        self.amp_bwd_spin.setDisabled(value)
        self.amp_fwd_spin.setDisabled(value)

    def update_motor(self):
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

    def convert_pos(self, pos: int) -> float:
        return self.cal_A * pos + self.cal_B

    def convert_pos_inv(self, value: float) -> int:
        return round((value - self.cal_B) / self.cal_A)

    @QtCore.Slot(int)
    def set_current_pos(self, pos: int):
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
        self.sigMoveRequested.emit(
            self.convert_pos_inv(self.target_spin.value()),
            self.freq_spin.value(),
            (self.amp_bwd_spin.value(), self.amp_fwd_spin.value()),
        )


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


# class MotionWorker(QtCore.QThread):
#     """Thread that handles queueing of motion commands."""

#     # sigMotion

#     def __init__(self, queue):
#         super().__init__()
#         self._stopped: bool = False
#         self.queue = queue

#     def run(self):
#         self._stopped = False
#         while not self._stopped:
#             time.sleep(0.1)
#             if self.queue.qsize() > 0:
#                 pass

#     def stop(self):

#         n_left = len(self.messages)
#         if n_left != 0:
#             print(
#                 f"Failed to write {n_left} log "
#                 + ("entries:" if n_left > 1 else "entry:")
#             )
#             for dt, msg in self.messages:
#                 print(f"{dt} | {msg}")
#         self._stopped = True
#         self.join()


class SingleControllerWidget(QtWidgets.QWidget):
    writeLog = QtCore.Signal(object)

    def __init__(self, parent=None, address: str = "192.168.0.210"):
        self.address = address

        super().__init__(parent)
        self.setLayout(QtWidgets.QVBoxLayout(self))

        self.ch1 = SingleChannelWidget(self)
        self.ch2 = SingleChannelWidget(self)
        self.ch3 = SingleChannelWidget(self)
        for i, ch in enumerate(self.channels):
            self.layout().addWidget(ch)
            ch.checkbox.setText(f"Ch{i+1}")

        self.ch1.sigMoveRequested.connect(self.move_ch1)
        self.ch2.sigMoveRequested.connect(self.move_ch2)
        self.ch3.sigMoveRequested.connect(self.move_ch3)

        self.mmthread = MMThread()
        self.mmthread.sigMoveStarted.connect(self.move_started)
        self.mmthread.sigMoveFinished.connect(self.move_finished)
        self.mmthread.sigPosRead.connect(self.set_position)
        self.mmthread.sigDeltaChanged.connect(self.update_plot)

        self.queue = queue.Queue()

        # setup plotting
        self.plot = MotionPlot()

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
    def valid_channel_numbers(self) -> list[int]:
        return [i for i in range(1, 3 + 1) if self.is_channel_enabled(i)]

    def get_channel(self, channel) -> SingleChannelWidget:
        return self.channels[channel - 1]

    def is_channel_enabled(self, channel: int) -> bool:
        return self.get_channel(channel).enabled

    def disable(self):
        for ch in self.channels:
            ch.checkbox.setChecked(False)
        self.setDisabled(True)

    def write_log(self, entry: str | list[str]):
        self.writeLog.emit(entry)

    @QtCore.Slot(object)
    def get_capacitance(self) -> list[str]:
        res = []
        for ch, n in zip(self.valid_channels, self.valid_channel_numbers):
            cap = self.mmthread.get_capacitance(n)
            res.append(f"{n}: Nominal {ch.nominal_capacitance}, Measured {cap:.4f} μF")
        # reconnect due to controller bug
        # position reading does not work after capacitance check
        self.reconnect()
        return res

    @QtCore.Slot()
    def refresh_positions(self):
        for ch_num in (1, 2, 3):
            self.refresh_position(ch_num)

    @QtCore.Slot()
    def refresh_position(self, channel: int):
        if self.is_channel_enabled(channel):
            self.mmthread.reset(channel)
            self.mmthread.get_position(channel)

    @QtCore.Slot()
    def target_current_all(self):
        for ch in self.valid_channels:
            ch.target_current_pos()

    @QtCore.Slot(int, int)
    def set_position(self, channel: int, pos: int):
        self.get_channel(channel).set_current_pos(pos)

    @QtCore.Slot(int, object)
    def update_plot(self, channel: int, delta: list[float]):
        delta_abs = -self.get_channel(channel).cal_A * np.asarray(delta)
        # delta_abs = -np.asarray(delta)
        self.plot.curve.setData(delta_abs)

    @QtCore.Slot(int)
    def move_started(self, channel: int):
        for ch in self.channels:
            ch.set_motion_busy(True)
        self.get_channel(channel).status.setState(True)

    @QtCore.Slot(int)
    def move_finished(self, channel: int):
        self.queue.task_done()

        for ch in self.channels:
            ch.set_motion_busy(False)
        self.get_channel(channel).status.setState(False)

        if not self.queue.empty():
            self._move(**self.queue.get())

    @QtCore.Slot()
    def refresh_plot_visibility(self):
        if self.actionplotpos.isChecked():
            if not self.plot.isVisible():
                self.plot.show()
        else:
            if self.plot.isVisible():
                self.plot.hide()

    @QtCore.Slot(int, int, object)
    def move_ch1(self, target: int, frequency: int, amplitude: tuple[int, int]):
        return self.move(1, target, frequency, amplitude)

    @QtCore.Slot(int, int, object)
    def move_ch2(self, target: int, frequency: int, amplitude: tuple[int, int]):
        return self.move(2, target, frequency, amplitude)

    @QtCore.Slot(int, int, object)
    def move_ch3(self, target: int, frequency: int, amplitude: tuple[int, int]):
        return self.move(3, target, frequency, amplitude)

    @QtCore.Slot(int, int, int, object)
    def move(
        self, channel: int, target: int, frequency: int, amplitude: tuple[int, int]
    ):
        if not self.mmthread.isRunning():
            self._move(channel, target, frequency, amplitude)
        else:
            self.queue.put(
                dict(
                    channel=channel,
                    target=target,
                    frequency=frequency,
                    amplitude=amplitude,
                )
            )

    @QtCore.Slot(int, int, int, object)
    def _move(
        self, channel: int, target: int, frequency: int, amplitude: tuple[int, int]
    ):
        ch = self.get_channel(channel)
        self.write_log(f"Move {ch.name} to {ch.convert_pos(target):.4f}")
        if not self.is_channel_enabled(channel):
            # warnings.warn("Move called on a disabled channel ignored.")
            print("Move called on a disabled channel ignored.")
            self.queue.task_done()
            return
        if self.mmthread.isRunning():
            # warnings.warn("Motion already in progress.")
            print("Motion already in progress.")
            self.queue.task_done()
            return
        self.mmthread.initialize_parameters(
            channel=channel,
            target=target,
            frequency=frequency,
            amplitude=amplitude,
            threshold=self.get_channel(channel).tolerance,
        )
        self.mmthread.start()

    @QtCore.Slot()
    def connect(self):
        while True:
            try:
                self.mmthread.connect(self.address)
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    str(e),
                    f"Connection to {self.address} failed. Make sure the controller is "
                    "on and connected. If the problem persists, try restarting the "
                    "server process on the controller.",
                )
                self.mmthread.sock.close()
            else:
                break

    @QtCore.Slot()
    def connect_raise(self):
        while True:
            try:
                self.mmthread.connect(self.address)
            except Exception as e:
                self.mmthread.sock.close()
                raise e
            else:
                break

    @QtCore.Slot()
    def stop(self):
        while not self.queue.empty():
            try:
                self.queue.get(block=False)
            except queue.Empty:
                continue
            else:
                self.queue.task_done()
        self.mmthread.stopped = True
        self.mmthread.wait(2000)

    @QtCore.Slot()
    def disconnect(self):
        self.stop()
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
        else:
            self.connect()


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
