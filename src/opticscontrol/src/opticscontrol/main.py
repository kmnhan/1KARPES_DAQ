from __future__ import annotations

import logging
import queue
import sys
import threading
import time
import weakref
from multiprocessing import shared_memory

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


class _RotatorWidget(QtWidgets.QWidget):
    sigToggled = QtCore.Signal()

    def __init__(
        self, parent: PolarizationControlWidget, title: str, address: int
    ) -> None:
        super().__init__(parent=parent)
        self.address = int(address)

        self._pcw = weakref.ref(parent)

        self._layout = QtWidgets.QHBoxLayout(self)
        self.setLayout(self._layout)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.check = QtWidgets.QCheckBox(title)
        self.check.setChecked(True)
        self.check.toggled.connect(self._toggled)
        self._layout.addWidget(self.check)

        self.val_spin = QtWidgets.QDoubleSpinBox()
        self.val_spin.setRange(-365, 365)
        self.val_spin.setDecimals(2)
        self.val_spin.setReadOnly(True)
        self.val_spin.setButtonSymbols(self.val_spin.ButtonSymbols.NoButtons)
        self.val_spin.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.val_spin.setValue(0)
        self._layout.addWidget(self.val_spin)

        self.target_spin = QtWidgets.QDoubleSpinBox()
        self.target_spin.setRange(0, 357)
        self.target_spin.setDecimals(2)
        self.target_spin.setSingleStep(1)
        self.target_spin.setValue(0)
        self._layout.addWidget(self.target_spin)

        self.go_btn = QtWidgets.QPushButton("Go")
        self.go_btn.clicked.connect(self.move)
        self.go_btn.setFixedWidth(
            QtGui.QFontMetrics(self.go_btn.font())
            .boundingRect(self.go_btn.text())
            .width()
            + 15
        )
        self._layout.addWidget(self.go_btn)

        self.home_btn = QtWidgets.QPushButton("Home")
        self.home_btn.clicked.connect(self.home)
        self.home_btn.setFixedWidth(
            QtGui.QFontMetrics(self.home_btn.font())
            .boundingRect(self.home_btn.text())
            .width()
            + 15
        )
        self._layout.addWidget(self.home_btn)

    @property
    def sigValueChanged(self) -> QtCore.Signal:
        return self.val_spin.valueChanged

    @property
    def pcw(self) -> PolarizationControlWidget:
        return self._pcw()

    @property
    def value(self) -> float:
        return self.val_spin.value() if self.enabled else np.nan

    @property
    def enabled(self) -> bool:
        return self.check.isChecked()

    def set_value(self, value: float) -> None:
        if self.enabled:
            self.val_spin.setValue(np.rad2deg(value))

    @QtCore.Slot()
    def update_value(self):
        if self.enabled:
            self.pcw._thread.request_command(
                "position_physical", self.pcw.sigRecvPos, (self.address,)
            )

    @QtCore.Slot()
    def _toggled(self):
        self.val_spin.setDisabled(not self.enabled)
        self.target_spin.setDisabled(not self.enabled)
        self.go_btn.setDisabled(not self.enabled)
        self.home_btn.setDisabled(not self.enabled)
        self.sigToggled.emit()

    @QtCore.Slot()
    def move(self):
        self.pcw._thread.request_command(
            "move_abs_physical",
            self.pcw.sigRecvPos,
            (self.address, float(np.deg2rad(self.target_spin.value()))),
        )

    @QtCore.Slot()
    def home(self):
        if self.enabled:
            self.pcw._thread.request_command(
                "home", self.pcw.sigRecvPos, (self.address,)
            )


class PolarizationControlWidget(QtWidgets.QWidget):
    sigRecvPos = QtCore.Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Shared memory for access by other processes
        # Will be created on initial data update
        self.shm: shared_memory.SharedMemory | None = None

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
        self.control_layout = QtWidgets.QVBoxLayout(self._control_widget)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        self._control_widget.setLayout(self.control_layout)

        self._motors = {
            0: _RotatorWidget(self, "λ/2", 0),
            1: _RotatorWidget(self, "λ/4", 1),
        }

        for motor in self._motors.values():
            motor.sigToggled.connect(self._update_plot)
            motor.sigValueChanged.connect(self._update_plot)
            self.control_layout.addWidget(motor)

        # Uncomment after installing lamba/4 waveplate
        self._motors[1].check.setChecked(False)
        self._motors[1]._toggled()
        self._motors[1].check.setDisabled(True)

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

        self.sigRecvPos.connect(self._pos_recv)

    @QtCore.Slot()
    def command_started(self) -> None:
        self.busy = True
        QtCore.QTimer.singleShot(200, self._show_busy_if_still_running)

    @QtCore.Slot()
    def command_finished(self) -> None:
        self.busy = False
        self._wait_dialog.close()

    @QtCore.Slot()
    def _show_busy_if_still_running(self) -> None:
        if self.busy:
            self._wait_dialog.show()

    @QtCore.Slot()
    def _get_positions(self) -> None:
        for motor in self._motors.values():
            motor.update_value()

    @QtCore.Slot(object)
    def _pos_recv(self, output) -> None:
        if output is None:
            return
        address, pos = output

        log.debug("Received pos result %s", output)

        if address in self._motors:
            self._motors[address].set_value(pos)

    @QtCore.Slot()
    def _update_plot(self):
        pol = calculate_polarization(self._motors[0].value, self._motors[1].value)
        self._plotter.set_polarization(pol)
        self._pol_info.setText(polarization_info(pol))
        self._update_shm()

    @QtCore.Slot()
    def _update_shm(self):
        if self.shm is None:
            # Create shared memory on first update
            self.shm = shared_memory.SharedMemory(
                name="Optics", create=True, size=8 * len(self._motors)
            )

        arr = np.ndarray((len(self._motors),), dtype="f8", buffer=self.shm.buf)

        for i, motor in enumerate(self._motors.values()):
            arr[i] = motor.value

    def closeEvent(self, event):
        # Free shared memory
        self.shm.close()
        self.shm.unlink()

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
    # win = PolarizationVisualizer()
    win.show()
    win.activateWindow()
    qapp.exec()
