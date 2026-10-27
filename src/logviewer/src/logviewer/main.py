import contextlib
import datetime
import os
import sys
from itertools import starmap
from typing import TYPE_CHECKING

import pyqtgraph as pg
import qtawesome as qta
from qt_extensions.dialogs import MessageDialog
from qt_extensions.legendtable import LegendTableView
from qt_extensions.plotting import (
    DynamicPlotItem,
    DynamicPlotItemTwiny,
    XDateSnapCurvePlotDataItem,
)
from qtpy import QtCore, QtGui, QtWidgets, uic

from logviewer._loading import LoadedLogs, LoadRequest, LogLoadTask
from logviewer.logreader import CRYO_DIR, MG15_DIR, LogLoader, log_index_to_unix_seconds

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


class MainWindowGUI(
    *uic.loadUiType(os.path.join(os.path.dirname(__file__), "logviewer.ui"))
):
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
        self._log_loader = LogLoader()
        self._active_task: LogLoadTask | None = None
        self._pending_request: LoadRequest | None = None
        self._request_id = 0
        self._closing = False

        self.concurrency_spin = QtWidgets.QSpinBox(self)
        self.concurrency_spin.setObjectName("concurrency_spin")
        self.concurrency_spin.setRange(0, 2**31 - 1)
        self.concurrency_spin.setSpecialValueText("Auto")
        self.concurrency_spin.setToolTip(
            "Maximum simultaneous file reads. Auto uses Python's executor default."
        )
        try:
            concurrency = int(self.settings.value("max_workers", 0))
        except (TypeError, ValueError):
            concurrency = 0
        self.concurrency_spin.setValue(concurrency)
        self.concurrency_spin.valueChanged.connect(
            lambda value: self.settings.setValue("max_workers", value)
        )
        self.formLayout.addRow("Parallel file reads", self.concurrency_spin)

        self.loading_label = QtWidgets.QLabel("Loading logs…", self)
        self.statusBar().addPermanentWidget(self.loading_label)
        self.loading_label.hide()

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
        else:
            self.update_timer.stop()

    @QtCore.Slot()
    def update_time(self) -> bool:
        self.enddateedit.setDateTime(QtCore.QDateTime.currentDateTime())
        return self.load_data()

    def _show_load_error(self):
        self.update_timer.stop()
        self.updatetime_check.setChecked(False)
        MessageDialog.critical(
            self,
            "Failed to Load Logs",
            "The selected logs could not be loaded.",
            informative_text=str(sys.exception()),
        )

    @QtCore.Slot()
    def load_data(self, *, update: bool = True) -> bool:
        """Request a background load, replacing any pending request."""
        if self._closing:
            return False
        self.update_timer.stop()
        self._request_id += 1
        if self.end_datetime < self.start_datetime:
            self._pending_request = None
            if self._active_task is not None:
                self._active_task.requestInterruption()
            self.updatetime_check.setChecked(False)
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Date Range",
                "The end date must be after the start date.",
            )
            return False

        try:
            request = LoadRequest(
                request_id=self._request_id,
                start=self.start_datetime,
                end=self.end_datetime,
                max_workers=self.concurrency_spin.value() or None,
                config_file=QtCore.QSettings("erlab", "tempcontrol").value(
                    "config_file", None
                ),
                update=update,
                cryo_dir=CRYO_DIR,
                pressure_dir=MG15_DIR,
            )
            if self._active_task is None:
                self._start_load(request)
            else:
                self._pending_request = request
                self._active_task.requestInterruption()
        except Exception:
            self._show_load_error()
            return False
        return True

    def _start_load(self, request: LoadRequest):
        task = LogLoadTask(self._log_loader, request, self)
        task.finished.connect(self._load_finished)
        self._active_task = task
        self.loading_label.setText("Loading logs…")
        self.loading_label.show()
        try:
            task.start()
        except Exception:
            self._active_task = None
            self.loading_label.hide()
            task.deleteLater()
            raise

    def _request_is_current(self, request: LoadRequest) -> bool:
        return (
            request.request_id == self._request_id
            and request.start == self.start_datetime
            and request.end == self.end_datetime
        )

    @QtCore.Slot()
    def _load_finished(self):
        task = self._active_task
        if task is None:
            return
        self._active_task = None
        try:
            if not self._closing and self._request_is_current(task.request):
                self._apply_result(task.result_or_raise(), update=task.request.update)
        except Exception:
            self._show_load_error()
        finally:
            task.result = None
            task.error = None
            task.deleteLater()

        if self._closing:
            self._pending_request = None
            self.close()
            return
        pending, self._pending_request = self._pending_request, None
        if pending is not None and self._request_is_current(pending):
            try:
                self._start_load(pending)
            except Exception:
                self._show_load_error()
        if self._active_task is None:
            self.loading_label.hide()
            if self.updatetime_check.isChecked():
                self.update_timer.start()

    def _apply_result(self, result: LoadedLogs, *, update: bool):
        df, df_mg15 = result.df, result.df_mg15

        if df is not None:
            plot_config = result.plot_config
            if plot_config is None:
                raise ValueError("The temperature plotting configuration is missing.")
            secondary_axes = list(plot_config["secondary_axes"])
            colors = list(starmap(QtGui.QColor.fromRgb, plot_config["colors"]))
            colors += [
                QtGui.QColor.fromRgb(*list(c)[:3], 200) for c in plot_config["colors"]
            ]
            required_colors = len(df.columns) - len(colors)
            colors += required_colors * [QtGui.QColor("white")]

            enabled = self.settings.value("enabled_names", [])

        # Keep the data and legend in sync even if plotting the new data fails.
        # Reader and configuration errors above leave the previous data intact.
        self.df, self.df_mg15 = df, df_mg15
        if df is not None:
            self.plot0.set_labels(df.columns)
            self.plot0.set_twiny_labels(secondary_axes)
            for i, col in enumerate(df.columns):
                self.plot0.set_enabled(i, col in enabled)
                self.plot0.set_color(i, colors[i])

        if update:
            self._update_plot()

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
        try:
            self._update_plot()
        except Exception:
            self._show_load_error()

    def _update_plot(self):
        for item, frame in ((self.plot0, self.df), (self.plot1, self.df_mg15)):
            if frame is None:
                for plot in item.plots:
                    plot.clear()
                    plot.curve.target.hide()
                item.update_cursor_label()
        if self.df is not None:
            self.plot0.set_datalist(
                log_index_to_unix_seconds(self.df.index),
                self.df.values.T,
            )
        if self.pressure_check.isChecked():
            for i in range(1, 2):
                self.plot1.legendtable.set_enabled(
                    i, not self.actiononlymain.isChecked()
                )
            if self.df_mg15 is not None:
                self.plot1.set_datalist(
                    log_index_to_unix_seconds(self.df_mg15.index),
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

    def closeEvent(self, event: QtGui.QCloseEvent):
        self._closing = True
        self._pending_request = None
        self.update_timer.stop()
        self.updatetime_check.setChecked(False)
        if self._active_task is not None:
            self._active_task.requestInterruption()
            self.loading_label.setText("Finishing file reads…")
            self.setEnabled(False)
            event.ignore()
            return
        self._log_loader.clear_cache()
        super().closeEvent(event)


def main():
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        # Ignore if running in a PyInstaller bundle
        if sys.platform == "darwin":
            qapp.setWindowIcon(
                QtGui.QIcon(os.path.join(os.path.dirname(__file__), "icon.icns"))
            )
        else:
            qapp.setWindowIcon(
                QtGui.QIcon(os.path.join(os.path.dirname(__file__), "icon.ico"))
            )
    win = MainWindow()
    win.show()
    win.activateWindow()

    qapp.exec()
