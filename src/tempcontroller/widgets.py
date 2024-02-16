import sys
from collections.abc import Iterable, Sequence

import numpy as np
import pyqtgraph as pg
import pyvisa
from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from qtpy import QtCore, QtGui, QtWidgets, uic

from connection import LakeshoreThread


class QHLine(QtWidgets.QFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)


class QVLine(QtWidgets.QFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)


class HeaterWidget(*uic.loadUiType("heater.ui")):
    """GUI for a single heater.

    The backend needs to connect signals and slots to appropriate SCPI commands.

    First, to populate the GUI with current values, some SCPI query outputs must be
    connected to appropriate slots; `SETP?` to `update_setpoint`, `HTR?` to
    `update_output`, `RANGE?` to `update_range`, and `RAMPST?` to `update_rampst`.

    Next, GUI signals must be hooked up to appropriate SCPI commands. See below for
    details.

    Signals
    -------
    sigSetp(float)
        Connect to SCPI command `SETP`.
    sigRamp(int, float)
        Connect to SCPI command `RAMP`.
    sigRange(int)
        Connect to SCPI command `RANGE`.
    sigUpdateTarget()
        Connect to SCPI query `KRDG?`, whose output must be connected to the
        `set_target` slot.

    """

    sigSetp = QtCore.Signal(float)
    sigRamp = QtCore.Signal(bool, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.pbar.valueChanged.connect(self._format_output)
        # palette = QtGui.QPalette(self.pbar.palette())
        # palette.setColor(QtGui.QPalette.ColorRole.Highlight,QtGui.QColor("crimson"))
        # self.pbar.setPalette(palette)

        self.ramp_check.toggled.connect(self.ramp_toggled)
        self.go_btn.clicked.connect(self.apply_setpoint)

    @property
    def sigRange(self):
        return self.combo.currentIndexChanged

    @property
    def sigUpdateTarget(self):
        return self.current_btn.clicked

    @QtCore.Slot(float)
    def update_setpoint(self, value: float):
        self.setpoint_spin.setValue(value)

    @QtCore.Slot(float)
    def update_output(self, value: float):
        self.pbar.setValue(round(value * 100))

    @QtCore.Slot(int)
    def update_range(self, value: int):
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(value)
        self.combo.blockSignals(False)

    @QtCore.Slot(int)
    def update_rampst(self, value: int):
        self.ramp_check.blockSignals(True)
        if int(value) == 0:
            self.ramp_check.setChecked(False)
        else:
            self.ramp_check.setChecked(True)
        self.ramp_check.blockSignals(False)

    @QtCore.Slot()
    def ramp_toggled(self):
        self.sigRamp.emit(int(self.ramp_check.isChecked()), self.rate_spin.value())

    @QtCore.Slot()
    def apply_setpoint(self):
        self.sigSetp.emit(self.target_spin.value())

    @QtCore.Slot(float)
    def set_target(self, value: float):
        self.target_spin.setValue(value)

    @QtCore.Slot(int)
    def _format_output(self, value: int):
        self.pbar.setFormat(f"{value / 100:.2f}%")


class SingleReadingWidget(*uic.loadUiType("reading.ui")):
    def __init__(
        self,
        name: str | None = None,
        input: str | None = None,
        hide_srdg: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setupUi(self)

        if name is None:
            name = ""
        if input is None:
            input = ""

        # self.klabel.setText(f"K")
        # self.slabel.setText(f"V")

        self.set_input(input)
        self.set_name(name)

        if hide_srdg:
            self.set_srdg_visible(False)

    def set_name(self, name: str):
        self.label.setText(name)

    def set_input(self, input: str):
        self.input: str = input
        self.inputlabel.setText(f"{self.input}")
        # self.klabel.setText(f"{self.input} [K]")
        # self.slabel.setText(f"{self.input} [V]")

    def set_srdg_visible(self, value: bool):
        self.slabel.setVisible(value)
        self.srdg.setVisible(value)

    @QtCore.Slot(float)
    def set_krdg(self, value: float):
        self.krdg.setText(str(value))

    @QtCore.Slot(float)
    def set_srdg(self, value: float):
        self.srdg.setText(str(value))


class ReadingWidgetGUI(QtWidgets.QWidget):
    def __init__(
        self,
        *args,
        inputs: Sequence[str],
        names: Sequence[str] | None = None,
        hide_srdg: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.setLayout(QtWidgets.QVBoxLayout())
        self.readingwidgets: list[SingleReadingWidget] = []
        for input in inputs:
            self.readingwidgets.append(
                SingleReadingWidget(input=input, hide_srdg=hide_srdg)
            )
            self.layout().addWidget(self.readingwidgets[-1])

        if names is not None:
            self.update_names(names)

    @property
    def srdg_enabled(self) -> bool:
        return self.readingwidgets[0].srdg.isVisible()

    def set_srdg_visible(self, visible: bool):
        for rw in self.readingwidgets:
            rw.set_srdg_visible(visible)

    def update_names(self, names: list[str]):
        for w, name in zip(self.readingwidgets, names):
            w.set_name(name)

    def update_krdg(self, readings: list[float]):
        for w, rdg in zip(self.readingwidgets, readings):
            w.set_krdg(rdg)

    def update_srdg(self, readings: list[float]):
        for w, rdg in zip(self.readingwidgets, readings):
            w.set_srdg(rdg)


class ReadingWidget(ReadingWidgetGUI):

    sigKRDG = QtCore.Signal(str)
    sigSRDG = QtCore.Signal(str)

    def __init__(
        self, *args, instrument: LakeshoreThread, inputs: Sequence[str], **kwargs
    ):
        super().__init__(*args, inputs=inputs, **kwargs)
        self.instrument = instrument

        self.sigKRDG.connect(self.update_krdg)
        self.sigSRDG.connect(self.update_srdg)

    def trigger_update(self):
        self.instrument.request_query("KRDG? 0", self.sigKRDG)
        if self.srdg_enabled:
            self.instrument.request_query("SRDG? 0", self.sigSRDG)

    @QtCore.Slot(str)
    def update_krdg(self, message):
        super().update_krdg([float(t) for t in message.split(",")])

    @QtCore.Slot(str)
    def update_srdg(self, message):
        super().update_srdg([float(t) for t in message.split(",")])


class CommandWidget(*uic.loadUiType("command.ui")):
    sigWrite = QtCore.Signal(str)
    sigQuery = QtCore.Signal(str)
    sigReply = QtCore.Signal(str)

    def __init__(self, instrument: LakeshoreThread=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.instrument = instrument

        self.write_btn.clicked.connect(self.write)
        self.query_btn.clicked.connect(self.query)

        self.sigReply.connect(self.set_reply)

    @QtCore.Slot(str)
    def set_reply(self, message: str):
        self.text_out.setPlainText(message)

    @QtCore.Slot()
    def write(self):
        self.instrument.request_write(self.text_in.toPlainText())

    @QtCore.Slot()
    def query(self):
        self.instrument.request_query(self.text_in.toPlainText(), self.sigReply)

    # def write(self):
    # self.instrument.request_query()


if __name__ == "__main__":

    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")

    # win = HeaterWidget()
    win = CommandWidget()
    # win = ReadingWidget(inputs=("A", "B", "C", "D"))

    # win.srdg_visible(False)
    # win.set_name("1K Cold Finger")
    # win.set_input("A")

    # win.update_output(50.2315)
    # win.update_mout(0.0)
    # win.update_mout(83.0)

    win.show()
    win.activateWindow()
    qapp.exec()
