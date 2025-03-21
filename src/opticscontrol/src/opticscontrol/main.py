import logging
import queue
import sys
import threading
import time

import numpy as np
from qtpy import QtCore, QtGui, QtWidgets

from opticscontrol.elliptec.commands import ElliptecFtdiDevice
from opticscontrol.polarization import calculate_polarization, polarization_info

log = logging.getLogger("opticscontrol")
log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)


class ElliptecThread(QtCore.QThread):
    sigExecutionStarted = QtCore.Signal()
    sigExecutionFinished = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.stopped = threading.Event()

    @property
    def running(self) -> bool:
        return not self.stopped.is_set()

    @QtCore.Slot(str, object)
    def request_command(self, meth_name, callback_signal, args):
        # meth_name must be a string of the method name of ElliptecFtdiDevice to call
        # callback_signal must be a signal to emit the result of the command
        # args must be a tuple of positional arguments
        self.mutex.lock()
        self.queue.put((meth_name, callback_signal, args))
        self.mutex.unlock()

    def run(self):
        self.mutex = QtCore.QMutex()
        self.queue = queue.Queue()
        self.stopped.clear()

        device = ElliptecFtdiDevice()
        device.connect()

        while not self.stopped.is_set():
            if not self.queue.empty():
                meth_name, callback_signal, args = self.queue.get()

                self.sigExecutionStarted.emit()
                try:
                    result = getattr(device, meth_name)(*args)
                except Exception:
                    log.exception("Error while calling %s", meth_name)
                    result = None
                self.sigExecutionFinished.emit()

                if callback_signal is not None:
                    callback_signal.emit(result)

                self.queue.task_done()

            time.sleep(0.01)

        device.disconnect()


class _WaitDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None, message: str) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(QtWidgets.QLabel(message))
        self.setLayout(layout)
        self.setWindowFlags(
            QtCore.Qt.WindowType.Tool | QtCore.Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)


