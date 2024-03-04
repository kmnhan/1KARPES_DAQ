"""GUI for the 1K ARPES 6-axis manipulator"""

import multiprocessing
import os
import sys
from multiprocessing import shared_memory

import numpy as np
from qtpy import QtCore, QtGui, QtWidgets, uic

from maniserver import ManiServer
from moee import MMStatus
from motionwidgets import (
    DeltaWidget,
    LoggingProc,
    SingleChannelWidget,
    SingleControllerWidget,
)

LOG_DIR = "D:/Logs/Motion"

CONTROLLERS: tuple[str, ...] = ("192.168.0.210", "192.168.0.211")

try:
    os.chdir(sys._MEIPASS)
except:
    pass


class MainWindow(*uic.loadUiType("controller.ui")):
    """Combines two controlller widgets to form a complete GUI.

    On initialization, starts a server so that motion can be controlled by other
    programs. Also creates shared memory for motor positions with name `MotorPositions`.

    """

    sigReply = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("Motion Control")

        # Shared memory for motor positions
        self.shm = shared_memory.SharedMemory(
            name="MotorPositions", create=True, size=8 * 3 * len(CONTROLLERS)
        )
        arr = np.ndarray((6,), dtype="f8", buffer=self.shm.buf)
        arr[:] = np.nan

        self.stop_btn.setDefaultAction(self.actionstop)
        self.stopcurrent_btn.setDefaultAction(self.actionstopcurrent)
        # self.readpos_btn.setDefaultAction(self.actionreadpos)
        # self.readavgpos_btn.setDefaultAction(self.actionreadavgpos)
        self.readpos_btn.setVisible(False)
        self.readavgpos_btn.setVisible(False)
        self.actionreadpos.setVisible(False)
        self.actionreadavgpos.setVisible(False)
        self.actionreadavgpos100.setVisible(False)

        self.actionplotpos.triggered.connect(self.refresh_plot_visibility)
        self.actionreadcap.triggered.connect(self.check_capacitance)

        # Setup logging
        self.logwriter = LoggingProc(LOG_DIR)
        self.logwriter.start()

        # Initialize controllers
        self.controllers: tuple[SingleControllerWidget, SingleControllerWidget] = tuple(
            SingleControllerWidget(
                self, address=address, index=idx, logwriter=self.logwriter
            )
            for idx, address in enumerate(CONTROLLERS)
        )
        for con in self.controllers:
            self.verticalLayout.addWidget(con)

            self.actionreconnect.triggered.connect(con.reconnect)
            self.actionstop.triggered.connect(con.stop)
            self.actionstopcurrent.triggered.connect(con.stop_current)
            self.actiontargetcurr.triggered.connect(con.target_current_all)
            # self.actionreadpos.triggered.connect(con.refresh_positions)
            # self.actionreadavgpos.triggered.connect(con.refresh_positions_averaged)
            # self.actionreadavgpos100.triggered.connect(
            # lambda *, ctrl=con: ctrl.refresh_positions(navg=100)
            # )

            con.sigPositionUpdated.connect(self.position_updated)

            con.mmthread.sigMoveStarted.connect(self.move_started)
            con.mmthread.sigMoveFinished.connect(self.move_finished)
            con.plot.sigClosed.connect(lambda: self.actionplotpos.setChecked(False))

        # Add delta control
        self.delta_widget = DeltaWidget()
        self.delta_widget.sigStepped.connect(self.step_delta)
        self.delta_widget.sigMoved.connect(self.move_delta)
        self.verticalLayout.addWidget(self.delta_widget)

        # Setup server
        self.server = ManiServer()
        self.server.sigRequest.connect(self.parse_request)
        self.server.sigCommand.connect(self.parse_command)
        self.server.sigMove.connect(self.parse_move)
        self.sigReply.connect(self.server.set_value)
        self.server.start()

        # Connect to controllers
        self.connect()

        # Show plot by default
        self.actionplotpos.setChecked(True)
        self.refresh_plot_visibility()

    @QtCore.Slot(str, str)
    def parse_request(self, command: str, args: str) -> None:
        if command == "STATUS":
            if args == "":
                rep = str(self.status)
            else:
                rep = str(getattr(self.get_controller(args), "status", np.nan))

        elif command == "NAME":
            if args == "" or args == "0":
                rep = ",".join(
                    [ch.name for con in self.controllers for ch in con.channels]
                )
            else:
                rep = getattr(self.get_channel(args), "name", "")

        elif command == "FIN":
            rep = str(int(self.is_finished(args)))

        elif command == "ENABLED":
            if args == "" or args == "0":
                rep = ",".join(
                    [
                        str(int(ch.enabled))
                        for con in self.controllers
                        for ch in con.channels
                    ]
                )
            else:
                rep = str(int(getattr(self.get_channel(args), "enabled", False)))

        elif command == "POS":
            if args == "" or args == "0":
                rep = ",".join([str(val) for val in self.current_positions])
            else:
                ch = self.get_channel(args)
                if getattr(ch, "enabled", False):
                    rep = str(ch.current_pos)
                else:
                    rep = str(np.nan)

        elif command == "TOL":
            rep = str(getattr(self.get_channel(args), "tolerance", np.nan))

        elif command == "ATOL":
            rep = str(getattr(self.get_channel(args), "abs_tolerance", np.nan))

        elif command == "MINMAX":
            ch = self.get_channel(args)
            mn, mx = getattr(ch, "minimum", np.nan), getattr(ch, "maximum", np.nan)
            rep = f"{mn},{mx}"

        self.sigReply.emit(rep)

    @QtCore.Slot(str, str)
    def parse_command(self, command: str, args: str):
        if command == "CLR":
            unique_id = args
            self.forget_uid(unique_id)

    @QtCore.Slot(str, float, object)
    def parse_move(self, axis: int | str, value: float, unique_id: str | None):
        ch = self.get_channel(axis)
        if getattr(ch, "enabled", False):
            ch.move_to(float(value), unique_id=unique_id)
        else:
            print("Axis disabled or nonexistent, not moving")

    def is_finished(self, unique_id: str) -> bool:
        for con in self.controllers:
            if con.is_finished(unique_id):
                return True
        return False

    def is_started(self, unique_id: str) -> bool:
        for con in self.controllers:
            if con.is_started(unique_id):
                return True
        return False

    def forget_uid(self, unique_id: str):
        for con in self.controllers:
            con.forget_uid(unique_id)

    def get_channel(self, axis: int | str) -> SingleChannelWidget | None:
        # Retrieves the channel corresponding to the specified axis.
        # Returns `None` if no matching axis is found.
        if isinstance(axis, int) or axis.isdigit():
            axis_idx = int(axis) - 1
            return self.controllers[axis_idx // 3].channels[axis_idx % 3]
        else:
            for con in self.controllers:
                for ch in con.channels:
                    if ch.name == axis:
                        return ch
            return None

    def get_controller(self, axis: int | str) -> SingleControllerWidget | None:
        if isinstance(axis, int) or axis.isdigit():
            return self.controllers[int(axis)]
        else:
            for con in self.controllers:
                for ch in con.channels:
                    if ch.name == axis:
                        return con
            return None

    def get_xy_axes(
        self,
    ) -> tuple[SingleChannelWidget, SingleChannelWidget] | tuple[None, None]:
        chx, chy = self.get_channel("X"), self.get_channel("Y")
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

    # def refresh_positions(self, navg: int = 10):
    #     for con in self.controllers:
    #         con.refresh_positions(navg=navg)

    @QtCore.Slot(int, float)
    def position_updated(self, channel_index: int, pos: float):
        # Update shared memory with new position
        np.ndarray((3 * len(CONTROLLERS),), dtype="f8", buffer=self.shm.buf)[
            channel_index
        ] = float(pos)

    @property
    def current_positions(self) -> tuple[float, ...]:
        # return sum((con.current_positions for con in self.controllers), tuple())
        return tuple(
            np.ndarray((3 * len(CONTROLLERS),), dtype="f8", buffer=self.shm.buf)
        )

    def get_current_position(self, con_idx: int, channel: int) -> float:
        con = self.controllers[con_idx]
        # con.refresh_position(channel, navg=10)
        return con.get_channel(channel).current_pos

    def connect(self):
        for con in self.controllers:
            con.connect_silent()

    def disconnect(self):
        for con in self.controllers:
            con.disconnect()

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
        # self.actionreadpos.setDisabled(True)
        # self.actionreadavgpos.setDisabled(True)
        # self.actionreadavgpos100.setDisabled(True)
        self.actionreadcap.setDisabled(True)

    @QtCore.Slot()
    def move_finished(self):
        # self.actionreadpos.setDisabled(False)
        # self.actionreadavgpos.setDisabled(False)
        # self.actionreadavgpos100.setDisabled(False)
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

        valid_channels: tuple[tuple[int, ...], tuple[int, ...]] = tuple(
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
        # Disconnect from controllers
        self.disconnect()

        # Close shared memory
        self.shm.close()
        self.shm.unlink()

        # stop log writer
        self.logwriter.stop()

        # stop server
        self.server.stopped.set()
        self.server.wait(2000)

        # Handle controller close events
        for con in self.controllers:
            con.close()
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":
    multiprocessing.freeze_support()

    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setWindowIcon(QtGui.QIcon("./icon.ico"))
    qapp.setStyle("Fusion")

    win = MainWindow()
    win.show()
    win.activateWindow()
    qapp.exec()
