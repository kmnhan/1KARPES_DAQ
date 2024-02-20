import datetime
import os
import sys
import time

import numpy as np
import pandas as pd
import pyqtgraph as pg
import tomlkit
from qtpy import QtCore, QtGui, QtWidgets, uic

from logreader import get_cryocooler_log, get_pressure_log
from qt_extensions.legendtable import LegendTableView
from qt_extensions.plotting import (
    DynamicPlotItem,
    DynamicPlotItemTwiny,
    XDateSnapCurvePlotDataItem,
)

try:
    os.chdir(sys._MEIPASS)
except:
    pass


class PressureSnapCurvePlotDataItem(XDateSnapCurvePlotDataItem):

    @staticmethod
    def format_y(y: float) -> str:
        return f"{y:.3g}"


class MainWindowGUI(*uic.loadUiType("logviewer.ui")):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.setWindowTitle("1KARPES Log Viewer")

        self.plot0 = DynamicPlotItemTwiny(
            legendtableview=self.legendtable,
            plot_cls=XDateSnapCurvePlotDataItem,
        )
        self.graphics_layout.addItem(self.plot0, 0, 0)
        self.plot0.setup_twiny()
        self.plot0.setAxisItems({"bottom": pg.DateAxisItem()})
        self.plot0.getAxis("left").setLabel("Temperature")
        self.plot0.getAxis("right").setLabel("Pump & Shields")

        self.plot1 = DynamicPlotItem(
            legendtableview=LegendTableView(),
            plot_cls=PressureSnapCurvePlotDataItem,
        )
        self.graphics_layout.addItem(self.plot1, 1, 0)
        self.plot1.setAxisItems({"bottom": pg.DateAxisItem()})

        self.plot1.setXLink(self.plot0)

        self.plot0.vline.sigPositionChanged.connect(self.sync_cursors)
        self.plot1.vline.sigPositionChanged.connect(self.sync_cursors)

        for pi in self.plot_items:
            pi.vb.setCursor(QtGui.QCursor(QtCore.Qt.CrossCursor))
            pi.scene().sigMouseMoved.connect(self.mouse_moved)
            pi.setDefaultPadding(0)
            pi.showGrid(x=True, y=True, alpha=1.0)
        self.plot1.setLogMode(False, True)

        self.startdateedit.dateTimeChanged.connect(self.enddateedit.setMinimumDateTime)
        self.startdateedit.setDate(QtCore.QDate.currentDate())
        self.startdateedit.setSelectedSection(QtWidgets.QDateTimeEdit.DaySection)

        self.enddateedit.dateTimeChanged.connect(self.startdateedit.setMaximumDateTime)
        self.enddateedit.setDateTime(QtCore.QDateTime.currentDateTime())
        self.enddateedit.setSelectedSection(QtWidgets.QDateTimeEdit.DaySection)

        self.actioncentercursor.triggered.connect(self.plot0.center_cursor)
        self.actionshowcursor.toggled.connect(self.plot0.toggle_cursor)
        self.actionshowcursor.toggled.connect(self.plot1.toggle_cursor)
        self.actionsnap.toggled.connect(self.plot0.toggle_snap)
        self.actionsnap.toggled.connect(self.plot1.toggle_snap)

    def sync_cursors(self, line: pg.InfiniteLine):
        if line == self.plot0.vline:
            self.plot1.vline.blockSignals(True)
            self.plot1.vline.setPos([line.getXPos(), 0])
            self.plot1.vline.blockSignals(False)
        else:
            self.plot0.vline.blockSignals(True)
            self.plot0.vline.setPos([line.getXPos(), 0])
            self.plot0.vline.blockSignals(False)

    @property
    def plot_items(self) -> tuple[pg.PlotItem, pg.PlotItem]:
        return self.plot0, self.plot1

    def mouse_moved(self, pos):
        if self.plot_items[0].sceneBoundingRect().contains(pos):
            index = 0
        elif self.plot_items[1].sceneBoundingRect().contains(pos):
            index = 1
        else:
            self.statusBar().clearMessage()
            return
        point = self.plot_items[index].vb.mapSceneToView(pos)
        try:
            dt = datetime.datetime.fromtimestamp(point.x())
        except OSError:
            return
        yval = point.y()
        if self.plot_items[index].ctrl.logYCheck.isChecked():
            yval = 10**yval
        self.statusBar().showMessage(
            f"{dt.strftime('%Y-%m-%d %H:%M:%S')}     {yval:.6g}"
        )


