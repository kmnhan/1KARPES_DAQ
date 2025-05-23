import contextlib
import datetime
import gc
import os
import sys
import time
from itertools import starmap
from typing import TYPE_CHECKING

import pyqtgraph as pg
import qtawesome as qta
import tomlkit
from logreader import CRYO_DIR, get_cryocooler_log, get_pressure_log
from qt_extensions.legendtable import LegendTableView
from qt_extensions.plotting import (
    DynamicPlotItem,
    DynamicPlotItemTwiny,
    XDateSnapCurvePlotDataItem,
)
from qtpy import QtCore, QtGui, QtWidgets, uic

if TYPE_CHECKING:
    import pandas as pd

with contextlib.suppress(Exception):
    os.chdir(sys._MEIPASS)


class PressureSnapCurvePlotDataItem(XDateSnapCurvePlotDataItem):
    @staticmethod
    def format_y(y: float) -> str:
        return f"{y:.3g}"


class BetterCalendarWidget(QtWidgets.QCalendarWidget):
    """A custom calendar widget with improved styling and navigation buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setStyleSheet(
            "QCalendarWidget QWidget#qt_calendar_navigationbar"
            " { background-color: #e0e0e0; }"
        )
        self.setGridVisible(True)

        prev_btn = self.findChild(QtWidgets.QToolButton, "qt_calendar_prevmonth")
        if prev_btn:
            prev_btn.setIcon(qta.icon("mdi6.arrow-left"))

        next_btn = self.findChild(QtWidgets.QToolButton, "qt_calendar_nextmonth")
        if next_btn:
            next_btn.setIcon(qta.icon("mdi6.arrow-right"))


class MainWindowGUI(*uic.loadUiType("logviewer.ui")):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.setWindowTitle("1KARPES Log Viewer")

        self.startdateedit.setCalendarWidget(BetterCalendarWidget())
        self.enddateedit.setCalendarWidget(BetterCalendarWidget())

        self.plot0 = DynamicPlotItemTwiny(
            legendtableview=self.legendtable,
            plot_cls=XDateSnapCurvePlotDataItem,
            plot_kw={"autoDownsample": True, "clipToView": True},
            pen_kw_twin={"width": 2, "style": QtCore.Qt.DashLine},
        )
        self.graphics_layout.addItem(self.plot0, 0, 0)
        self.plot0.setup_twiny()
        self.plot0.setAxisItems({"bottom": pg.DateAxisItem()})
        self.plot0.getAxis("left").setLabel("Temperature")
        self.plot0.getAxis("right").setLabel("Pump & Shields")

        self.plot1 = DynamicPlotItem(
            legendtableview=LegendTableView(),
            plot_cls=PressureSnapCurvePlotDataItem,
            plot_kw={"autoDownsample": True, "clipToView": True},
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

        # Set start to 00:00 today
        self.startdateedit.setDate(QtCore.QDate.currentDate())
        self.startdateedit.setSelectedSection(QtWidgets.QDateTimeEdit.DaySection)

        # Set start to current date and time
        self.enddateedit.setDateTime(QtCore.QDateTime.currentDateTime())
        self.enddateedit.setSelectedSection(QtWidgets.QDateTimeEdit.DaySection)

        self.actioncentercursor.triggered.connect(self.plot0.center_cursor)
        self.actionshowcursor.toggled.connect(self.plot0.vline.setVisible)
        self.actionshowcursor.toggled.connect(self.plot1.vline.setVisible)
        self.actionsnap.toggled.connect(self.plot0.toggle_snap)
        self.actionsnap.toggled.connect(self.plot1.toggle_snap)
        self.actionlog0.triggered.connect(lambda: self.plot0.toggle_logy(twin=False))
        self.actionlog1.triggered.connect(lambda: self.plot0.toggle_logy(twin=True))

    def sync_cursors(self, line: pg.InfiniteLine):
        if line == self.plot0.vline:
            self.plot1.vline.blockSignals(True)
            self.plot1.vline.setPos([line.getXPos(), 0])
            self.plot1.update_cursor_label()
            self.plot1.vline.blockSignals(False)
        else:
            self.plot0.vline.blockSignals(True)
            self.plot0.vline.setPos([line.getXPos(), 0])
            self.plot0.update_cursor_label()
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
        with contextlib.suppress(ValueError):
            self.load_data()

    @QtCore.Slot()
    def curve_toggled(self):
        if self.df is not None:
            self.settings.setValue(
                "enabled_names", list(self.df.columns[self.legendtable.enabled])
            )

    @QtCore.Slot(bool)
    def toggle_updates(self, value: bool):
        if value:
            self.update_time()
            self.update_timer.start()
        else:
            self.update_timer.stop()

    @QtCore.Slot()
    def update_time(self):
        self.enddateedit.setDateTime(QtCore.QDateTime.currentDateTime())
        self.load_data()
        gc.collect(generation=2)

    @QtCore.Slot()
    def load_data(self, *, update: bool = True):
        if self.end_datetime < self.start_datetime:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Date Range",
                "The end date must be after the start date.",
            )
            return

        self.df = get_cryocooler_log(self.start_datetime, self.end_datetime)
        if self.df is not None:
            self.plot0.set_labels(self.df.columns)

            config_file: str | None = QtCore.QSettings("erlab", "tempcontrol").value(
                "config_file", None
            )
            if config_file is None or not os.path.isfile(config_file):
                config_file = os.path.join(CRYO_DIR, "config.toml")
            with open(config_file) as f:
                plot_config = tomlkit.load(f)["plotting"]
            self.plot0.set_twiny_labels(plot_config["secondary_axes"])

            colors = list(starmap(QtGui.QColor.fromRgb, plot_config["colors"]))
            colors += [
                QtGui.QColor.fromRgb(*list(c)[:3], 200) for c in plot_config["colors"]
            ]
            colors += 10 * [QtGui.QColor("white")]

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
            self.plot0.set_datalist(
                self.df.index.values.astype(float) * 1e-9 + time.timezone,
                self.df.values.T,
            )
        if self.pressure_check.isChecked():
            for i in range(1, 2):
                self.plot1.legendtable.set_enabled(
                    i, not self.actiononlymain.isChecked()
                )
            if self.df_mg15 is not None:
                self.plot1.set_datalist(
                    self.df_mg15.index.values.astype(float) * 1e-9 + time.timezone,
                    self.df_mg15.values.T,
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
    if sys.platform == "darwin":
        qapp.setWindowIcon(QtGui.QIcon("./icon.icns"))
    else:
        qapp.setWindowIcon(QtGui.QIcon("./icon.ico"))
    win = MainWindow()
    win.show()
    win.activateWindow()

    qapp.exec()
