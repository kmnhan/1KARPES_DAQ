import collections
import csv
import datetime
import itertools
import logging
import multiprocessing
import os
import sys
import time
from multiprocessing import shared_memory

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets, uic

from powermeter.connection import VISAThread
from powermeter.widgets import CommandWidget

logging.addLevelName(5, "TRACE")
logging.TRACE = 5

log = logging.getLogger("powermeter")

log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)


LOG_DIR = "D:/Logs/Power"


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


class MainWindowGUI(
    *uic.loadUiType(os.path.join(os.path.dirname(__file__), "main.ui"))
):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setupUi(self)
        self.plot_live.plotItem.setAxisItems({"bottom": pg.DateAxisItem()})
        self._plot_live_data = pg.PlotDataItem()
        self.plot_live.addItem(self._plot_live_data)

        self.plot_log.plotItem.setAxisItems({"bottom": pg.DateAxisItem()})
        self._plot_log_data = pg.PlotDataItem()
        self.plot_log.addItem(self._plot_log_data)

        self.shm: shared_memory.SharedMemory | None = None

        self._command_widget: CommandWidget = CommandWidget()
        self.actioncommand.triggered.connect(self.show_command_widget)

        # Live plot data (not logged) - about 1 hour
        self._recorded_times: collections.deque = collections.deque(maxlen=36000)
        self._recorded_values: collections.deque = collections.deque(maxlen=36000)

        # Plotted data (logged)
        self._plot_times: list[float] = []
        self._plot_values: list[float] = []
        self.clear_btn.clicked.connect(self.clear_plot)

        # Setup logging
        self.logwriter = LoggingProc(LOG_DIR)
        self.logwriter.start()

        self.log_timer = QtCore.QTimer(self)
        self.set_logging_interval(5.0)
        self.interval_spin.valueChanged.connect(self.set_logging_interval)
        self.log_timer.timeout.connect(self.write_log)

    @QtCore.Slot(float)
    def set_logging_interval(self, interval: float) -> None:
        """Set the logging interval in seconds."""
        self.log_timer.setInterval(round(interval * 1000))

    @QtCore.Slot()
    def show_command_widget(self) -> None:
        rect = self.geometry()
        self._command_widget.setGeometry(rect.x() + rect.width(), rect.y(), 250, 200)
        self._command_widget.show()
        self._command_widget.activateWindow()

    @QtCore.Slot(str, object)
    def update_power(self, message: str, dt: datetime.datetime) -> None:
        """Set the power value in the GUI."""
        power = float(message) * 1e6  # power in μW

        self._recorded_times.append(dt.timestamp())
        self._recorded_values.append(power)

        self.power_label.setText(
            f"{np.format_float_positional(power, precision=4)} μW".replace("-", "−")
        )
        threshold = 0.01
        if power < threshold:
            self.power_label.setStyleSheet("color: red;")
        else:
            self.power_label.setStyleSheet("")

        if self.shm is None:
            # Create shared memory on first update
            self.shm = shared_memory.SharedMemory(
                name="laser_power", create=True, size=8
            )
            log.debug("Shared memory created")

        # Write the power value to shared memory
        np.ndarray((1,), "f8", self.shm.buf)[0] = float(power)

        # Update plot
        self._plot_live_data.setData(self._recorded_times, self._recorded_values)

    @QtCore.Slot()
    def write_log(self) -> None:
        """Write the power value to the log file."""
        if self._recorded_times and self._recorded_values:
            dt: float = self._recorded_times[-1]
            val: float = self._recorded_values[-1]
            self.logwriter.append(datetime.datetime.fromtimestamp(dt), [val])
            self._plot_times.append(dt)
            self._plot_values.append(val)
            self.update_plot()

    @QtCore.Slot()
    def update_plot(self) -> None:
        """Update logged plot data with the latest values."""
        if self._plot_times and self._plot_values:
            self._plot_log_data.setData(self._plot_times, self._plot_values)

    @QtCore.Slot()
    def clear_plot(self) -> None:
        """Clear the logged plot."""
        self._plot_times = []
        self._plot_values = []
        self._plot_log_data.setData()

    def closeEvent(self, event: QtGui.QCloseEvent):
        self._command_widget.close()

        self.logwriter.stop()
        log.info("Logging process stopped")

        # Free shared memory
        self.shm.close()
        self.shm.unlink()
        log.debug("Shared memory unlinked")

        super().closeEvent(event)


