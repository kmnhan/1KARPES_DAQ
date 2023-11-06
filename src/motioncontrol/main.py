"""GUI for the 1K ARPES 6-axis manipulator"""
import csv
import datetime
import os
import sys
import threading
import time
from collections import deque

from maniserver import ManiServer
from moee import MMStatus
from motionwidgets import SingleChannelWidget, SingleControllerWidget
from qtpy import QtCore, QtGui, QtWidgets, uic

try:
    os.chdir(sys._MEIPASS)
except:
    pass

LOG_DIR = "D:/MotionController/logs"
# LOG_DIR = os.path.expanduser("~/MotionController/logs")


class LoggingThread(threading.Thread):
    """Thread for logging manipulator motion.

    Parameters
    ----------
    log_dir
        Directory where the log file will be stored. The filename will be automatically
        determined from the current date and time.

    """

    def __init__(self, log_dir: str | os.PathLike):
        super().__init__()
        self.log_dir = log_dir
        self._stopped: bool = False
        self.messages: deque[tuple[datetime.datetime, list[str]]] = deque()

    def run(self):
        self._stopped = False
        while not self._stopped:
            time.sleep(0.2)
            if len(self.messages) == 0:
                continue
            dt, msg = self.messages.popleft()
            try:
                with open(
                    os.path.join(self.log_dir, dt.strftime("%y%m%d") + ".csv"),
                    "a",
                    newline="",
                ) as f:
                    writer = csv.writer(f)
                    writer.writerow([dt.isoformat()] + msg)
            except PermissionError:
                self.messages.appendleft((dt, msg))
                continue

    def stop(self):
        n_left = len(self.messages)
        if n_left != 0:
            print(
                f"Failed to write {n_left} log "
                + ("entries:" if n_left > 1 else "entry:")
            )
            for dt, msg in self.messages:
                print(f"{dt} | {msg}")
        self._stopped = True
        self.join()

    def add_content(self, content: str | list[str]):
        now = datetime.datetime.now()
        if isinstance(content, str):
            content = [content]
        self.messages.append((now, content))


class MainWindow(*uic.loadUiType("controller.ui")):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("1KARPES Motion Control")

        self.stop_btn.setDefaultAction(self.actionstop)
        self.readpos_btn.setDefaultAction(self.actionreadpos)

        self.actionplotpos.triggered.connect(self.refresh_plot_visibility)
        self.actionreadcap.triggered.connect(self.check_capacitance)

        # initialize controllers
        self.controllers: tuple[SingleControllerWidget, SingleControllerWidget] = (
            SingleControllerWidget(self, "192.168.0.210"),
            SingleControllerWidget(self, "192.168.0.211"),
        )
        for con in self.controllers:
            self.verticalLayout.addWidget(con)
            con.writeLog.connect(self.write_log)

            # self.actionconnect.triggered.connect(con.connect)
            # self.actiondisconnect.triggered.connect(con.disconnect)
            self.actionreconnect.triggered.connect(con.reconnect)
            self.actionstop.triggered.connect(con.stop)
            self.actiontargetcurr.triggered.connect(con.target_current_all)
            self.actionreadpos.triggered.connect(con.refresh_positions)

            con.mmthread.sigMoveStarted.connect(self.move_started)
            con.mmthread.sigMoveFinished.connect(self.move_finished)

            con.plot.sigClosed.connect(lambda: self.actionplotpos.setChecked(False))

        # setup logging
        self.log_writer = LoggingThread(LOG_DIR)
        self.log_writer.start()

        # setup server
        self.server = ManiServer()
        self.server.start()

        # connect to controllers
        self.connect()

    @property
    def status(self) -> MMStatus:
        status_list = [con.status for con in self.controllers]
        if MMStatus.Moving in status_list:
            return MMStatus.Moving
        elif MMStatus.Aborted in status_list:
            return MMStatus.Aborted
        else:
            return MMStatus.Done

    @QtCore.Slot(int, int, int, object)
    def move(
        self,
        con_idx: int,
        channel: int,
        target: int,
        frequency: int,
        amplitude: tuple[int, int],
    ):
        self.controllers[con_idx].move(channel, target, frequency, amplitude)

    def get_current_positions(self, con_idx: int) -> list[float]:
        con = self.controllers[con_idx]
        if con.status != MMStatus.Moving:
            con.refresh_positions()
        return [ch.current_pos for ch in con.channels]

    def get_current_position(self, con_idx: int, channel: int) -> float:
        con = self.controllers[con_idx]
        if con.status != MMStatus.Moving:
            con.refresh_position(channel)
        con.get_channel(channel).current_pos
        return [ch.current_pos for ch in con.channels]

    def connect(self):
        for con in self.controllers:
            try:
                con.connect_raise()
            except Exception as e:
                con.disable()

    def disconnect(self):
        for con in self.controllers:
            con.disconnect()

    def get_channel(self, con_idx: int, channel: int) -> SingleChannelWidget:
        return self.controllers[con_idx].get_channel[channel]

    @QtCore.Slot(object)
    def write_log(self, content: str | list[str]):
        self.log_writer.add_content(content)

    @QtCore.Slot()
    def refresh_plot_visibility(self):
        for con in self.controllers:
            if self.actionplotpos.isChecked():
                if not con.plot.isVisible():
                    con.plot.show()
            else:
                if con.plot.isVisible():
                    con.plot.hide()

    @QtCore.Slot()
    def move_started(self):
        self.actionreadpos.setDisabled(True)
        self.actionreadcap.setDisabled(True)

    @QtCore.Slot()
    def move_finished(self):
        self.actionreadpos.setDisabled(False)
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
        # stop server
        self.server.running = False
        self.server.wait(2000)

        # disconnect from controllers
        self.disconnect()

        # stop log writer
        self.log_writer.stop()

        # close plots
        for con in self.controllers:
            con.plot.close()
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
