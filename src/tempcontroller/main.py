import collections
import configparser
import csv
import datetime
import json
import multiprocessing
import os
import sys
import time

import numpy as np
import pyqtgraph as pg
import pyvisa
import tomlkit
from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from qtpy import QtCore, QtGui, QtWidgets, uic

from connection import LakeshoreThread
from widgets import CommandWidget, HeaterWidget, QHLine, QVLine, ReadingWidget

try:
    os.chdir(sys._MEIPASS)
except:
    pass


def header_changed(filename, header: list[str]) -> bool:
    """Check log file and determine whether new header needs to be appended."""

    if not os.path.isfile(filename):
        return True

    last_header = ""
    with open(filename, "r") as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith("Time"):
                last_header = lines[i]
    if last_header.strip().split(",") == header:
        return False
    else:
        return True


class LoggingProc(multiprocessing.Process):
    def __init__(self, log_dir: str | os.PathLike, header: list[str]):
        super().__init__()
        self.log_dir = log_dir
        self.header = header
        self._stopped = multiprocessing.Event()
        self.queue = multiprocessing.Manager().Queue()

    def run(self):
        self._stopped.clear()

        while not self._stopped.is_set():
            time.sleep(0.02)

            if self.queue.empty():
                continue

            # retrieve message from queue
            dt, msg = self.queue.get()
            filename = os.path.join(self.log_dir, dt.strftime("%y%m%d") + ".csv")
            try:
                # Check whether to add header before writing message
                need_header = header_changed(filename, self.header)
                with open(filename, "a", newline="") as f:
                    writer = csv.writer(f)
                    if need_header:
                        writer.writerow(self.header)
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
                f"Failed to write {n_left} data "
                + ("entries:" if n_left > 1 else "entry:")
            )
            for _ in range(n_left):
                dt, msg = self.queue.get()
                print(f"{dt} | {msg}")
        self._stopped.set()
        self.join()

    def append(self, timestamp: datetime.datetime, content: str | list[str]):
        if isinstance(content, str):
            content = [content]
        self.queue.put((timestamp, content))


class MainWindowGUI(*uic.loadUiType("main.ui")):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setupUi(self)
        self.setGeometry(0, 0, 300, 200)
        self.setWindowTitle("1KARPES Temperature Controller")

        # Read config file
        with open(
            QtCore.QSettings("erlab", "tempcontroller").value("config_file"), "r"
        ) as f:
            self.config = tomlkit.load(f)

        self.readings_336 = ReadingWidget(
            inputs=("A", "B", "C", "D"),
            names=self.config["general"]["names_336"],
            decimals=3,
        )
        self.readings_218_0 = ReadingWidget(
            inputs=tuple(str(i) for i in range(1, 5)),
            names=list(self.config["general"]["names_218"])[:4],
            indexer=slice(0, 4),
        )
        self.readings_218_1 = ReadingWidget(
            inputs=tuple(str(i) for i in range(5, 9)),
            names=list(self.config["general"]["names_218"])[4:],
            indexer=slice(4, 8),
        )

        readings_218_combined = QtWidgets.QWidget()
        readings_218_combined.setLayout(QtWidgets.QHBoxLayout())
        readings_218_combined.layout().setContentsMargins(0, 0, 0, 0)
        readings_218_combined.layout().addWidget(self.readings_218_0)
        readings_218_combined.layout().addWidget(QVLine())
        readings_218_combined.layout().addWidget(self.readings_218_1)
        self.readings_331 = ReadingWidget(
            inputs=(" ",),
            names=self.config["general"]["names_331"],
            hide_srdg=True,
            krdg_command="KRDG? B",
            srdg_command="SRDG? B",
        )

        self.group0.layout().addWidget(self.readings_336)
        self.group1.layout().addWidget(self.readings_331)
        self.group2.layout().addWidget(readings_218_combined)

        # d1 = Dock(f"Lakeshore 336", widget=self.readings_336)
        # d2 = Dock(f"Lakeshore 218", widget=readings_218_combined)
        # d3 = Dock(f"Lakeshore 331", widget=self.readings_331)
        # self.area.addDock(d1, "left")
        # self.area.addDock(d2, "right", d1)
        # self.area.addDock(d3, "bottom", d1)

        self.heaters = QtWidgets.QWidget()
        self.heaters.setLayout(QtWidgets.QVBoxLayout())
        self.heaters.setWindowTitle("Heaters")
        self.heaters.layout().setContentsMargins(3, 3, 3, 3)

        area = DockArea()
        self.heaters.layout().addWidget(area)

        self.heater1 = HeaterWidget(output="1")
        self.heater2 = HeaterWidget(output="2")
        self.heater3 = HeaterWidget(output="", loop="1")
        d1 = Dock(f"336 Heater1 (D) Control", widget=self.heater1)
        d2 = Dock(f"336 Heater2 (C) Control", widget=self.heater2)
        d3 = Dock(f"331 Heater Control", widget=self.heater3)
        area.addDock(d2, "left")
        area.addDock(d1, "right", d2)
        area.addDock(d3, "right", d1)

        self.commands = QtWidgets.QTabWidget()
        self.commands.setWindowTitle("Command")
        self.command336 = CommandWidget()
        self.command218 = CommandWidget()
        self.command331 = CommandWidget()

        self.commands.addTab(self.command336, "336")
        self.commands.addTab(self.command218, "218")
        self.commands.addTab(self.command331, "331")

        self.actionheaters.triggered.connect(self.show_heaters)
        self.actioncommand.triggered.connect(self.show_commands)
        self.actionsensorunit.triggered.connect(self.toggle_sensorunits)

    def show_heaters(self):
        rect = self.geometry()
        self.heaters.setGeometry(rect.x() + rect.width(), rect.y(), 300, 150)
        self.heaters.show()

    def show_commands(self):
        rect = self.geometry()
        self.commands.setGeometry(rect.x() + rect.width(), rect.y(), 250, 200)
        self.commands.show()

    def overwrite_config(self):
        with open(
            QtCore.QSettings("erlab", "tempcontroller").value("config_file"), "w"
        ) as f:
            tomlkit.dump(self.config, f)

    def toggle_sensorunits(self):
        for rw in (
            self.readings_336,
            self.readings_218_0,
            self.readings_218_1,
            self.readings_331,
        ):
            rw.set_srdg_visible(not rw.srdg_enabled)

    def closeEvent(self, *args, **kwargs):
        self.heaters.close()
        self.commands.close()
        super().closeEvent(*args, **kwargs)


