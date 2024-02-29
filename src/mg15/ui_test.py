import configparser
import csv
import datetime
import json
import multiprocessing
import os
import sys
import time

import numpy as np
import pymodbus
import pyqtgraph as pg
from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from qtpy import QtCore, QtGui, QtWidgets, uic

import mg15

class PressuresWidget(*uic.loadUiType("pressures.ui")):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

    def set_label(self, index: int, label: str):
        self.groups[index].setTitle(label)

    def set_value(self, index: int, value: str):
        self.labels[index].setText(value)

    @property
    def groups(self) -> tuple[QtWidgets.QGroupBox, ...]:
        return self.group1, self.group2, self.group3

    @property
    def labels(self) -> tuple[QtWidgets.QLabel, ...]:
        return self.label1, self.label2, self.label3

if __name__ == "__main__":
    multiprocessing.freeze_support()

    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Windows")
    qapp.setWindowIcon(QtGui.QIcon("./icon.ico"))

    win = PressuresWidget()
    
    def parse_value(val):
        return (
                    np.format_float_scientific(val, 3)
                    .replace("e", "E")
                    .replace("-", "−")
                )
    win.set_value(0, mg15.GAUGE_STATE[19])
    win.set_value(1, parse_value(1.983534e-9))
    win.set_value(2, parse_value(2.1315352e-11))
    win.show()
    win.activateWindow()
    qapp.exec()
