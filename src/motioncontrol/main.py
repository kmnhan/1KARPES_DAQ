"""GUI for the 1K ARPES 6-axis manipulator"""
import csv
import datetime
import os
import sys

import numpy as np
import pyqtgraph as pg
from moee import MMCommand, MMThread
from motionwidgets import SingleChannelWidget
from qtpy import QtCore, QtGui, QtWidgets, uic

try:
    os.chdir(sys._MEIPASS)
except:
    pass

LOG_DIR = "D:/MotionController/logs"
# LOG_DIR = os.path.expanduser("~/MotionController/logs")


def write_log(content):
    now = datetime.datetime.now()
    with open(
        os.path.join(LOG_DIR, now.strftime("%y%m%d") + ".csv"), "a", newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow([now.isoformat(), content])


class MotionPlot(pg.PlotWidget):
    sigClosed = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Relative position")
        self.curve: pg.PlotDataItem = self.plot(pen="w")
        # self.setWindowFlags(self.windowFlags() | QtCore.Qt.CustomizeWindowHint)
        # self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)

    def closeEvent(self, *args, **kwargs):
        self.sigClosed.emit()
        super().closeEvent(*args, **kwargs)


class MainWindow(*uic.loadUiType("controller.ui")):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("1KARPES Motion Control")

        self.stop_btn.setDefaultAction(self.actionstop)
        self.actionstop.triggered.connect(self.stop)

        self.actionreconnect.triggered.connect(self.reconnect)

        self.readpos_btn.setDefaultAction(self.actionreadpos)
        self.actionreadpos.triggered.connect(self.refresh_positions)

        self.actionreadcap.triggered.connect(self.check_capacitance)

        self.actiontargetcurr.triggered.connect(self.target_current_all)

        self.ch1.sigMoveRequested.connect(self.move_ch1)
        self.ch2.sigMoveRequested.connect(self.move_ch2)
        self.ch3.sigMoveRequested.connect(self.move_ch3)
        for i in range(3):
            self.channels[i].set_name(f"Ch{i+1}")

        self.mmthread = MMThread()
        self.mmthread.sigMoveStarted.connect(self.move_started)
        self.mmthread.sigMoveFinished.connect(self.move_finished)
        self.mmthread.sigPosRead.connect(self.set_position)
        self.mmthread.sigDeltaChanged.connect(self.update_plot)

        # setup plotting
        self.plot = MotionPlot()
        self.curve: pg.PlotDataItem = self.plot.plot(pen="w")
        self.actionplotpos.triggered.connect(self.refresh_plot_visibility)
        self.plot.sigClosed.connect(lambda: self.actionplotpos.setChecked(False))
        # self.actionplotpos.

        # connect to controller
        self.connect()

    @property
    def channels(
        self,
    ) -> tuple[SingleChannelWidget, SingleChannelWidget, SingleChannelWidget]:
        return (self.ch1, self.ch2, self.ch3)

    @property
    def valid_channels(self):
        return tuple(ch for ch in self.channels if ch.enabled)

    @QtCore.Slot()
    def check_capacitance(self):
        if len(self.valid_channels) == 0:
            QtWidgets.QMessageBox.warning(
                self,
                "No enabled channels",
                "Enable at least one channel to measure the capacitance.",
            )
            return
        enabled_channels: list[int] = [
            i for i in range(1, 3 + 1) if self.is_channel_enabled(i)
        ]
        ret = QtWidgets.QMessageBox.question(
            self,
            "Capacitance check",
            "Check capacitance for all enabled channel(s) "
            f"{', '.join([str(i) for i in enabled_channels])}?",
        )
        if ret == QtWidgets.QMessageBox.Yes:
            res = []
            for ch, n in zip(self.valid_channels, enabled_channels):
                cap = self.mmthread.get_capacitance(n)
                res.append(
                    f"Ch{n}: Nominal {ch.nominal_capacitance}, Measured {cap:.4f} μF"
                )
            # reconnect due to controller bug
            # position reading does not work after capacitance check
            self.reconnect()
            QtWidgets.QMessageBox.information(
                self, "Capacitance measured", "\n".join(res)
            )

    def is_channel_enabled(self, channel: int) -> bool:
        return self.channels[channel - 1].enabled

    @QtCore.Slot()
    def refresh_positions(self):
        for ch_num in (1, 2, 3):
            if self.is_channel_enabled(ch_num):
                self.mmthread.get_position(ch_num)

    @QtCore.Slot()
    def target_current_all(self):
        for ch in self.valid_channels:
            ch.target_current_pos()

    @QtCore.Slot(int, int)
    def set_position(self, channel: int, pos: int):
        self.channels[channel - 1].set_current_pos(pos)

    @QtCore.Slot(int, object)
    def update_plot(self, channel: int, delta: list[float]):
        delta_abs = self.channels[channel - 1].cal_A * np.asarray(delta)
        self.curve.setData(delta_abs)

    @QtCore.Slot(int)
    def move_started(self, channel: int):
        for ch in self.channels:
            ch.set_motion_busy(True)
        self.channels[channel - 1].status.setState(True)
        self.actionreadpos.setDisabled(True)
        self.actionreadcap.setDisabled(True)

    @QtCore.Slot(int)
    def move_finished(self, channel: int):
        for ch in self.channels:
            ch.set_motion_busy(False)
        self.channels[channel - 1].status.setState(False)
        self.actionreadpos.setDisabled(False)
        self.actionreadcap.setDisabled(False)

    @QtCore.Slot()
    def refresh_plot_visibility(self):
        if self.actionplotpos.isChecked():
            if not self.plot.isVisible():
                self.plot.show()
        else:
            if self.plot.isVisible():
                self.plot.hide()

    @QtCore.Slot(int, int, int)
    def move_ch1(self, target: int, frequency: int, amplitude: int):
        return self.move(1, target, frequency, amplitude)

    @QtCore.Slot(int, int, int)
    def move_ch2(self, target: int, frequency: int, amplitude: int):
        return self.move(2, target, frequency, amplitude)

    @QtCore.Slot(int, int, int)
    def move_ch3(self, target: int, frequency: int, amplitude: int):
        return self.move(3, target, frequency, amplitude)

    @QtCore.Slot(int, int, int, int)
    def move(self, channel: int, target: int, frequency: int, amplitude: int):
        write_log(
            f"Move Ch{channel} to {self.channels[channel - 1].convert_pos(target):.4f}"
        )
        if not self.is_channel_enabled(channel):
            # warnings.warn("Move called on a disabled channel ignored.")
            print("Move called on a disabled channel ignored.")
            return
        if self.mmthread.isRunning():
            # warnings.warn("Motion already in progress.")
            print("Motion already in progress.")
            return
        self.mmthread.initialize_parameters(
            channel=channel,
            target=target,
            frequency=frequency,
            amplitude=amplitude,
            threshold=self.threshold_spin.value(),
        )
        self.mmthread.start()

    @QtCore.Slot()
    def connect(self):
        while True:
            try:
                self.mmthread.connect()
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    str(e),
                    f"Connection failed. Make sure the controller is on and connected."
                    " If the problem persists, try restarting the server process on "
                    "the controller.",
                )
                self.mmthread.sock.close()
            else:
                break

    @QtCore.Slot()
    def stop(self):
        self.mmthread.moving = False
        self.mmthread.wait(2000)
        write_log("All motions stopped")

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
                f"Disconnect failed. If the problem persists, try "
                "restarting the server process on the controller.",
            )
        else:
            self.connect()

    def closeEvent(self, *args, **kwargs):
        self.disconnect()
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)
    qapp.setWindowIcon(QtGui.QIcon("./icon.ico"))
    # qapp.setStyle("Fusion")

    win = MainWindow()
    win.show()
    win.activateWindow()
    qapp.exec()