class PolarizationControlWidget(QtWidgets.QWidget):
    sigRecvPos = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QtWidgets.QVBoxLayout(self)
        self.setLayout(self._layout)

        self._plotter = PolarizationPlotter()
        self._layout.addWidget(self._plotter)

        self._pol_info = QtWidgets.QLabel()
        self._pol_info.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._pol_info)

        # Setup controls
        self._control_widget = QtWidgets.QWidget()
        self._layout.addWidget(self._control_widget)
        control_layout = QtWidgets.QGridLayout(self._control_widget)
        control_layout.setContentsMargins(0, 0, 0, 0)
        self._control_widget.setLayout(control_layout)

        # lambda/2 waveplate controls
        self._hwp_check = QtWidgets.QCheckBox("λ/2")
        self._hwp_check.setChecked(True)
        self._hwp_check.toggled.connect(self._plate_toggled)
        control_layout.addWidget(self._hwp_check, 0, 0)

        self._hwp_ang = QtWidgets.QDoubleSpinBox()
        self._hwp_ang.setRange(-365, 365)
        self._hwp_ang.setDecimals(2)
        self._hwp_ang.setReadOnly(True)
        self._hwp_ang.setButtonSymbols(self._hwp_ang.ButtonSymbols.NoButtons)
        self._hwp_ang.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._hwp_ang.setValue(0)
        self._hwp_ang.valueChanged.connect(self._update_plot)
        control_layout.addWidget(self._hwp_ang, 0, 1)

        self._hwp_setter = QtWidgets.QDoubleSpinBox()
        self._hwp_setter.setRange(0, 357)
        self._hwp_setter.setDecimals(2)
        self._hwp_setter.setSingleStep(1)
        self._hwp_setter.setValue(0)
        control_layout.addWidget(self._hwp_setter, 0, 2)

        self._hwp_go_btn = QtWidgets.QPushButton("Go")
        self._hwp_go_btn.clicked.connect(self._move_hwp)
        self._hwp_go_btn.setFixedWidth(
            QtGui.QFontMetrics(self._hwp_go_btn.font())
            .boundingRect(self._hwp_go_btn.text())
            .width()
            + 15
        )
        control_layout.addWidget(self._hwp_go_btn, 0, 3)

        self._hwp_home_btn = QtWidgets.QPushButton("Home")
        self._hwp_home_btn.clicked.connect(self._home_hwp)
        self._hwp_home_btn.setFixedWidth(
            QtGui.QFontMetrics(self._hwp_home_btn.font())
            .boundingRect(self._hwp_home_btn.text())
            .width()
            + 15
        )
        control_layout.addWidget(self._hwp_home_btn, 0, 4)

        # lambda/4 waveplate controls
        self._qwp_check = QtWidgets.QCheckBox("λ/4")
        self._qwp_check.setChecked(True)
        self._qwp_check.toggled.connect(self._plate_toggled)
        control_layout.addWidget(self._qwp_check, 1, 0)

        self._qwp_ang = QtWidgets.QDoubleSpinBox()
        self._qwp_ang.setRange(-365, 365)
        self._qwp_ang.setDecimals(2)
        self._qwp_ang.setReadOnly(True)
        self._qwp_ang.setButtonSymbols(self._qwp_ang.ButtonSymbols.NoButtons)
        self._qwp_ang.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._qwp_ang.setValue(0)
        self._qwp_ang.valueChanged.connect(self._update_plot)
        control_layout.addWidget(self._qwp_ang, 1, 1)

        self._qwp_setter = QtWidgets.QDoubleSpinBox()
        self._qwp_setter.setRange(0, 357)
        self._qwp_setter.setDecimals(2)
        self._qwp_setter.setSingleStep(1)
        self._qwp_setter.setValue(0)
        control_layout.addWidget(self._qwp_setter, 1, 2)

        self._qwp_go_btn = QtWidgets.QPushButton("Go")
        self._qwp_go_btn.clicked.connect(self._move_qwp)
        self._qwp_go_btn.setFixedWidth(
            QtGui.QFontMetrics(self._qwp_go_btn.font())
            .boundingRect(self._qwp_go_btn.text())
            .width()
            + 15
        )
        control_layout.addWidget(self._qwp_go_btn, 1, 3)

        self._qwp_home_btn = QtWidgets.QPushButton("Home")
        self._qwp_home_btn.clicked.connect(self._home_qwp)
        self._qwp_home_btn.setFixedWidth(
            QtGui.QFontMetrics(self._qwp_home_btn.font())
            .boundingRect(self._qwp_home_btn.text())
            .width()
            + 15
        )
        control_layout.addWidget(self._qwp_home_btn, 1, 4)

        # Uncomment after installing lamba/4 waveplate
        self._qwp_check.setChecked(False)
        self._plate_toggled()
        self._qwp_check.setDisabled(True)

        self.update_btn = QtWidgets.QPushButton("Get Positions")
        self.update_btn.clicked.connect(self._get_positions)
        self._layout.addWidget(self.update_btn)

        # Setup thread
        self._thread = ElliptecThread()
        self._thread.sigExecutionStarted.connect(self.command_started)
        self._thread.sigExecutionFinished.connect(self.command_finished)

        self.busy: bool = False
        self._wait_dialog = _WaitDialog(self, "Busy...")

        self._thread.start()
        while self._thread.stopped.is_set():
            time.sleep(1e-4)

        self.sigRecvPos.connect(self._update_angles)

    @QtCore.Slot()
    def command_started(self):
        self.busy = True
        QtCore.QTimer.singleShot(200, self._show_busy_if_still_running)

    @QtCore.Slot()
    def command_finished(self):
        self.busy = False
        self._wait_dialog.close()

    @QtCore.Slot()
    def _show_busy_if_still_running(self):
        if self.busy:
            self._wait_dialog.show()

    @QtCore.Slot()
    def _plate_toggled(self):
        self._hwp_ang.setDisabled(not self._hwp_check.isChecked())
        self._hwp_setter.setDisabled(not self._hwp_check.isChecked())
        self._hwp_go_btn.setDisabled(not self._hwp_check.isChecked())
        self._hwp_home_btn.setDisabled(not self._hwp_check.isChecked())
        self._qwp_ang.setDisabled(not self._qwp_check.isChecked())
        self._qwp_setter.setDisabled(not self._qwp_check.isChecked())
        self._qwp_go_btn.setDisabled(not self._qwp_check.isChecked())
        self._qwp_home_btn.setDisabled(not self._qwp_check.isChecked())
        self._update_plot()

    @QtCore.Slot()
    def _get_positions(self):
        if self._hwp_check.isChecked():
            self._thread.request_command("position_physical", self.sigRecvPos, (0,))
        if self._qwp_check.isChecked():
            self._thread.request_command("position_physical", self.sigRecvPos, (1,))

    @QtCore.Slot(object)
    def _update_angles(self, output):
        if output is None:
            return
        address, pos = output
        if address == 0:
            self._hwp_ang.setValue(np.rad2deg(pos))
        elif address == 1:
            self._qwp_ang.setValue(np.rad2deg(pos))

    @QtCore.Slot()
    def _move_hwp(self):
        self._thread.request_command(
            "move_abs_physical",
            self.sigRecvPos,
            (0, float(np.deg2rad(self._hwp_setter.value()))),
        )

    @QtCore.Slot()
    def _move_qwp(self):
        self._thread.request_command(
            "move_abs_physical",
            self.sigRecvPos,
            (1, float(np.deg2rad(self._qwp_setter.value()))),
        )

    @QtCore.Slot()
    def _home_hwp(self):
        self._thread.request_command("home", self.sigRecvPos, (0,))

    @QtCore.Slot()
    def _home_qwp(self):
        self._thread.request_command("home", self.sigRecvPos, (1,))

    @QtCore.Slot()
    def _update_plot(self):
        pol = calculate_polarization(
            self._hwp_ang.value() if self._hwp_check.isChecked() else None,
            self._qwp_ang.value() if self._qwp_check.isChecked() else None,
        )
        self._plotter.set_polarization(pol)
        self._pol_info.setText(polarization_info(pol))

    def closeEvent(self, event):
        self._thread.stopped.set()
        self._thread.wait()


