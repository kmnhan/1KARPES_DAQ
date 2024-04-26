import logging
import sys

from qtpy import QtWidgets, QtCore
import time

from f70h import F70HInstrument, F70H_ALARM_BITS, F70H_STATE

log = logging.getLogger("F70H")
log.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)


class QHLine(QtWidgets.QFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)


class F70GUI(QtWidgets.QMainWindow):
    ON_LABEL = "🔴"
    OFF_LABEL = "🟢"

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
            alarm_status_label = QtWidgets.QLabel(self.OFF_LABEL)
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
        values_layout.addWidget(QtWidgets.QLabel("Pressure"), 3, 0)
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
        self.instr = F70HInstrument("ASRL1::INSTR")

        self.start_button.clicked.connect(self.start_button_clicked)
        self.stop_button.clicked.connect(self.stop_button_clicked)
        self.reset_button.clicked.connect(self.reset_button_clicked)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1000)

    def start_button_clicked(self):
        self.instr.turn_on()

    def stop_button_clicked(self):
        self.instr.turn_off()

    def reset_button_clicked(self):
        self.instr.reset()

    def update_status(self):
        bits = self.instr.status
        time.sleep(50e-3)
        temps = self.instr.temperature
        time.sleep(50e-3)
        pressure = self.instr.pressure

        state = F70H_STATE[int(bits[4:7], 2)]

        if bits[-1] == "1":
            self.statusBar().showMessage(f"System ON | {state}")
        elif bits[-1] == "0":
            self.statusBar().showMessage(f"System OFF | {state}")

        for k, v in F70H_ALARM_BITS.items():
            label = self.alarms_status_labels[v - 1]
            if int(bits[-v - 1]) == 1:
                label.setText(self.ON_LABEL)
                log.error(f"{k} alarm")
            else:
                label.setText(self.OFF_LABEL)

        for label, value in zip(self.labels[:3], temps):
            label.setText(f"{value} °C")

        self.labels[3].setText(f"{pressure} psig")

    def closeEvent(self, event):
        self.timer.stop()
        self.instr.instrument.close()

        super().closeEvent(event)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
