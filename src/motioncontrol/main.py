"""GUI for the 1K ARPES 6-axis manipulator"""

import csv
import datetime
import multiprocessing
import os
import sys
import time

try:
    os.chdir(sys._MEIPASS)
except:
    pass

import numpy as np
from maniserver import ManiServer
from moee import MMStatus
from motionwidgets import DeltaWidget, SingleChannelWidget, SingleControllerWidget
from qtpy import QtCore, QtGui, QtWidgets, uic

LOG_DIR = "D:/MotionController/logs"
# LOG_DIR = os.path.expanduser("~/MotionController/logs")


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
        self.queue = multiprocessing.Queue()

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


class MainWindow(*uic.loadUiType("controller.ui")):
    """Combines two controlller widgets to form a complete GUI. On connection failure,
    the controller will be greyed out instead of displaying a message.

    On initialization, starts a server so that motion can be controlled by other
    programs.

    """

    sigReply = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("Motion Control")

        self.stop_btn.setDefaultAction(self.actionstop)
        self.stopcurrent_btn.setDefaultAction(self.actionstopcurrent)
        self.readpos_btn.setDefaultAction(self.actionreadpos)
        self.readavgpos_btn.setDefaultAction(self.actionreadavgpos)

        self.actionplotpos.triggered.connect(self.refresh_plot_visibility)
        self.actionreadcap.triggered.connect(self.check_capacitance)

        # initialize controllers
        self.controllers: tuple[SingleControllerWidget, SingleControllerWidget] = (
            SingleControllerWidget(self, address="192.168.0.210"),
            SingleControllerWidget(self, address="192.168.0.211"),
        )
        for con in self.controllers:
            self.verticalLayout.addWidget(con)
            con.writeLog.connect(self.write_log)

            # self.actionconnect.triggered.connect(con.connect)
            # self.actiondisconnect.triggered.connect(con.disconnect)
            self.actionreconnect.triggered.connect(con.reconnect)
            self.actionstop.triggered.connect(con.stop)
            self.actionstopcurrent.triggered.connect(con.stop_current)
            self.actiontargetcurr.triggered.connect(con.target_current_all)
            self.actionreadpos.triggered.connect(con.refresh_positions)
            self.actionreadavgpos.triggered.connect(con.refresh_positions_averaged)
            self.actionreadavgpos100.triggered.connect(
                lambda *, ctrl=con: ctrl.refresh_positions(navg=100)
            )

            con.mmthread.sigMoveStarted.connect(self.move_started)
            con.mmthread.sigMoveFinished.connect(self.move_finished)

            con.plot.sigClosed.connect(lambda: self.actionplotpos.setChecked(False))

        # Add delta control
        self.delta_widget = DeltaWidget()
        self.delta_widget.sigStepped.connect(self.step_delta)
        self.delta_widget.sigMoved.connect(self.move_delta)
        self.verticalLayout.addWidget(self.delta_widget)

        # Setup logging
        self.log_writer = LoggingProc(LOG_DIR)
        self.log_writer.start()

        # Setup server
        self.server = ManiServer()
        self.server.sigRequest.connect(self.parse_request)
        self.server.sigMove.connect(self.parse_move)
        self.sigReply.connect(self.server.set_value)
        self.server.start()

        # Connect to controllers
        self.connect()

    @QtCore.Slot(object)
    def parse_request(self, request: list[str]):
        if len(request) == 0:
            # `?`
            self.sigReply.emit(
                self.get_current_positions(0) + self.get_current_positions(1)
            )
        elif request[0] == "STATUS":
            # `? STATUS`
            self.sigReply.emit(self.status)
        elif request[0] == "TOL":
            # `? X TOL`
            self.sigReply.emit(self.get_axis(request[1]).abs_tolerance)
        elif request[0] == "MIN":
            # `? Y MIN`
            self.sigReply.emit(self.get_axis(request[1]).minimum)
        elif request[0] == "MAX":
            # `? Z MAX`
            self.sigReply.emit(self.get_axis(request[1]).maximum)
        else:
            # `? X`, `? Y`, etc.
            con_idx, channel = self.get_axis_index(request[0])
            if con_idx is None:
                print("AXIS NOT FOUND")
                self.sigReply.emit(np.nan)
            else:
                self.sigReply.emit(self.get_current_position(con_idx, channel))

    @QtCore.Slot(str, float)
    def parse_move(self, axis: str, value: float):
        ch = self.get_axis(axis)
        if ch is None:
            print("AXIS NOT FOUND")
            self.sigReply.emit(1)
            return
        ch.set_target(value)
        ch.move()
        self.sigReply.emit(0)

    def get_axis(self, axis: str) -> SingleChannelWidget | None:
        for con in self.controllers:
            for ch in con.channels:
                if ch.enabled and ch.name == axis:
                    return ch
        return None

    def get_axis_index(self, axis: str) -> tuple[int, int] | tuple[None, None]:
        for i, con in enumerate(self.controllers):
            for j, ch in enumerate(con.channels):
                if ch.enabled and ch.name == axis:
                    return i, j + 1
        return None, None

    def get_xy_axes(
        self,
    ) -> tuple[SingleChannelWidget, SingleChannelWidget] | tuple[None, None]:
        chx, chy = self.get_axis("X"), self.get_axis("Y")
        if chx is None or chy is None:
            QtWidgets.QMessageBox.warning(
                self, "Missing motor", "X or Y motor is not enabled."
            )
            return None, None
        return chx, chy

    @property
    def status(self) -> MMStatus:
        """Status of the motors.

        If one or more axis is moving, returns `MMStatus.Moving`. If no axis is moving
        and one or more axis is aborted, returns `MMStatus.Aborted`. Otherwise, returns
        `MMStatus.Done`.

        """
        status_list = [con.status for con in self.controllers]
        if MMStatus.Moving in status_list:
            return MMStatus.Moving
        elif MMStatus.Aborted in status_list:
            return MMStatus.Aborted
        else:
            return MMStatus.Done

    @QtCore.Slot(int, int, int, int, object)
    def move(
        self,
        con_idx: int,
        channel: int,
        target: int,
        frequency: int,
        amplitude: tuple[int, int],
    ):
        self.controllers[con_idx].move(channel, target, frequency, amplitude)

    @QtCore.Slot(float)
    def step_delta(self, value: float):
        chx, chy = self.get_xy_axes()
        if chx is None or chy is None:
            return

        beam_incidence = np.deg2rad(50)
        newx = chx.target_spin.value() + value * np.cos(beam_incidence)
        newy = chy.target_spin.value() + value * np.sin(beam_incidence)

        if not chx.minimum <= newx <= chx.maximum:
            QtWidgets.QMessageBox.warning(
                self,
                "Out of bounds",
                f"New X value {newx:.2f} is out of bounds.",
            )
            return
        if not chy.minimum <= newy <= chy.maximum:
            QtWidgets.QMessageBox.warning(
                self,
                "Out of bounds",
                f"New Y value {newy:.2f} is out of bounds.",
            )
            return

        chx.set_target(newx)
        chy.set_target(newy)

    @QtCore.Slot()
    def move_delta(self):
        chx, chy = self.get_xy_axes()
        if chx is None or chy is None:
            return
        chx.move()
        chy.move()

    def get_current_positions(self, con_idx: int) -> list[float]:
        con = self.controllers[con_idx]
        if con.status != MMStatus.Moving:
            con.refresh_positions(navg=10)
        return [ch.current_pos for ch in con.channels]

    def get_current_position(self, con_idx: int, channel: int) -> float:
        con = self.controllers[con_idx]
        if con.status != MMStatus.Moving:
            con.refresh_position(channel, navg=10)
        return con.get_channel(channel).current_pos

    def connect(self):
        for con in self.controllers:
            try:
                con.connect_raise()
            except Exception as e:
                con.disable()

    def disconnect(self):
        for con in self.controllers:
            if con.isEnabled():
                con.disconnect()

    def get_channel(self, con_idx: int, channel: int) -> SingleChannelWidget:
        return self.controllers[con_idx].get_channel[channel]

    @QtCore.Slot(object)
    def write_log(self, content: str | list[str]):
        self.log_writer.add_content(content)

    @QtCore.Slot()
    def refresh_plot_visibility(self):
        for con in self.controllers:
            if con.isEnabled():
                if self.actionplotpos.isChecked():
                    if not con.plot.isVisible():
                        con.plot.show()
                else:
                    if con.plot.isVisible():
                        con.plot.hide()

    @QtCore.Slot()
    def move_started(self):
        self.actionreadpos.setDisabled(True)
        self.actionreadavgpos.setDisabled(True)
        self.actionreadavgpos100.setDisabled(True)
        self.actionreadcap.setDisabled(True)

    @QtCore.Slot()
    def move_finished(self):
        self.actionreadpos.setDisabled(False)
        self.actionreadavgpos.setDisabled(False)
        self.actionreadavgpos100.setDisabled(False)
        self.actionreadcap.setDisabled(False)

    @QtCore.Slot()
    def check_capacitance(self):
        n_valid = sum([len(con.valid_channels) for con in self.controllers])

        if n_valid == 0:
            QtWidgets.QMessageBox.warning(
                self,
                "No enabled channels",
                "Enable at least one channel to measure the capacitance.",
            )
            return

        valid_channels: tuple[list[int]] = tuple(
            con.valid_channel_numbers for con in self.controllers
        )

        valid_names = []
        for i, nums in enumerate(valid_channels):
            valid_names += [f"{i}-{n}" for n in nums]

        ret = QtWidgets.QMessageBox.question(
            self,
            "Capacitance check",
            "Check capacitance for all enabled channel(s) "
            f"{', '.join(valid_names)}?",
        )
        if ret == QtWidgets.QMessageBox.Yes:
            res = []

            for i, nums in enumerate(valid_channels):
                if len(nums) > 0:
                    res = res + [
                        f"{i}-" + r for r in self.controllers[i].get_capacitance()
                    ]
            QtWidgets.QMessageBox.information(
                self, "Capacitance measured", "\n".join(res)
            )

    def closeEvent(self, *args, **kwargs):
        # disconnect from controllers
        self.disconnect()

        # stop log writer
        self.log_writer.stop()

        # stop server
        self.server.stopped.set()
        self.server.wait(2000)

        # close plots
        for con in self.controllers:
            con.plot.close()
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":
    multiprocessing.freeze_support()

    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setWindowIcon(QtGui.QIcon("./icon.ico"))
    # qapp.setStyle("Fusion")

    win = MainWindow()
    win.show()
    win.activateWindow()
    qapp.exec()