class PolarizationVisualizer(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QtWidgets.QFormLayout(self)
        self.setLayout(self._layout)

        self._plotter = PolarizationPlotter()
        self._layout.addRow(self._plotter)

        self._pol_info = QtWidgets.QLabel()
        self._pol_info.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._layout.addRow(self._pol_info)

        self._hwp_ang = QtWidgets.QDoubleSpinBox()
        self._hwp_ang.setRange(-360, 360)
        self._hwp_ang.setSingleStep(1)
        self._hwp_ang.setValue(0)
        self._hwp_ang.setKeyboardTracking(False)
        self._hwp_ang.valueChanged.connect(self._update_polarization)
        self._layout.addRow("λ/2", self._hwp_ang)

        self._qwp_ang = QtWidgets.QDoubleSpinBox()
        self._qwp_ang.setRange(-360, 360)
        self._qwp_ang.setSingleStep(1)
        self._qwp_ang.setValue(0)
        self._qwp_ang.setKeyboardTracking(False)
        self._qwp_ang.valueChanged.connect(self._update_polarization)
        self._layout.addRow("λ/4", self._qwp_ang)

        self._update_polarization()

    @QtCore.Slot()
    def _update_polarization(self):
        pol = calculate_polarization(
            float(self._hwp_ang.value()), float(self._qwp_ang.value())
        )
        self._plotter.set_polarization(pol)
        self._pol_info.setText(polarization_info(pol))


class PolarizationPlotter(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.jones = np.array([0.0, 1.0])
        self.setMinimumSize(100, 100)

    def set_polarization(self, jones):
        self.jones = jones
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect()
        center = rect.center()

        a = np.abs(self.jones[0])
        b = np.abs(self.jones[1])
        delta = np.angle(self.jones[1]) - np.angle(self.jones[0])

        # Calculate ellipse parameters from the polarization components.
        # The ellipse representing the polarization has semi-axes A and B given by:
        #   A², B² = (a²+b² ± sqrt((a²-b²)²+4a²b²cos²(delta)))/2
        term = np.sqrt((a**2 - b**2) ** 2 + 4 * (a * b * np.cos(delta)) ** 2)
        A = np.sqrt(max((a**2 + b**2 + term) / 2, 1e-15))
        B = np.sqrt(max((a**2 + b**2 - term) / 2, 1e-15))

        # The rotation angle (psi) of the ellipse is:
        #   psi = 0.5 * arctan(2a*b*cos(delta)/(a²-b²))
        if abs(a**2 - b**2) < 1e-15:
            angle = np.pi / 4
        else:
            angle = 0.5 * np.atan2(2 * a * b * np.cos(delta), (a**2 - b**2))

        # Scale the drawing based on the widget size.
        scale = min(rect.width(), rect.height()) / 3.0

        # Draw the polarization ellipse.
        painter.save()
        painter.translate(center)
        painter.rotate(angle * 180 / np.pi)
        painter.setPen(QtGui.QPen(QtGui.QColor("blue"), 2))
        painter.drawEllipse(
            QtCore.QRectF(-A * scale, -B * scale, 2 * A * scale, 2 * B * scale)
        )
        # polygon = QtGui.QPolygonF()
        # t = np.linspace(0, 2 * np.pi, 100)
        # x = np.real(self.jones[0] * np.exp(1j * t))
        # y = np.real(self.jones[1] * np.exp(1j * t))

        # for xi, yi in zip(x, y, strict=True):
        #     polygon.append(
        #         QtCore.QPointF(center.x() + xi * scale, center.y() + yi * scale)
        #     )
        # painter.drawPolygon(polygon)
        painter.restore()

        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("red"), 2))
        # painter.drawLine(
        #     QtCore.QLineF(center.x(), center.y(), center.x() + a * scale, center.y())
        # )
        # painter.drawLine(
        #     QtCore.QLineF(center.x(), center.y(), center.x(), center.y() - b * scale)
        # )
        painter.restore()


if __name__ == "__main__":
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")

    win = PolarizationControlWidget()
    win.show()
    win.activateWindow()
    qapp.exec()
