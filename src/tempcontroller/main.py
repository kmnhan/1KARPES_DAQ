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
from widgets import HeaterWidget, QHLine, QVLine
from widgets import ReadingWidgetGUI as ReadingWidget

try:
    os.chdir(sys._MEIPASS)
except:
    pass


class MainWindow(*uic.loadUiType("main.ui")):
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
            hide_srdg=True,
        )
        self.readings_218_0 = ReadingWidget(
            inputs=tuple(str(i) for i in range(1, 5)),
            names=list(self.config["config"]["names_218"])[:4],
            hide_srdg=False,
        )
        self.readings_218_1 = ReadingWidget(
            inputs=tuple(str(i) for i in range(5, 9)),
            names=list(self.config["config"]["names_218"])[4:],
            hide_srdg=False,
        )

        readings_218_combined = QtWidgets.QWidget()
        readings_218_combined.setLayout(QtWidgets.QHBoxLayout())
        readings_218_combined.layout().setContentsMargins(0, 0, 0, 0)
        readings_218_combined.layout().addWidget(self.readings_218_0)
        readings_218_combined.layout().addWidget(QVLine())
        readings_218_combined.layout().addWidget(self.readings_218_1)
        self.readings_331 = ReadingWidget(
            inputs=(" ",), names=self.config["config"]["names_331"], hide_srdg=False
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
        d4 = Dock(f"336 Heater1 (D) Control", widget=self.heater1)
        d5 = Dock(f"336 Heater2 (C) Control", widget=self.heater2)
        d6 = Dock(f"331 Heater Control", widget=self.heater3)
        self.heaters.addDock(d5, "left")
        self.heaters.addDock(d4, "right", d5)
        self.heaters.addDock(d6, "right", d4)

        self.actionheaters.triggered.connect(lambda: self.heaters.show())

        self.resize(100, 100)

    def closeEvent(self, *args, **kwargs):
        pyvisa.ResourceManager().close()
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
    qapp.setStyle("Windows")

    while not valid_config():
        configdialog = ConfigFileDialog()
        if configdialog.exec() != QtWidgets.QDialog.Accepted:
            break
    else:
        win = MainWindow()
        win.show()
        win.activateWindow()
        qapp.exec()