class MainWindow(MainWindowGUI):
    def __init__(self):
        super().__init__()
        self.settings = QtCore.QSettings("erlab", "1karpes_logviewer")

        self.load_btn.clicked.connect(self.load_data)
        self.pressure_check.toggled.connect(self.toggle_pressure)
        self.temperature_check.toggled.connect(self.toggle_temperature)
        self.updatetime_check.toggled.connect(self.toggle_updates)

        self.df: pd.DataFrame | None = None
        self.df_mg15: pd.DataFrame | None = None

        self.plot1.setVisible(False)
        self.plot1.set_labels(["Main", "Middle"])
        self.plot1.set_color(0, QtGui.QColor("cyan"))
        self.plot1.set_color(1, QtGui.QColor("magenta"))

        self.legendtable.model().sigCurveToggled.connect(self.curve_toggled)

        # setup timer
        self.update_timer = QtCore.QTimer(self)
        self.update_timer.setInterval(round(self.updatetime_spin.value() * 1000))
        self.update_timer.timeout.connect(self.update_time)
        self.updatetime_spin.valueChanged.connect(
            lambda val: self.update_timer.setInterval(round(val * 1000))
        )
        self.actiononlymain.toggled.connect(self.update_plot)
        try:
            self.load_data()
        except ValueError:
            pass

    @QtCore.Slot()
    def curve_toggled(self):
        if self.df is not None:
            self.settings.setValue(
                "enabled_names", list(self.df.columns[self.legendtable.enabled])
            )

    @QtCore.Slot(bool)
    def toggle_updates(self, value: bool):
        if value:
            self.update_timer.start()
        else:
            self.update_timer.stop()

    @QtCore.Slot()
    def update_time(self):
        self.enddateedit.setDateTime(QtCore.QDateTime.currentDateTime())
        self.load_data()

    @QtCore.Slot()
    def load_data(self, *, update: bool = True):
        self.df = get_cryocooler_log(self.start_datetime, self.end_datetime)
        if self.df is not None:
            self.plot0.set_labels(self.df.columns)

            with open(
                QtCore.QSettings("erlab", "tempcontroller").value("config_file"), "r"
            ) as f:
                plot_config = tomlkit.load(f)["plotting"]
            self.plot0.set_twiny_labels(plot_config["secondary_axes"])

            colors = [QtGui.QColor.fromRgb(*c) for c in plot_config["colors"]]
            colors += [
                QtGui.QColor.fromRgb(*list(c)[:3], 200) for c in plot_config["colors"]
            ]
            colors += 6 * [QtGui.QColor("white")]

            enabled = self.settings.value("enabled_names", [])
            for i, col in enumerate(self.df.columns):
                self.plot0.set_enabled(i, col in enabled)
                self.plot0.set_color(i, colors[i])

        self.df_mg15 = get_pressure_log(self.start_datetime, self.end_datetime)

        if update:
            self.update_plot()

    @QtCore.Slot(bool)
    def toggle_pressure(self, value: bool):
        self.plot1.setVisible(value)
        if value:
            self.update_plot()

    @QtCore.Slot(bool)
    def toggle_temperature(self, value: bool):
        self.plot0.setVisible(value)

    @QtCore.Slot()
    def update_plot(self):
        if self.df is not None:
            for i in range(len(self.df.columns)):
                self.plot0.set_data(
                    i,
                    self.df.index.values.astype(np.float64) * 1e-9,
                    self.df[self.df.columns[i]].values,
                )

        if self.pressure_check.isChecked():
            for i in range(1, 2):
                self.plot1.legendtable.set_enabled(
                    i, not self.actiononlymain.isChecked()
                )
            if self.df_mg15 is not None:
                for i in range(2):
                    self.plot1.set_data(
                        i,
                        self.df_mg15.index.values.astype(np.float64) * 1e-9,
                        self.df_mg15[self.df_mg15.columns[i]].values,
                    )

    @property
    def start_datetime_timestamp(self) -> float:
        return 1e-3 * self.startdateedit.dateTime().toMSecsSinceEpoch()

    @property
    def end_datetime_timestamp(self) -> float:
        return 1e-3 * self.enddateedit.dateTime().toMSecsSinceEpoch()

    @property
    def start_datetime(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.start_datetime_timestamp)

    @property
    def end_datetime(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.end_datetime_timestamp)

    def closeEvent(self, *args, **kwargs):
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    qapp.setWindowIcon(QtGui.QIcon("./images/logviewer.ico"))
    win = MainWindow()
    win.show()
    win.activateWindow()

    qapp.exec()
