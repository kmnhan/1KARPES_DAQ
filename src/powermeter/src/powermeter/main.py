import csv
import datetime
import multiprocessing
import os
import sys
import time

from qtpy import QtCore, QtGui, QtWidgets, uic

from powermeter.connection import VISAThread
from powermeter.widgets import CommandWidget

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

        self._command_widget: CommandWidget = CommandWidget()
        self.actioncommand.triggered.connect(self.show_command_widget)

        self._recent_power: float | None = None
        self._recent_dt: datetime.datetime | None = None

        # Setup logging
        self.logwriter = LoggingProc(LOG_DIR)
        self.logwriter.start()

        self.log_timer = QtCore.QTimer(self)
        self.set_logging_interval(10.0)
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
        self._recent_power = float(message) * 1e6  # power in μW
        self._recent_dt = dt

        self.power_label.setText(f"{self._recent_power:.4f} μW")

    @QtCore.Slot()
    def write_log(self) -> None:
        """Write the power value to the log file."""
        if self._recent_power is not None and self._recent_dt is not None:
            self.logwriter.append(self._recent_dt, [self._recent_power])


class MainWindow(MainWindowGUI):
    sigPowerRead = QtCore.Signal(str, object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.instr: VISAThread = VISAThread(
            "USB0::0x1313::0x8078::P0033832::INSTR", interval_ms=0
        )
        self._command_widget.instrument = self.instr

        # Auto range
        self.instr.request_write("SENS:RANGE:AUTO ON")

        # CW mode
        self.instr.request_write("SENS:FREQ:MODE CW")

        # Set wavelength to 206 nm
        self.instr.write("SENS:CORR:WAV 206")

        self.sigPowerRead.connect(self.update_power)

        self.fetch_timer = QtCore.QTimer(self)
        self.fetch_timer.timeout.connect(self.fetch_power)
        self.fetch_timer.setInterval(100)  # 100 ms
        self.fetch_timer.start()

        self.log_timer.start()

    @QtCore.Slot()
    def fetch_power(self) -> None:
        self.instr.request_query("MEAS:POW?", self.sigPowerRead)


if __name__ == "__main__":
    multiprocessing.freeze_support()

    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")

    win = MainWindow()
    # win = MainWindowGUI()
    win.show()
    win.activateWindow()
    qapp.exec()
