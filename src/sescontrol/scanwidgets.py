import sys
from typing import Optional

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets, uic


class SingleMotorSetup(QtWidgets.QGroupBox):
    valueChanged = QtCore.Signal(float, float, float, int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        self.setCheckable(True)

        self.setLayout(QtWidgets.QVBoxLayout(self))

        self.combo = QtWidgets.QComboBox(self)
        self.layout().addWidget(self.combo)

        motors = QtWidgets.QWidget(self)
        self.layout().addWidget(motors)
        motors.setLayout(QtWidgets.QFormLayout(motors))

        self.motor_coord = np.linspace(0, 1, 11)
        self.start, self.end, self.delta, self.nstep = (
            pg.SpinBox(compactHeight=False, value=self.motor_coord[0]),
            pg.SpinBox(compactHeight=False, value=self.motor_coord[-1]),
            pg.SpinBox(
                compactHeight=False,
                value=self.motor_coord[1] - self.motor_coord[0],
            ),
            pg.SpinBox(
                compactHeight=False,
                value=len(self.motor_coord),
                int=True,
                step=1,
                min=2,
            ),
        )
        motors.layout().addRow("Start", self.start)
        motors.layout().addRow("End", self.end)
        motors.layout().addRow("Delta", self.delta)
        motors.layout().addRow("Num", self.nstep)

        self.start.sigValueChanged.connect(self.boundschanged)
        self.end.sigValueChanged.connect(self.boundschanged)
        self.nstep.sigValueChanged.connect(self.countchanged)
        self.delta.sigValueChanged.connect(self.deltachanged)

    def _refresh_values(self):
        for w in (self.start, self.end, self.delta, self.nstep):
            w.blockSignals(True)

        self.start.setValue(self.motor_coord[0])
        self.end.setValue(self.motor_coord[-1])
        self.delta.setValue(self.motor_coord[1] - self.motor_coord[0])
        self.nstep.setValue(len(self.motor_coord))

        for w in (self.start, self.end, self.delta, self.nstep):
            w.blockSignals(False)

        self.valueChanged.emit(
            self.start.value(), self.end.value(), self.delta.value(), self.nstep.value()
        )

    @property
    def npoints(self) -> int:
        if self.isChecked():
            return len(self.motor_coord)
        else:
            return 1

    @property
    def motor_properties(self) -> tuple[str, np.ndarray] | None:
        if self.isChecked():
            return (self.combo.currentText(), self.motor_coord)
        else:
            return None

    def set_limits(self, minimum: float | None, maximum: float | None):
        if minimum is not None:
            self.start.setMinimum(minimum)
            self.end.setMinimum(minimum)
        if maximum is not None:
            self.start.setMaximum(maximum)
            self.end.setMaximum(maximum)

    def set_delta(self, value: float, fixed: bool):
        self.delta.setValue(value)
        self.delta.setDisabled(fixed)

    @QtCore.Slot()
    def countchanged(self):
        if self.delta.isEnabled():
            self.boundschanged()
            return
        else:
            self.motor_coord = np.arange(
                self.start.value(),
                self.start.value() + self.delta.value() * self.nstep.value(),
                self.delta.value(),
            )
            self._refresh_values()

    @QtCore.Slot()
    def boundschanged(self):
        if self.start.value() == self.end.value():
            self.end.setValue(self.end.value() + self.delta.value())
            return
        if self.delta.isEnabled():
            self.motor_coord = np.linspace(
                self.start.value(), self.end.value(), self.nstep.value()
            )
        else:
            self.deltachanged()
            return
        self._refresh_values()

    @QtCore.Slot()
    def deltachanged(self):
        if self.delta.value() == 0:
            self.delta.setValue(1e-3)
            return
        self.motor_coord = np.arange(
            self.start.value(),
            self.end.value() + self.delta.value(),
            self.delta.value(),
        )
        if len(self.motor_coord) == 1:
            self.motor_coord = np.array(
                [self.start.value(), self.start.value() + self.delta.value()]
            )
        self._refresh_values()


if __name__ == "__main__":
    # MWE for debugging

    class MyWidget(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.channel = SingleMotorSetup()
            self.layout = QtWidgets.QVBoxLayout(self)
            self.layout.addWidget(self.channel)

    qapp = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)
    # qapp.setStyle("Fusion")
    widget = MyWidget()
    widget.show()
    widget.activateWindow()
    qapp.exec()
