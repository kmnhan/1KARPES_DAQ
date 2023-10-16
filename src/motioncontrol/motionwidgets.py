import configparser
import sys
from collections.abc import Sequence

import qtawesome as qta
from qtpy import QtCore, QtGui, QtWidgets, uic

CONFIG_FILE = "D:/MotionController/piezomotors.ini"


class StautsIconWidget(qta.IconWidget):
    def __init__(self, *icons: Sequence[str | dict | QtGui.QIcon], parent=None):
        super().__init__(parent=parent)
        self._icons: list[QtGui.QIcon] = []
        for icn in icons:
            if isinstance(icn, str):
                self._icons.append(qta.icon(icn))
            elif isinstance(icn, dict):
                self._icons.append(qta.icon(**icn))
            elif isinstance(icn, QtGui.QIcon):
                self._icons.append(icn)
            else:
                raise TypeError(f"Unrecognized icon type `{type(icn)}`")
        self._state: int = 0
        self.setState(self._state)

    def setText(self, *args, **kwargs):
        return

    def icons(self) -> Sequence[QtGui.QIcon]:
        return self._icons

    def state(self) -> int:
        return self._state

    def nstates(self) -> int:
        return len(self.icons())

    def setState(self, state: int):
        self._state = int(state)
        self.setIcon(self.icons()[self._state])

    def setIconSize(self, size: QtCore.QSize, update: bool = False):
        super().setIconSize(size)
        if update:
            self.update()

    def update(self, *args, **kwargs):
        self._icon = self.icons()[self._state]
        return super().update(*args, **kwargs)


class MotorStatus(StautsIconWidget):
    def __init__(self, parent=None):
        super().__init__(
            qta.icon("mdi6.circle-outline", color="#e50000"),
            qta.icon("mdi6.loading", color="#15b01a", animation=qta.Spin(self)),
            parent=parent,
        )
        self.setIconSize(QtCore.QSize(20, 20), update=True)

    def setState(self, value: bool):
        super().setState(1 if value else 0)


class SingleChannelWidget(*uic.loadUiType("channel.ui")):
    sigMoveRequested = QtCore.Signal(int, int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.checkbox.toggled.connect(
            lambda: self.set_channel_disabled(not self.enabled)
        )
        self.status = MotorStatus(self)
        self.layout().addWidget(self.status)
        self.left_btn.setIcon(qta.icon("mdi6.arrow-left"))
        self.right_btn.setIcon(qta.icon("mdi6.arrow-right"))
        self.step_spin.valueChanged.connect(self.target_spin.setSingleStep)
        self.step_spin.setValue(0.1)

        self.left_btn.clicked.connect(self.step_down)
        self.right_btn.clicked.connect(self.step_up)
        self.move_btn.clicked.connect(self.move)

        # internal variables
        self.raw_position: int | None = None

        # read configuration & populate combobox
        self.config = configparser.ConfigParser()
        self.config.read(CONFIG_FILE)
        self.combobox.clear()
        for sec in self.config.sections():
            self.combobox.addItem(self.config[sec].get("alias", sec))
        self.combobox.currentTextChanged.connect(self.update_motor)
        self.update_motor()

    def set_name(self, name: str):
        self.checkbox.setText(name)

    @property
    def enabled(self) -> bool:
        return self.checkbox.isChecked()

    @property
    def current_config(self) -> configparser.SectionProxy:
        return self.config[self.config.sections()[self.combobox.currentIndex()]]

    @property
    def nominal_capacitance(self) -> float | None:
        return self.current_config.getfloat("cap", None)

    @property
    def tolerance(self) -> int:
        tol = self.current_config.getfloat("tol", None)
        if tol is None:
            return 4
        else:
            return round(abs(tol * 1e-3 / self.cal_A))

    @QtCore.Slot()
    def target_current_pos(self):
        self.target_spin.setValue(self.convert_pos(self.raw_position))

    def set_channel_disabled(self, value: bool):
        self.combobox.setDisabled(value)
        self.pos_lineedit.setDisabled(value)
        self.target_spin.setDisabled(value)
        self.left_btn.setDisabled(value)
        self.step_spin.setDisabled(value)
        self.right_btn.setDisabled(value)
        self.move_btn.setDisabled(value)

    def set_motion_busy(self, value: bool):
        self.combobox.setDisabled(value)
        self.move_btn.setDisabled(value)

    def update_motor(self):
        self.cal_A = self.current_config.getfloat("a", 1.0)
        self.cal_B = self.current_config.getfloat("b", 0.0)
        self.cal_B -= self.current_config.getfloat("origin", 0.0)

        bounds = (
            self.convert_pos(self.current_config.getint("min", 0)),
            self.convert_pos(self.current_config.getint("max", 65535)),
        )
        self.target_spin.setMinimum(min(bounds))
        self.target_spin.setMaximum(max(bounds))

        self.freq_spin.setValue(self.current_config.getint("freq", 200))
        self.amp_fwd_spin.setValue(self.current_config.getint("voltage_0", 30))
        self.amp_bwd_spin.setValue(self.current_config.getint("voltage_1", 30))

        if self.raw_position is not None:
            self.set_current_pos(self.raw_position)

    def convert_pos(self, pos: int) -> float:
        return self.cal_A * pos + self.cal_B

    def convert_pos_inv(self, value: float) -> int:
        return round((value - self.cal_B) / self.cal_A)

    @QtCore.Slot(int)
    def set_current_pos(self, pos: int):
        self.raw_position = pos
        self.pos_lineedit.setText(f"{self.convert_pos(self.raw_position):.4f}")

    @QtCore.Slot()
    def step_up(self):
        self.target_spin.stepBy(1)

    @QtCore.Slot()
    def step_down(self):
        self.target_spin.stepBy(-1)

    @QtCore.Slot()
    def move(self):
        self.sigMoveRequested.emit(
            self.convert_pos_inv(self.target_spin.value()),
            self.freq_spin.value(),
            (self.amp_fwd_spin.value(), self.amp_bwd_spin.value()),
        )


if __name__ == "__main__":
    # MWE for debugging

    class MyWidget(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.channel = SingleChannelWidget()
            self.layout = QtWidgets.QVBoxLayout(self)
            self.layout.addWidget(self.channel)

    qapp = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    widget = MyWidget()
    widget.show()
    widget.activateWindow()
    qapp.exec()