class MainWindow(MainWindowGUI):
    sigPowerRead = QtCore.Signal(str, object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.instr: VISAThread = VISAThread(
            "USB0::4883::32888::P0033832::0::INSTR", interval_ms=0
        )
        self.start_threads()

        self._command_widget.instrument = self.instr

        # Auto range
        # self.instr.request_write("SENS:RANG:AUTO ON")
        self.instr.request_write("SENS:POW:RANG MIN")

        # Enable analog filter (limits bandwidth to ~3 Hz)
        self.instr.request_write("INP:PDI:FILT:LPAS:STAT 1")

        # CW mode
        self.instr.request_write("SENS:FREQ:MODE CW")

        # Set averaging to 100 (once every 100 ms)
        self.instr.request_write("SENS:AVER:COUN 100")

        # Set wavelength to 206 nm
        self.instr.request_write("SENS:CORR:WAV 206")

        self.sigPowerRead.connect(self.update_power)

        # Set up the signal to refresh the power value
        self.fetch_timer = QtCore.QTimer(self)
        self.fetch_timer.timeout.connect(self.fetch_power)
        self.fetch_timer.setInterval(100)
        self.fetch_timer.start()

        self.log_timer.start()

        self.actionzero.triggered.connect(self.correct_zero)
        self.actionref.triggered.connect(self.set_reference)

    @QtCore.Slot()
    def fetch_power(self) -> None:
        self.instr.request_query("MEAS:POW?", self.sigPowerRead, loglevel=logging.TRACE)

    @QtCore.Slot()
    def correct_zero(self) -> None:
        """Correct the zero point of the power meter."""
        self.fetch_timer.stop()
        self.instr.request_write("SENS:CORR:COLL:ZERO")
        while True:
            time.sleep(0.01)
            msg = self.instr.controller.query(
                "SENS:CORR:COLL:ZERO:STAT?", loglevel=logging.TRACE
            )
            if msg.strip() == "0":
                break
        self.fetch_timer.start()

    @QtCore.Slot()
    def set_reference(self) -> None:
        """Set the reference power value.

        Sets the offset of the power meter to the mean of the last 50 measurements.
        """
        if len(self._recorded_values) < 50:
            QtCore.QTimer.singleShot(1000, self.set_reference)
            return

        self.fetch_timer.stop()

        ref: float = (
            np.mean(list(itertools.islice(reversed(self._recorded_values), 50))) * 1e-6
        )

        if (
            self.instr.controller.query(
                "SENS:POW:REF:STAT?", loglevel=logging.DEBUG
            ).strip()
            == "1"
        ):
            # If the reference is already set, add the current reference to the new one
            ref = ref + float(
                self.instr.controller.query("SENS:POW:REF?", loglevel=logging.DEBUG)
            )

        if ref < 0:
            ref = 0.0

        self.instr.request_write(f"SENS:POW:REF {np.format_float_positional(ref)}")
        self.instr.request_write("SENS:POW:REF:STAT 1")

        self.fetch_timer.start()

    def start_threads(self):
        self.instr.start()
        # Wait until all threads are ready
        log.info("Starting measurement thread...")
        while any((self.instr.stopped.is_set(),)):
            time.sleep(1e-4)
        log.info("Measurement thread started")

    def stop_threads(self):
        log.info("Stopping measurement thread...")
        self.instr.stopped.set()
        self.instr.wait()
        log.info("Measurement thread stopped")

    def closeEvent(self, event: QtGui.QCloseEvent):
        self.stop_threads()

        super().closeEvent(event)


if __name__ == "__main__":
    multiprocessing.freeze_support()

    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")

    win = MainWindow()
    # win = MainWindowGUI()
    win.show()
    win.activateWindow()
    qapp.exec()
