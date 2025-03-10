import configparser
import contextlib
import csv
import datetime
import json
import multiprocessing
import os
import sys
import time
from multiprocessing import shared_memory

import numpy as np
import pymodbus
import pyqtgraph as pg
from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from qtpy import QtCore, QtGui, QtWidgets, uic

import mg15

with contextlib.suppress(Exception):
    os.chdir(sys._MEIPASS)


MBAR_TO_TORR: float = 76000 / 101325


class LoggingProc(multiprocessing.Process):
    """A process for logging data to CSV files.

    Queues log entries and writes them to CSV files in the background. When the file is
    unaccessible, the process will wait until the file is unlocked and then write the
    log entry. If the process is stopped before all entries are written to the file, any
    remaining log entries will be printed to stdout.

    Parameters
    ----------
    log_dir
        The directory where the log files will be stored.

    Attributes
    ----------
    log_dir : str or os.PathLike
        The directory where the log files will be stored.
    queue : multiprocessing.Queue
        A queue to store the log messages.

    """

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

            # Retrieve message from queue
            dt, msg = self.queue.get()
            try:
                with open(
                    os.path.join(self.log_dir, dt.strftime("%y%m%d") + ".csv"),
                    "a",
                    newline="",
                ) as f:
                    writer = csv.writer(f)
                    writer.writerow([dt.isoformat(), *msg])
            except (PermissionError, FileNotFoundError):
                # Put back the retrieved message in the queue
                n_left = int(self.queue.qsize())
                self.queue.put((dt, msg))
                for _ in range(n_left):
                    self.queue.put(self.queue.get())
                continue

    def stop(self):
        """Stop the logging process and print any remaining log entries."""
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
        """Append a log entry to the queue."""
        if isinstance(content, str):
            content = [content]
        self.queue.put((timestamp, content))


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


class PlottingWidget(*uic.loadUiType("plotting.ui")):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.plotItem.showGrid(x=True, y=True, alpha=1.0)
        self.plots = (
            pg.PlotDataItem(pen="c"),
            pg.PlotDataItem(pen="m"),
            pg.PlotDataItem(pen="y"),
        )
        for plot in self.plots:
            self.plotItem.addItem(plot)
        self.plotItem.setAxisItems({"bottom": pg.DateAxisItem()})

    def set_data(
        self,
        x: list[datetime.datetime],
        ylist: list[list[float]],
    ):
        if isinstance(self.plotItem.getAxis("bottom"), pg.DateAxisItem):
            if self.relative_check.isChecked():
                self.plotItem.setAxisItems({"bottom": pg.AxisItem("bottom")})
        elif not self.relative_check.isChecked():
            self.plotItem.setAxisItems({"bottom": pg.DateAxisItem()})

        if self.relative_check.isChecked():
            t0 = x[0]
            xval: list[float] = [(t - t0).total_seconds() for t in x]
        else:
            xval: list[float] = [t.timestamp() for t in x]

        for plot, yval in zip(self.plots, ylist, strict=True):
            plot.setData(xval, yval)

    def clear(self):
        for plot in self.plots:
            plot.setData()

    @property
    def plotItem(self) -> pg.PlotItem:
        return self.plotwidget.plotItem


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("MG15")
        self.resize(400, 400)

        # Read config file
        self.config = configparser.ConfigParser()
        self.config.read(QtCore.QSettings("erlab", "mg15").value("config_file"))

        # Get parameters from config file
        self.main_gauges: list[int] = json.loads(
            self.config.get("Python", "Main Gauges", fallback="[1, 2, 4]")
        )[:3]
        self.channel_names: list[str] = [
            self.config.get("Section 2", f"MG15 CH{i + 1} Name")[1:-1] for i in range(7)
        ]
        self.disp_units: str = (
            self.config.get("Python", "Display Units", fallback="torr").strip().lower()
        )
        self.log_units: str = (
            self.config.get("Python", "Logging Units", fallback="torr").strip().lower()
        )
        log_dir: str = self.config.get("Python", "Logging Directory")
        log_interval: float = self.config.getfloat(
            "Python", "Logging Interval (s)", fallback=10.0
        )
        address: str = self.config["Section 1"]["MG15 Path"][1:-1]

        # Setup frontend docks
        area = DockArea()
        self.setCentralWidget(area)
        d1 = Dock(f"Pressures ({self.disp_units})", size=(500, 400))
        d2 = Dock("Plot", size=(500, 400))
        area.addDock(d2, "left")
        area.addDock(d1, "above", d2)

        # Setup frontend widgets
        self.pressure_widget = PressuresWidget()
        for i, idx in enumerate(self.main_gauges):
            self.pressure_widget.set_label(i, self.channel_names[idx - 1])
        d1.addWidget(self.pressure_widget)
        self.plotting = PlottingWidget()
        self.plotting.interval_spin.setValue(log_interval)
        self.plotting.interval_spin.valueChanged.connect(self.set_logging_interval)
        self.plotting.plotItem.getAxis("left").setLabel(f"Pressure ({self.log_units})")
        self.plotting.plotItem.getAxis("left").enableAutoSIPrefix(False)
        self.plotting.clear_btn.clicked.connect(self.clear_plot)
        d2.addWidget(self.plotting)

        # Setup data array
        self.time_list: list[datetime.datetime] = []
        self.pressure_list: list[list[float]] = []

        # Shared memory for access by other processes
        # Will be created on initial data update
        self.shm: shared_memory.SharedMemory | None = None

        # Connect to MG15
        self.mg15 = mg15.MG15(address)
        self.mg15.sigUpdated.connect(self.update_values)
        self.mg15.connect()

        # Setup log writing process
        self.log_writer = LoggingProc(log_dir)
        self.log_writer.start()

        # Setup logging timer
        self.log_timer = QtCore.QTimer(self)
        self.set_logging_interval(log_interval, update_config=False)
        self.log_timer.timeout.connect(self.write_log)
        self.toggle_updates(True)

    @QtCore.Slot(bool)
    def toggle_updates(self, value: bool):
        if value:
            self.log_timer.start()
        else:
            self.log_timer.stop()

    @QtCore.Slot()
    def clear_plot(self):
        self.time_list: list[datetime.datetime] = []
        self.pressure_list: list[list[float]] = []
        self.plotting.clear()

    @QtCore.Slot()
    def write_log(self):
        updated: datetime.datetime = self.mg15.updated
        pressures: list[float] = self.mg15.pressures(self.log_units)
        self.log_writer.append(updated, pressures)

        # Setup plotting
        self.time_list.append(updated)
        main_gauge_pressures = []
        for ch in self.main_gauges:
            if self.mg15.get_state(ch) == mg15.GAUGE_STATE[0]:
                main_gauge_pressures.append(pressures[ch - 1])
            else:
                main_gauge_pressures.append(np.nan)
        self.pressure_list.append(main_gauge_pressures)
        self.plotting.set_data(
            self.time_list, [list(i) for i in zip(*self.pressure_list, strict=False)]
        )

    @QtCore.Slot(float)
    def set_logging_interval(self, value: float, update_config: bool = True):
        self.log_timer.setInterval(round(value * 1000))
        if update_config:
            self.config.set("Python", "Logging Interval (s)", str(value))
            with open(QtCore.QSettings("erlab", "mg15").value("config_file"), "w") as f:
                self.config.write(f)

    @QtCore.Slot()
    def update_values(self):
        if self.shm is None:
            # Create shared memory on first update
            self.shm = shared_memory.SharedMemory(
                name="Pressures", create=True, size=4 * len(self.main_gauges)
            )

        arr = np.ndarray((len(self.main_gauges),), dtype="f4", buffer=self.shm.buf)

        for i, ch in enumerate(self.main_gauges):
            # Format & display pressure
            status: str = self.mg15.get_state(ch)
            if status == mg15.GAUGE_STATE[0]:
                value = (
                    np.format_float_scientific(
                        self.mg15.get_pressure(ch, self.disp_units), 3
                    )
                    .replace("e", "E")
                    .replace("-", "−")
                )
                arr[i] = np.float32(self.mg15.get_pressure(ch, self.log_units))
            else:
                arr[i] = np.float32(np.nan)
                value = status
            self.pressure_widget.set_value(i, value)

    def closeEvent(self, *args, **kwargs):
        # Log NaNs to signal end of data acquisition
        self.log_writer.append(
            datetime.datetime.now(), [np.nan] * len(self.mg15.pressures(self.log_units))
        )

        # Halt data acquisition
        self.mg15.disconnect()

        # Free shared memory
        self.shm.close()
        self.shm.unlink()

        # Stop logging process
        self.log_writer.stop()

        return super().closeEvent(*args, **kwargs)


class ConfigFileDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Choose config.ini file")
        self.setLayout(QtWidgets.QVBoxLayout())
        self.buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        box = QtWidgets.QWidget()
        box.setLayout(QtWidgets.QHBoxLayout())
        box.layout().setContentsMargins(0, 0, 0, 0)
        self.line = QtWidgets.QLineEdit()
        button = QtWidgets.QPushButton("Choose File")
        button.clicked.connect(self.choose_file)
        box.layout().addWidget(self.line)
        box.layout().addWidget(button)
        self.layout().addWidget(box)
        self.layout().addWidget(self.buttonBox)

    def accept(self):
        if valid_config(self.line.text()):
            QtCore.QSettings("erlab", "mg15").setValue("config_file", self.line.text())
        else:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Config File",
                "An error occurred while parsing the file.",
            )
        super().accept()

    def choose_file(self):
        dialog = QtWidgets.QFileDialog(self)
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptOpen)
        dialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilter("Configuration file (*.ini)")

        if dialog.exec():
            self.line.setText(dialog.selectedFiles()[0])


def valid_config(filename: str | None = None) -> bool:
    """Return True if a valid config file has been added, False otherwise."""
    if filename is None:
        filename = QtCore.QSettings("erlab", "mg15").value("config_file", "")
    config = configparser.ConfigParser()
    try:
        return len(config.read(filename)) != 0
    except configparser.ParsingError:
        return False


if __name__ == "__main__":
    multiprocessing.freeze_support()

    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    qapp.setWindowIcon(QtGui.QIcon("./icon.ico"))

    while not valid_config():
        configdialog = ConfigFileDialog()
        if configdialog.exec() != QtWidgets.QDialog.Accepted:
            break
    else:
        win = MainWindow()
        win.show()
        win.activateWindow()
        qapp.exec()
