import csv
import datetime
import logging
import multiprocessing
import os
import sys
import time

import pyvisa
import slack_sdk
import slack_sdk.errors
from f70h import F70H_ALARM_BITS, F70H_STATE, F70HInstrument
from qtpy import QtCore, QtGui, QtWidgets

try:
    os.chdir(sys._MEIPASS)
except:  # noqa: E722
    pass


F70_INST_NAME: str = "ASRL3::INSTR"
REFRESH_INTERVAL_MS: int = 1000

log = logging.getLogger("F70H")
log.setLevel(logging.INFO)
# handler = logging.StreamHandler(sys.stdout)

handler = logging.FileHandler(f"D:/daq_logs/{log.name}.log", mode="a", encoding="utf-8")
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)


client = slack_sdk.WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))


def send_message(message: str | list[str]):
    """Send a message to the slack channel."""
    if isinstance(message, list):
        message = "\n".join(message)
    try:
        _ = client.chat_postMessage(
            channel="C070N0MDBE2",
            text=message,
            mrkdwn=True,
        )
    except slack_sdk.errors.SlackApiError:
        log.exception("Error posting message")


class LoggingProc(multiprocessing.Process):
    def __init__(self):
        super().__init__()
        self.log_dir = "D:/Logs/Compressor"
        self._stopped = multiprocessing.Event()
        self.queue = multiprocessing.Manager().Queue()
        self._last_logged: datetime.datetime = datetime.datetime.now()
        self._content_old: tuple[int, int, int] = (0, 0, 0)

    def run(self):
        self._stopped.clear()

        while not self._stopped.is_set():
            time.sleep(0.02)

            if self.queue.empty():
                continue

            # Retrieve message from queue
            dt, values = self.queue.get()
            if values == self._content_old:
                continue
            try:
                with open(
                    os.path.join(self.log_dir, dt.strftime("%y%m%d") + ".csv"),
                    "a",
                    newline="",
                ) as f:
                    writer = csv.writer(f)
                    dt_prev = dt - datetime.timedelta(milliseconds=REFRESH_INTERVAL_MS)

                    # If there is a gap in logging, log the last value
                    if self._last_logged < dt_prev - datetime.timedelta(
                        milliseconds=REFRESH_INTERVAL_MS * 0.5
                    ):
                        writer.writerow([dt_prev, *[str(v) for v in self._content_old]])

                    writer.writerow([dt.isoformat(), *[str(v) for v in values]])

            except PermissionError:
                # Put back the retrieved message in the queue
                n_left = int(self.queue.qsize())
                self.queue.put((dt, values))
                for _ in range(n_left):
                    self.queue.put(self.queue.get())
                continue

            else:
                self._content_old = values
                self._last_logged = dt

    def stop(self):
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

    def append(self, timestamp: datetime.datetime, values: tuple[int, int, int]):
        self.queue.put((timestamp, values))


class UpdateThread(QtCore.QThread):
    sigUpdate = QtCore.Signal(str, object, int)

    def __init__(self, instrument: F70HInstrument, timeout: float = 50.0) -> None:
        super().__init__()
        self.instrument = instrument
        self.timeout = timeout * 1e-3

    def run(self):
        bits = self.instrument.status

        time.sleep(self.timeout)
        temps = self.instrument.temperature

        time.sleep(self.timeout)
        pressure = self.instrument.pressure

        self.sigUpdate.emit(bits, temps, pressure)


class QHLine(QtWidgets.QFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)


class F70GUI(QtWidgets.QMainWindow):
    ON_LABEL = "🔴"
    OFF_LABEL = "🟢"
    NEUTRAL_LABEL = "⚪"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("F70H Status")
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)

        layout = QtWidgets.QVBoxLayout(central_widget)
        central_widget.setLayout(layout)

        alarms_layout = QtWidgets.QGridLayout()
        self.alarm_status_labels: list[QtWidgets.QLabel] = []
        for k, v in F70H_ALARM_BITS.items():
            alarm_status_label = QtWidgets.QLabel(self.NEUTRAL_LABEL)
            alarm_status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            alarm_status_label.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Fixed
            )
            alarm_name_label = QtWidgets.QLabel(k)
            alarm_name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            alarms_layout.addWidget(alarm_status_label, v - 1, 0)
            alarms_layout.addWidget(alarm_name_label, v - 1, 1)
            self.alarm_status_labels.append(alarm_status_label)

        values_layout = QtWidgets.QGridLayout()

        values_layout.addWidget(QtWidgets.QLabel("He Discharge"), 0, 0)
        values_layout.addWidget(QtWidgets.QLabel("Water Out"), 1, 0)
        values_layout.addWidget(QtWidgets.QLabel("Water In"), 2, 0)
        values_layout.addWidget(QtWidgets.QLabel("Return Pressure"), 3, 0)
        self.labels = [
            QtWidgets.QLabel(),
            QtWidgets.QLabel(),
            QtWidgets.QLabel(),
            QtWidgets.QLabel(),
        ]
        for i, label in enumerate(self.labels):
            values_layout.addWidget(label, i, 1)

        buttons_layout = QtWidgets.QHBoxLayout()

        self.start_button = QtWidgets.QPushButton("START")
        self.start_button.setFixedHeight(50)
        self.start_button.setStyleSheet("background-color : green")

        self.stop_button = QtWidgets.QPushButton("STOP")
        self.stop_button.setFixedHeight(50)
        self.stop_button.setStyleSheet("background-color : red")

        self.reset_button = QtWidgets.QPushButton("RESET")
        self.reset_button.setFixedHeight(50)

        buttons_layout.addWidget(self.start_button)
        buttons_layout.addWidget(self.stop_button)

        layout.addLayout(alarms_layout)
        layout.addWidget(QHLine())
        layout.addLayout(values_layout)
        layout.addWidget(QHLine())
        layout.addLayout(buttons_layout)
        layout.addWidget(self.reset_button)


