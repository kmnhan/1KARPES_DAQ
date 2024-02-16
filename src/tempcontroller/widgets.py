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


# class ReadingWidgetGUI(QtWidgets.QWidget):
#     def __init__(
#         self,
#         *args,
#         inputs: Sequence[str],
#         names: Sequence[str] | None = None,
#         hide_srdg: bool = False,
#         **kwargs,
#     ):
#         super().__init__(*args, **kwargs)
#         self.setLayout(QtWidgets.QVBoxLayout())
#         self.readingwidgets: list[SingleReadingWidget] = []
#         for input in inputs:
#             self.readingwidgets.append(
#                 SingleReadingWidget(input=input, hide_srdg=hide_srdg)
#             )
#             self.layout().addWidget(self.readingwidgets[-1])

#         if names is not None:
#             self.update_names(names)


class ReadingWidgetGUI(QtWidgets.QWidget):
    def __init__(
        self,
        *args,
        inputs: Sequence[str],
        names: Sequence[str] | None = None,
        hide_srdg: bool = True,
        decimals: int = 2,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.setLayout(QtWidgets.QGridLayout())
        self.name_labels: list[QtWidgets.QLabel] = []
        self.krdg_spins: list[QtWidgets.QDoubleSpinBox] = []
        self.srdg_spins: list[QtWidgets.QDoubleSpinBox] = []
        self.krdg_units: list[QtWidgets.QLabel] = []
        self.srdg_units: list[QtWidgets.QLabel] = []

        boldfont = QtGui.QFont()
        boldfont.setBold(True)

        for i, input in enumerate(inputs):
            input_label = QtWidgets.QLabel(input)
            input_label.setFont(boldfont)

            name_label = QtWidgets.QLabel()
            name_label.setWordWrap(True)

            krdg_spin = QtWidgets.QDoubleSpinBox()
            krdg_spin.setReadOnly(True)
            krdg_spin.setDecimals(decimals)
            # krdg_spin.setSuffix(" K")
            krdg_spin.setRange(0.0, 500.0)
            krdg_spin.setButtonSymbols(krdg_spin.ButtonSymbols.NoButtons)

            srdg_spin = QtWidgets.QDoubleSpinBox()
            srdg_spin.setReadOnly(True)
            srdg_spin.setDecimals(decimals)
            # srdg_spin.setSuffix(" V")
            srdg_spin.setRange(0.0, 500.0)
            srdg_spin.setButtonSymbols(srdg_spin.ButtonSymbols.NoButtons)

            krdg_unit = QtWidgets.QLabel("[K]")
            srdg_unit = QtWidgets.QLabel("[V]")

            self.layout().addWidget(input_label, 2 * i, 0, 2, 1)
            self.layout().addWidget(name_label, 2 * i, 1, 2, 3)
            self.layout().addWidget(krdg_spin, 2 * i, 4, 1, 2)
            self.layout().addWidget(srdg_spin, 2 * i + 1, 4, 1, 2)
            self.layout().addWidget(krdg_unit, 2 * i, 6, 1, 1)
            self.layout().addWidget(srdg_unit, 2 * i + 1, 6, 1, 1)

            self.name_labels.append(name_label)
            self.krdg_spins.append(krdg_spin)
            self.srdg_spins.append(srdg_spin)
            self.krdg_units.append(krdg_unit)
            self.srdg_units.append(srdg_unit)

        self.set_srdg_visible(not hide_srdg)
        if names is not None:
            self.update_names(names)

    @property
    def srdg_enabled(self) -> bool:
        # return self.readingwidgets[0].srdg.isVisible()
        return self.srdg_spins[0].isVisible()

    @property
    def krdg(self) -> list[float]:
        return [spin.value() for spin in self.krdg_spins]

    @property
    def srdg(self) -> list[float]:
        return [spin.value() for spin in self.srdg_spins]

    def set_srdg_visible(self, visible: bool):
        for i in range(len(self.krdg_spins)):

            self.srdg_spins[i].setVisible(visible)
            self.srdg_units[i].setVisible(visible)
            if visible:
                self.layout().addWidget(self.krdg_spins[i], 2 * i, 4, 1, 2)
                self.layout().addWidget(self.krdg_units[i], 2 * i, 6, 1, 1)
            else:
                self.layout().addWidget(self.krdg_spins[i], 2 * i, 4, 2, 2)
                self.layout().addWidget(self.krdg_units[i], 2 * i, 6, 2, 1)
        # for rw in self.readingwidgets:
        # rw.set_srdg_visible(visible)

    def update_names(self, names: list[str]):
        for label, name in zip(self.name_labels, names):
            label.setText(name)
        # for w, name in zip(self.readingwidgets, names):
        # w.set_name(name)

    def update_krdg(self, readings: list[float]):
        for spin, value in zip(self.krdg_spins, readings):
            spin.setValue(value)
        # for w, rdg in zip(self.readingwidgets, readings):
        # w.set_krdg(rdg)

    def update_srdg(self, readings: list[float]):
        for spin, value in zip(self.srdg_spins, readings):
            spin.setValue(value)
        # for w, rdg in zip(self.readingwidgets, readings):
        #     w.set_srdg(rdg)


class ReadingWidget(ReadingWidgetGUI):

    sigKRDG = QtCore.Signal(str)
    sigSRDG = QtCore.Signal(str)

    def __init__(
        self,
        *args,
        instrument: LakeshoreThread | None = None,
        inputs: Sequence[str],
        indexer: slice | None = None,
        krdg_command: str | None = None,
        srdg_command: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, inputs=inputs, **kwargs)
        self.instrument = instrument
        self.indexer = indexer
        if krdg_command is None:
            krdg_command = "KRDG? 0"
        if srdg_command is None:
            srdg_command = "SRDG? 0"
        self.krdg_command = krdg_command
        self.srdg_command = srdg_command
        self.sigKRDG.connect(self.update_krdg)
        self.sigSRDG.connect(self.update_srdg)

    def trigger_update(self):
        self.instrument.request_query(self.krdg_command, self.sigKRDG)
        self.instrument.request_query(self.srdg_command, self.sigSRDG)

    @QtCore.Slot(str)
    def update_krdg(self, message):
        vals = [float(t) for t in message.split(",")]
        if self.indexer is not None:
            vals = vals[self.indexer]
        super().update_krdg(vals)

    @QtCore.Slot(str)
    def update_srdg(self, message):
        vals = [float(t) for t in message.split(",")]
        if self.indexer is not None:
            vals = vals[self.indexer]
        super().update_srdg(vals)


class CommandWidget(*uic.loadUiType("command.ui")):
    sigWrite = QtCore.Signal(str)
    sigQuery = QtCore.Signal(str)
    sigReply = QtCore.Signal(str)

    def __init__(self, instrument: LakeshoreThread | None = None, parent=None):
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
