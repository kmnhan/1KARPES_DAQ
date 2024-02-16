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
from widgets import HeaterWidget, QHLine, QVLine, ReadingWidget, CommandWidget

try:
    os.chdir(sys._MEIPASS)
except:
    pass


class LoggingProc(multiprocessing.Process):
    def __init__(self, log_dir: str | os.PathLike):
        super().__init__()
        self.log_dir = log_dir
        self._stopped = multiprocessing.Event()
        self.queue = multiprocessing.Queue()

    def run(self):
        self._stopped.clear()
        while not self._stopped.is_set():
            time.sleep(0.02)

            if self.queue.empty():
                continue

            # retrieve message from queue
            dt, msg, is_header = self.queue.get()
            try:
                with open(
                    os.path.join(self.log_dir, dt.strftime("%y%m%d") + ".csv"),
                    "a",
                    newline="",
                ) as f:
                    writer = csv.writer(f)
                    if is_header:
                        writer.writerow(msg)
                    else:
                        writer.writerow([dt.isoformat()] + msg)
            except PermissionError:
                # put back the retrieved message in the queue
                n_left = int(self.queue.qsize())
                self.queue.put((dt, msg, is_header))
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

    def append(self, timestamp: datetime.datetime, content, is_header: bool = False):
        if isinstance(content, str):
            content = [content]
        self.queue.put((timestamp, content, is_header))


class MainWindowGUI(*uic.loadUiType("main.ui")):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setupUi(self)
        self.setWindowTitle("1KARPES Temperature Controller")

        # Read config file
        with open(
            QtCore.QSettings("erlab", "tempcontroller").value("config_file"), "r"
        ) as f:
            self.config = tomlkit.load(f)

        self.readings_336 = ReadingWidget(
            inputs=("A", "B", "C", "D"),
            names=self.config["config"]["names_336"],
            decimals=3,
        )
        self.readings_218_0 = ReadingWidget(
            inputs=tuple(str(i) for i in range(1, 5)),
            names=list(self.config["config"]["names_218"])[:4],
            indexer=slice(0, 4),
        )
        self.readings_218_1 = ReadingWidget(
            inputs=tuple(str(i) for i in range(5, 9)),
            names=list(self.config["config"]["names_218"])[4:],
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
            names=self.config["config"]["names_331"],
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

        self.heaters = DockArea()
        self.heaters.setWindowTitle("Heaters")
        self.heater1 = HeaterWidget()
        self.heater2 = HeaterWidget()
        self.heater3 = HeaterWidget()
        d1 = Dock(f"336 Heater1 (D) Control", widget=self.heater1)
        d2 = Dock(f"336 Heater2 (C) Control", widget=self.heater2)
        d3 = Dock(f"331 Heater Control", widget=self.heater3)
        self.heaters.addDock(d2, "left")
        self.heaters.addDock(d1, "right", d2)
        self.heaters.addDock(d3, "right", d1)

        self.commands = DockArea()
        # self.commands.setWindowTitle("")
        self.command336 = CommandWidget()
        self.command218 = CommandWidget()
        self.command331 = CommandWidget()
        d4 = Dock(f"336 Command", widget=self.command336)
        d5 = Dock(f"218 Command", widget=self.command218)
        d6 = Dock(f"331 Command", widget=self.command331)
        self.heaters.addDock(d5, "left")
        self.heaters.addDock(d4, "right", d5)
        self.heaters.addDock(d6, "right", d4)

        self.actionheaters.triggered.connect(lambda: self.heaters.show())
        self.actioncommand.triggered.connect(lambda: self.commands.show())
        self.actionvoltage.triggered.connect(self.toggle_voltages)

        self.resize(100, 100)

    def overwrite_config(self):
        with open(
            QtCore.QSettings("erlab", "tempcontroller").value("config_file"), "w"
        ) as f:
            tomlkit.dump(self.config, f)

    def toggle_voltages(self):
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize temperature controller threads
        self.lake218 = LakeshoreThread("GPIB0::12::INSTR", baud_rate=9600)
        self.lake331 = LakeshoreThread("GPIB0::15::INSTR", baud_rate=9600)
        self.lake336 = LakeshoreThread("GPIB0::18::INSTR", baud_rate=57600)

        self.readings_331.instrument = self.lake331
        self.readings_218_0.instrument = self.lake218
        self.readings_218_1.instrument = self.lake218
        self.readings_336.instrument = self.lake336

        self.command336.instrument = self.lake336
        self.command218.instrument = self.lake218
        self.command331.instrument = self.lake331

        self.lake218.start()
        self.lake331.start()
        self.lake336.start()

        # Setup refresh timer
        refresh_time = float(self.config["config"]["refresh_time"])
        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setInterval(round(refresh_time * 1000))
        self.refresh_timer.timeout.connect(self.update)

        # Get logging parameters from config
        log_dir = str(self.config["logging"]["directory"])
        log_interval = float(self.config["logging"]["interval"])

        # Setup log writing process
        self.log_writer = LoggingProc(log_dir)
        self.log_writer.start()

        # Setup logging timer
        self.log_timer = QtCore.QTimer(self)
        self.set_logging_interval(log_interval, update_config=False)
        self.log_timer.timeout.connect(self.write_log)

        # Start acquiring & logging
        self.refresh_timer.start()
        self.log_timer.start()

    def set_logging_interval(self, value: float, update_config: bool = True):
        self.log_timer.setInterval(round(value * 1000))
        if update_config:
            self.config["logging"]["interval"] = value
            self.overwrite_config()

    def update(self):
        # UPDATE HEATERS HERE
        for rdng in (
            self.readings_331,
            self.readings_218_0,
            self.readings_218_1,
            self.readings_336,
        ):
            rdng.trigger_update()

    def write_log(self):
        dt = datetime.datetime.now()
        # self.log_writer.append(dt, )
        pass

    def closeEvent(self, *args, **kwargs):
        self.lake218.stopped.set()
        self.lake331.stopped.set()
        self.lake336.stopped.set()
        self.lake218.wait()
        self.lake331.wait()
        self.lake336.wait()
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
    qapp.setStyle("Fusion")

    while not valid_config():
        configdialog = ConfigFileDialog()
        if configdialog.exec() != QtWidgets.QDialog.Accepted:
            break
    else:
        win = MainWindow()
        win.show()
        win.activateWindow()
        qapp.exec()