class MainWindow(F70GUI):
    def __init__(self):
        super().__init__()
        self.instr = F70HInstrument(F70_INST_NAME)

        self.start_button.clicked.connect(self.start_button_clicked)
        self.stop_button.clicked.connect(self.stop_button_clicked)
        self.reset_button.clicked.connect(self.reset_button_clicked)

        self.alarms_notified: set[str] = set()

        self.update_thread = UpdateThread(self.instr)
        self.update_thread.sigUpdate.connect(self.update_status)

        # Setup log writing process
        self.log_writer = LoggingProc()
        self.log_writer.start()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_INTERVAL_MS)

    @property
    def current_time_formatted(self) -> str:
        return datetime.datetime.now().isoformat(sep=" ", timespec="seconds")

    def start_button_clicked(self):
        if self.update_thread.isRunning():
            self.update_thread.wait()

        # Turn on compressor
        self.instr.turn_on()

        # Notify slack channel
        send_message(
            f":large_green_circle: {self.current_time_formatted} Compressor ON"
        )

    def stop_button_clicked(self):
        if self.update_thread.isRunning():
            self.update_thread.wait()

        # Turn off compressor
        self.instr.turn_off()

        # Notify slack channel
        send_message(f":red_circle: {self.current_time_formatted} Compressor OFF")

    def reset_button_clicked(self):
        if self.update_thread.isRunning():
            self.update_thread.wait()

        # Reset alarms
        self.instr.reset()

        # Clear alarms so that they can be notified again
        self.alarms_notified = []

    def refresh(self):
        if self.update_thread.isRunning():
            self.update_thread.wait()
        self.update_thread.start()

    def notify_alarm(
        self,
        alarms: list[str],
        status: str,
        temperature: tuple[int, int, int],
        pressure: int,
    ):
        if len(alarms) == 0:
            # Alarms cleared
            send_message(
                f":white_check_mark: {self.current_time_formatted} Alarms cleared"
            )
            return
        else:
            # Alarms raised
            send_message(
                [
                    f":warning: {self.current_time_formatted} Alarms raised:",
                    ", ".join(alarms),
                    status,
                    f"Temperatures {', '.join([f'{t}°C' for t in temperature])}",
                    f"Return pressure {pressure} psig",
                ]
            )

    @QtCore.Slot(str, object, int)
    def update_status(
        self, bits: str, temperature: tuple[int, int, int], pressure: int
    ):
        self.log_writer.append(datetime.datetime.now(), temperature)

        state = F70H_STATE[int(bits[4:7], 2)]

        if bits[-1] == "1":
            state_str = f"System On ({state})"
        elif bits[-1] == "0":
            state_str = f"System Off ({state})"
        self.statusBar().showMessage(state_str)

        alarms = []
        for k, v in F70H_ALARM_BITS.items():
            # Get corresponding indicator
            label = self.alarm_status_labels[v - 1]
            if int(bits[-v - 1]) == 1:
                # Alarm is active
                label.setText(self.ON_LABEL)
                log.critical(f"ALARM: {k}")
                # Add alarm to list
                alarms.append(k)
            else:
                # Alarm is inactive
                label.setText(self.OFF_LABEL)

        if set(alarms) != self.alarms_notified:
            # Notify only if alarms have changed
            self.notify_alarm(alarms, state_str, temperature, pressure)
            self.alarms_notified = set(alarms)

        # Update temperature and pressure labels
        for label, value in zip(self.labels[:3], temperature, strict=True):
            label.setText(f"{value} °C")
        self.labels[3].setText(f"{pressure} psig")

    def closeEvent(self, event):
        self.timer.stop()

        if self.update_thread.isRunning():
            self.update_thread.wait()

        self.instr.instrument.close()

        # Stop logging process
        self.log_writer.stop()

        super().closeEvent(event)


class PortDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Select Instrument")

        layout = QtWidgets.QVBoxLayout(self)
        self.setLayout(layout)

        self.port_combobox = QtWidgets.QComboBox()
        self.port_combobox.addItems(pyvisa.ResourceManager().list_resources())
        layout.addWidget(self.port_combobox)

        self.ok_button = QtWidgets.QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        layout.addWidget(self.ok_button)

    def accept(self):
        global F70_INST_NAME
        F70_INST_NAME = self.port_combobox.currentText()
        super().accept()


if __name__ == "__main__":
    multiprocessing.freeze_support()

    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon("./icon.ico"))
    app.setStyle("Fusion")

    dialog = PortDialog()

    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        sys.exit()

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
