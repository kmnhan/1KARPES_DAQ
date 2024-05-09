import datetime
import logging
import os
import sys
import time

import slack_sdk
import slack_sdk.errors
from f70h import F70H_ALARM_BITS, F70H_STATE, F70HInstrument
from qtpy import QtCore, QtGui, QtWidgets

try:
    os.chdir(sys._MEIPASS)
except:  # noqa: E722
    pass

log = logging.getLogger("F70H")
log.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)


client = slack_sdk.WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))


def send_message(message: str | list[str]):
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
        self.alarm_status_labels = []
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


class UpdateThread(QtCore.QThread):
    sigUpdate = QtCore.Signal(str, object, int)

    def __init__(self, instrument, timeout=50.0) -> None:
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


class MainWindow(F70GUI):
    def __init__(self):
        super().__init__()
        self.instr = F70HInstrument("ASRL1::INSTR")

        self.start_button.clicked.connect(self.start_button_clicked)
        self.stop_button.clicked.connect(self.stop_button_clicked)
        self.reset_button.clicked.connect(self.reset_button_clicked)

        self.alarms_notified: set[str] = set()

        self.update_thread = UpdateThread(self.instr)
        self.update_thread.sigUpdate.connect(self.update_status)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

    @property
    def current_time_formatted(self) -> str:
        return datetime.datetime.now().isoformat(sep=" ", timespec="seconds")

    def start_button_clicked(self):
        if self.update_thread.isRunning():
            self.update_thread.wait()
        self.instr.turn_on()

        send_message(
            f":large_green_circle: {self.current_time_formatted} Compressor ON"
        )

    def stop_button_clicked(self):
        if self.update_thread.isRunning():
            self.update_thread.wait()
        self.instr.turn_off()

        send_message(f":red_circle: {self.current_time_formatted} Compressor OFF")

    def reset_button_clicked(self):
        if self.update_thread.isRunning():
            self.update_thread.wait()
        self.instr.reset()
        self.alarms_notified = []

    def refresh(self):
        if self.update_thread.isRunning():
            self.update_thread.wait()
        self.update_thread.start()

    def notify_alarm(
        self, alarms: list[str], temperature: tuple[int, int, int], pressure: int
    ):
        if len(alarms) == 0:
            send_message(
                f":white_check_mark: {self.current_time_formatted} Alarms cleared"
            )
            return
        temp_str = ", ".join([f"{t}°C" for t in temperature])
        send_message(
            [
                f":warning: {self.current_time_formatted} Alarms raised:",
                ", ".join(alarms),
                f"Current status: {temp_str}",
                f"Return pressure {pressure} psig",
            ]
        )

    @QtCore.Slot(str, object, int)
    def update_status(
        self, bits: str, temperature: tuple[int, int, int], pressure: int
    ):
        state = F70H_STATE[int(bits[4:7], 2)]

        if bits[-1] == "1":
            self.statusBar().showMessage(f"System ON | {state}")
        elif bits[-1] == "0":
            self.statusBar().showMessage(f"System OFF | {state}")

        alarms = []
        for k, v in F70H_ALARM_BITS.items():
            label = self.alarm_status_labels[v - 1]
            if int(bits[-v - 1]) == 1:
                label.setText(self.ON_LABEL)
                log.critical(f"ALARM: {k}")
                alarms.append(k)
            else:
                label.setText(self.OFF_LABEL)

        if set(alarms) != self.alarms_notified:
            self.notify_alarm(alarms, temperature, pressure)
            self.alarms_notified = set(alarms)

        for label, value in zip(self.labels[:3], temperature, strict=True):
            label.setText(f"{value} °C")

        self.labels[3].setText(f"{pressure} psig")

    def closeEvent(self, event):
        self.timer.stop()

        if self.update_thread.isRunning():
            self.update_thread.wait()

        self.instr.instrument.close()

        super().closeEvent(event)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon("./icon.ico"))
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
