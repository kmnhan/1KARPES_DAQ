import datetime
import os
import sys

import numpy as np
import pandas as pd
import PyQt6
import pyqtgraph as pg
import seaborn as sns
from qtpy import QtCore, QtGui, QtWidgets, uic

from logreader import get_cryocooler_log, get_pressure_log

try:
    os.chdir(sys._MEIPASS)
except:
    pass


class MainWindowGUI(*uic.loadUiType("logviewer.ui")):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.setWindowTitle("1KARPES Log Viewer")

        # add plot and image
        self.plot0: pg.PlotItem = self.graphics_layout.addPlot(
            0, 0, axisItems={"bottom": pg.DateAxisItem(utcOffset=9.0)}
        )
        self.plot1: pg.PlotItem = self.graphics_layout.addPlot(
            1, 0, axisItems={"bottom": pg.DateAxisItem(utcOffset=9.0)}
        )
        self.plot1.setXLink(self.plot0)
        self.plot0.getAxis("bottom").setStyle(showValues=False)
        for pi in self.plot_items:
            pi.setDefaultPadding(0)
            pi.showGrid(x=True, y=True, alpha=1.0)
            pi.showAxes((True, False, False, True))
        self.plot1.setLogMode(False, True)

        self.startdateedit.dateTimeChanged.connect(self.enddateedit.setMinimumDateTime)
        self.startdateedit.setDate(QtCore.QDate.currentDate())
        self.startdateedit.setSelectedSection(QtWidgets.QDateTimeEdit.DaySection)

        self.enddateedit.dateTimeChanged.connect(self.startdateedit.setMaximumDateTime)
        self.enddateedit.setDateTime(QtCore.QDateTime.currentDateTime())
        self.enddateedit.setSelectedSection(QtWidgets.QDateTimeEdit.DaySection)

    @property
    def plot_items(self) -> tuple[pg.PlotItem, pg.PlotItem]:
        return self.plot0, self.plot1


class MainWindow(MainWindowGUI):
    def __init__(self):
        super().__init__()
        self.settings = QtCore.QSettings("erlab", "1karpes_logviewer")
        self.legendtable.model().sigCurveToggled.connect(self.update_plot)
        self.legendtable.model().sigColorChanged.connect(self.update_plot)
        self.load_btn.clicked.connect(self.load_data)
        self.pressure_check.toggled.connect(self.toggle_pressure)
        self.updatetime_check.toggled.connect(self.toggle_updates)

        self.df = None
        self.df_mg15 = None
        self.plot1.setVisible(False)

        try:
            self.load_data(update=False)
            enabled = self.settings.value("enabled_names", [])
            for i in range(self.legendtable.model().rowCount()):
                if self.df.columns[i] in enabled:
                    self.legendtable.set_enabled(i, True)
        except ValueError:
            pass

        # setup timer
        self.client_timer = QtCore.QTimer(self)
        self.client_timer.setInterval(round(self.updatetime_spin.value() * 1000))
        self.client_timer.timeout.connect(self.update_time)
        self.updatetime_spin.valueChanged.connect(
            lambda val: self.client_timer.setInterval(round(val * 1000))
        )

    @QtCore.Slot(bool)
    def toggle_updates(self, value: bool):
        if value:
            self.client_timer.start()
        else:
            self.client_timer.stop()

    @QtCore.Slot()
    def update_time(self):
        self.enddateedit.setDateTime(QtCore.QDateTime.currentDateTime())
        self.load_data()

    @QtCore.Slot()
    def load_data(self, *, update: bool = True):
        self.df = get_cryocooler_log(self.start_datetime, self.end_datetime)
        self.legendtable.set_items(self.df.columns)
        if self.pressure_check.isChecked():
            self.df_mg15 = get_pressure_log(self.start_datetime, self.end_datetime)
        if update:
            self.update_plot()

    @QtCore.Slot(bool)
    def toggle_pressure(self, value: bool):
        self.plot1.setVisible(value)
        if value:
            self.df_mg15 = get_pressure_log(self.start_datetime, self.end_datetime)
            self.update_plot()
        else:
            self.plot1.clearPlots()
            self.df_mg15 = None

    def update_plot(self):
        self.settings.setValue(
            "enabled_names", list(self.df.columns[self.legendtable.enabled])
        )
        self.plot0.clearPlots()

        for i, on in enumerate(self.legendtable.enabled):
            if on:
                self.plot0.plot(
                    self.df.index.values.astype(np.float64) * 1e-9,
                    self.df[self.df.columns[i]].values,
                    pen=pg.mkPen(self.legendtable.colors[i]),
                    autoDownsample=True,
                )

        if self.pressure_check.isChecked():
            self.plot1.plot(
                self.df_mg15.index.values.astype(np.float64) * 1e-9,
                self.df_mg15.values.flatten(),
                # pen=pg.mkPen(),
                autoDownsample=True,
            )

    @property
    def start_datetime(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(
            1e-3 * self.startdateedit.dateTime().toMSecsSinceEpoch()
        )

    @property
    def end_datetime(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(
            1e-3 * self.enddateedit.dateTime().toMSecsSinceEpoch()
        )


if __name__ == "__main__":
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)

    win = MainWindow()
    win.show()
    win.activateWindow()

    qapp.exec()
