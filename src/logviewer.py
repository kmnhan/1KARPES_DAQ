import datetime
import os
import sys
import time

import numpy as np
import pandas as pd
import pyqtgraph as pg

# os.environ["QT_API"] = "pyqt6"
from qtpy import QtCore, QtGui, QtWidgets, uic

from logreader import get_cryocooler_log, get_pressure_log
from qt_extensions.legendtable import LegendTableView

try:
    os.chdir(sys._MEIPASS)
except:
    pass


UTC_OFFSET: int = -time.timezone


class MainWindowGUI(*uic.loadUiType("logviewer.ui")):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.setWindowTitle("1KARPES Log Viewer")

        # add plot and image
        self.plot0: pg.PlotItem = self.graphics_layout.addPlot(
            0, 0, axisItems={"bottom": pg.DateAxisItem(utcOffset=UTC_OFFSET / 3600)}
        )
        self.plot1: pg.PlotItem = self.graphics_layout.addPlot(
            1, 0, axisItems={"bottom": pg.DateAxisItem(utcOffset=UTC_OFFSET / 3600)}
        )
        self.plot1.setXLink(self.plot0)
        self.plot0.getAxis("bottom").setStyle(showValues=False)
        self.plot0.setYRange(0, 300)

        self.line0 = pg.InfiniteLine(
            angle=90,
            movable=True,
            label="",
            labelOpts=dict(position=0.75, movable=True, fill=(200, 200, 200, 50)),
        )
        self.line0.sigPositionChanged.connect(self.sync_cursors)
        self.line0.setZValue(100)
        self.line1 = pg.InfiniteLine(
            angle=90,
            movable=True,
            label="",
            labelOpts=dict(position=0.75, movable=True, fill=(200, 200, 200, 50)),
        )
        self.line1.sigPositionChanged.connect(self.sync_cursors)

        self.plot0.addItem(self.line0)
        self.plot1.addItem(self.line1)

        for pi in self.plot_items:
            pi.vb.setCursor(QtGui.QCursor(QtCore.Qt.CrossCursor))
            pi.scene().sigMouseMoved.connect(self.mouse_moved)
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

        self.actionshowcursor.setChecked(True)
        self.actioncentercursor.triggered.connect(self.center_cursor)
        self.actionshowcursor.toggled.connect(self.toggle_cursor)

    def sync_cursors(self, line: pg.InfiniteLine):
        if line == self.line0:
            self.line1.blockSignals(True)
            self.line1.setPos([line.getXPos(), 0])
            self.line1.blockSignals(False)
        else:
            self.line0.blockSignals(True)
            self.line0.setPos([line.getXPos(), 0])
            self.line0.blockSignals(False)

    @property
    def plot_items(self) -> tuple[pg.PlotItem, pg.PlotItem]:
        return self.plot0, self.plot1

    @QtCore.Slot(bool)
    def toggle_cursor(self, value: bool):
        self.line0.setVisible(value)
        self.line1.setVisible(value)
        self.actioncentercursor.setDisabled(not value)

    @QtCore.Slot()
    def center_cursor(self):
        xmin, xmax = self.plot0.viewRange()[0]
        self.line0.setValue((xmin + xmax) / 2)

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
            dt = datetime.datetime.fromtimestamp(point.x() - UTC_OFFSET)
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
        self.legendtable.model().sigCurveToggled.connect(self.update_plot)
        self.legendtable.model().sigColorChanged.connect(self.update_plot)
        self.load_btn.clicked.connect(self.load_data)
        self.pressure_check.toggled.connect(self.toggle_pressure)
        self.temperature_check.toggled.connect(self.toggle_temperature)
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
        self.line0.sigPositionChanged.connect(self.update_cursor_label)
        self.line1.sigPositionChanged.connect(self.update_cursor_label)

        self.actiononlymain.toggled.connect(self.update_plot)

    @QtCore.Slot()
    def update_cursor_label(self):
        dt = datetime.datetime.fromtimestamp(self.line0.value() - UTC_OFFSET)
        if self.df is not None:
            row = self.df.iloc[self.df.index.get_indexer([dt], method="nearest")]
            label = row.index[0].strftime("%Y-%m-%d %H:%M:%S")
            for enabled, entry in zip(
                self.legendtable.enabled, self.legendtable.entries
            ):
                if enabled:
                    label += f"\n{entry}: {row[entry].iloc[0]:.3f}"
            self.line0.label.setText(label)
        if self.df_mg15 is not None:
            row = self.df_mg15.iloc[
                self.df_mg15.index.get_indexer([dt], method="nearest")
            ]
            label = row.index[0].strftime("%Y-%m-%d %H:%M:%S")
            entries = ["IG Main"]
            if not self.actiononlymain.isChecked():
                entries += ["IG Middle"]
            for entry in entries:
                label += f"\n{entry}: {row[entry].iloc[0]:.3g}"
            self.line1.label.setText(label)

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
        if self.df is not None:
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

    @QtCore.Slot(bool)
    def toggle_temperature(self, value: bool):
        self.plot0.setVisible(value)

    @QtCore.Slot()
    def update_plot(self):
        self.plot0.clearPlots()
        if self.df is not None:
            self.settings.setValue(
                "enabled_names", list(self.df.columns[self.legendtable.enabled])
            )
            for i, on in enumerate(self.legendtable.enabled):
                if on:
                    self.plot0.plot(
                        self.df.index.values.astype(np.float64) * 1e-9,
                        self.df[self.df.columns[i]].values,
                        pen=pg.mkPen(self.legendtable.colors[i]),
                        autoDownsample=True,
                    )
        if self.pressure_check.isChecked():
            self.plot1.clearPlots()
            if self.actiononlymain.isChecked():
                pens = (pg.mkPen("c"),)
            else:
                pens = (pg.mkPen("c"), pg.mkPen("m"))
            if self.df_mg15 is not None:
                for j, pen in enumerate(pens):
                    self.plot1.plot(
                        self.df_mg15.index.values.astype(np.float64) * 1e-9,
                        self.df_mg15[self.df_mg15.columns[j]].values,
                        pen=pen,
                        autoDownsample=True,
                    )

        for pi in self.plot_items:
            pi.getViewBox().setLimits(
                xMin=self.start_datetime_timestamp, xMax=self.end_datetime_timestamp
            )

    @property
    def start_datetime_timestamp(self) -> float:
        return 1e-3 * self.startdateedit.dateTime().toMSecsSinceEpoch() + UTC_OFFSET

    @property
    def end_datetime_timestamp(self) -> float:
        return 1e-3 * self.enddateedit.dateTime().toMSecsSinceEpoch() + UTC_OFFSET

    @property
    def start_datetime(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(
            self.start_datetime_timestamp - UTC_OFFSET
        )

    @property
    def end_datetime(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.end_datetime_timestamp - UTC_OFFSET)


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