class MainWindow(MainWindowGUI):
    sigUpdate = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize temperature controller threads
        self.lake218 = LakeshoreThread("GPIB0::12::INSTR", baud_rate=9600)
        self.lake331 = LakeshoreThread("GPIB0::15::INSTR", baud_rate=9600)
        self.lake336 = LakeshoreThread("GPIB0::18::INSTR", baud_rate=57600)

        # Link reading, command, and heater widgets to corresponding thread
        self.readings_331.instrument = self.lake331
        self.readings_218_0.instrument = self.lake218
        self.readings_218_1.instrument = self.lake218
        self.readings_336.instrument = self.lake336

        self.command336.instrument = self.lake336
        self.command218.instrument = self.lake218
        self.command331.instrument = self.lake331

        self.heater1.instrument = self.lake336
        self.heater2.instrument = self.lake336
        self.heater3.instrument = self.lake331

        self.heater1.curr_spin = self.readings_336.krdg_spins[3]
        self.heater2.curr_spin = self.readings_336.krdg_spins[2]
        self.heater3.curr_spin = self.readings_331.krdg_spins[0]

        # Connect update signal
        self.sigUpdate.connect(self.readings_331.trigger_update)
        self.sigUpdate.connect(self.readings_218_0.trigger_update)
        self.sigUpdate.connect(self.readings_218_1.trigger_update)
        self.sigUpdate.connect(self.readings_336.trigger_update)
        self.sigUpdate.connect(self.heater1.trigger_update)
        self.sigUpdate.connect(self.heater2.trigger_update)
        self.sigUpdate.connect(self.heater3.trigger_update)

        # Start threads
        self.start_threads()

        # Reset based on config
        if self.config["acquisition"].get("reset_336", True):
            self.lake336.request_write("*RST")
        if self.config["acquisition"].get("reset_331", True):
            self.lake331.request_write("*RST")
        if self.config["acquisition"].get("reset_218", True):
            self.lake218.request_write("*RST")

        # Set heater options
        # Max current 0.1 A for pump is hardcoded to protect the GL4.
        self.lake336.request_write("HTRSET 1,1,2,0,2")
        self.lake336.request_write("HTRSET 2,2,0,0.1,2")

        # Setup plotting
        refresh_time = float(self.config["acquisition"]["refresh_time"])
        minutes = self.config["acquisition"].get("plot_size_minutes", 30)
        maxlen = (minutes * 60) / refresh_time

        # Setup refresh timer
        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setInterval(round(refresh_time * 1000))
        self.refresh_timer.timeout.connect(self.update)

        # Get logging parameters from config
        log_dir = str(self.config["logging"]["directory"])
        log_interval = float(self.config["logging"]["interval"])

        # Setup log writing process
        self.log_writer = LoggingProc(log_dir, header=self.header)
        self.log_writer.start()

        # Setup logging timer
        self.log_timer = QtCore.QTimer(self)
        self.set_logging_interval(log_interval, update_config=False)
        self.log_timer.timeout.connect(self.write_log)

        # Start acquiring & logging
        self.refresh_timer.start()
        self.log_timer.start()

    def start_threads(self):
        self.lake218.start()
        self.lake331.start()
        self.lake336.start()
        # Wait until all threads are ready
        while not all(
            (
                hasattr(self.lake218, "queue"),
                hasattr(self.lake331, "queue"),
                hasattr(self.lake336, "queue"),
            )
        ):
            time.sleep(1e-3)

    def stop_threads(self):
        self.lake218.stopped.set()
        self.lake331.stopped.set()
        self.lake336.stopped.set()
        self.lake218.wait()
        self.lake331.wait()
        self.lake336.wait()

    def set_logging_interval(self, value: float, update_config: bool = True):
        self.log_timer.setInterval(round(value * 1000))
        if update_config:
            self.config["logging"]["interval"] = value
            self.overwrite_config()

    def update(self):
        # Trigger updates
        self.sigUpdate.emit()

    @property
    def header(self) -> list[str]:
        header = ["Time"]
        all_names: list[str] = (
            self.config["general"]["names_336"]
            + self.config["general"]["names_218"]
            + self.config["general"]["names_331"]
        )
        header += all_names
        header += [n + " (SU)" for n in all_names]
        header += [
            "336 Setpoint1 (K)",
            "336 Heater1 (%)",
            "336 Setpoint2 (K)",
            "336 Heater2 (%)",
            "331 Setpoint (K)",
            "331 Heater (%)",
        ]
        return header

    @property
    def values(self) -> list[str]:
        return (
            self.readings_336.krdg_raw
            + self.readings_218_0.krdg_raw
            + self.readings_218_1.krdg_raw
            + self.readings_331.krdg_raw
            + self.readings_336.srdg_raw
            + self.readings_218_0.srdg_raw
            + self.readings_218_1.srdg_raw
            + self.readings_331.srdg_raw
            + [
                self.heater1.setp_raw,
                self.heater1.htr_raw,
                self.heater2.setp_raw,
                self.heater2.htr_raw,
                self.heater3.setp_raw,
                self.heater3.htr_raw,
            ]
        )

    def write_log(self):
        dt = datetime.datetime.now()
        self.log_writer.append(dt, [v.lstrip("+") for v in self.values])

    def closeEvent(self, *args, **kwargs):
        self.stop_threads()
        pyvisa.ResourceManager().close()
        self.log_writer.stop()
        super().closeEvent(*args, **kwargs)


class ConfigFileDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Choose config.toml file")
        self.setLayout(QtWidgets.QVBoxLayout())

        box = QtWidgets.QWidget()
        box.setLayout(QtWidgets.QHBoxLayout())
        box.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(box)

        self.line = QtWidgets.QLineEdit()
        box.layout().addWidget(self.line)

        button = QtWidgets.QPushButton("Choose File")
        button.clicked.connect(self.choose_file)
        box.layout().addWidget(button)

        self.buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.layout().addWidget(self.buttonBox)

    def accept(self):
        if valid_config(self.line.text()):
            QtCore.QSettings("erlab", "tempcontroller").setValue(
                "config_file", self.line.text()
            )
        else:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Config File",
                f"An error occurred while parsing the file.",
            )
        super().accept()

    def choose_file(self):
        dialog = QtWidgets.QFileDialog(self)
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptOpen)
        dialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilter("Configuration file (*.toml)")

        if dialog.exec():
            self.line.setText(dialog.selectedFiles()[0])


def valid_config(filename: str | None = None) -> bool:
    """Return True if a valid config file has been added, False otherwise."""
    if filename is None:
        filename = QtCore.QSettings("erlab", "tempcontroller").value("config_file", "")
    try:
        with open(filename, "r") as f:
            tomlkit.load(f)
            return True
    except Exception as e:
        print(e)
        return False


if __name__ == "__main__":
    multiprocessing.freeze_support()

    qapp = QtWidgets.QApplication(sys.argv)
    # qapp.setWindowIcon(QtGui.QIcon("./icon.ico"))
    # qapp.setStyle("Fusion")

    while not valid_config():
        configdialog = ConfigFileDialog()
        if configdialog.exec() != QtWidgets.QDialog.Accepted:
            break
    else:
        win = MainWindow()
        win.show()
        win.activateWindow()
        qapp.exec()
