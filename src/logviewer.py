import datetime
import os
import sys

import numpy as np
import pyqtgraph as pg
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
            if self.df_mg15 is not None:
                for j, pen in enumerate((pg.mkPen("r"), pg.mkPen("b"))):
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
