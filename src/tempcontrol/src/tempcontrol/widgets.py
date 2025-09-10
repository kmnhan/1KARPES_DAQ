import contextlib
import datetime
import logging
import os
import sys
import weakref
from collections.abc import Sequence

import pyqtgraph as pg
from qt_extensions.legendtable import LegendTableView
from qt_extensions.plotting import DynamicPlotItemTwiny, XDateSnapCurvePlotDataItem
from qtpy import QtCore, QtGui, QtWidgets, uic

from tempcontrol.connection import VISAThread, VISAWidgetBase

with contextlib.suppress(Exception):
    os.chdir(sys._MEIPASS)

log = logging.getLogger("tempctrl")


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


class HeaterWidgetGUI(
    *uic.loadUiType(os.path.join(os.path.dirname(__file__), "heater.ui"))
):
    """GUI for a single heater.

    The backend needs to connect signals and slots to appropriate SCPI commands.

    First, to populate the GUI with current values, some SCPI query outputs must be
    connected to appropriate slots; `SETP?` to `update_setpoint`, `HTR?` to
    `update_output`, `RANGE?` to `update_range`, and `RAMP?` to `update_rampst` and
    `update_ramprate`.

    Next, GUI signals must be hooked up to appropriate SCPI commands. See below for
    details.

    Signals
    -------
    sigSetpChanged(float)
        Connect to SCPI command `SETP`.
    sigRampChanged(int, float)
        Connect to SCPI command `RAMP`.
    sigRangeChanged(int)
        Connect to SCPI command `RANGE`.
    sigUpdateTarget()
        Connect to SCPI query `KRDG?`, whose output must be connected to the
        `set_target` slot.

    """

    sigSetpChanged = QtCore.Signal(float)
    sigRampChanged = QtCore.Signal(int, float)
    sigPIDInputSet = QtCore.Signal(object, int)

    def __init__(self, *args, **kwargs):
        # Do not reconnect on error, reconnecting will be handled by CommandWidget
        kwargs["reconnect_on_error"] = False
        super().__init__(*args, **kwargs)
        self.setupUi(self)

        self.pbar.valueChanged.connect(self._format_output)
        palette = QtGui.QPalette(self.pbar.palette())
        palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor("crimson"))
        self.pbar.setPalette(palette)

        self.rate_spin.valueChanged.connect(self.apply_ramp)
        self.ramp_check.toggled.connect(self.apply_ramp)
        self.go_btn.clicked.connect(self.apply_setpoint)

        # List of [update_time, value] pairs
        # [setpoint, output, range, ramp state, ramp rate]
        self._raw_data: list[list[datetime.datetime, str]] = [[None, "nan"]] * 5

    def set_input_name(self, input_name: str, input_desc: str) -> None:
        if input_name.strip() == "":
            input_name = "B"
        self.input_name.setText(f"Input <b>{input_name}</b>")
        self.input_desc.setText(input_desc)

    def set_heater_mode(self, mode: str) -> None:
        self.input_name.setText(mode)
        self.input_desc.setText("")

    @property
    def sigRangeChanged(self):
        return self.combo.currentIndexChanged

    @property
    def sigUpdateTarget(self):
        return self.current_btn.clicked

    def get_raw_data(self, threshold: float) -> list[str]:
        # Obtain the most recent value for each parameter, or "nan" if the value is
        # older than `threshold` seconds.
        now = datetime.datetime.now()
        out = []
        for dt, val in self._raw_data:
            if dt is None or now - dt > datetime.timedelta(seconds=threshold):
                out.append("nan")
            else:
                out.append(val)
        return out

    @QtCore.Slot(str, object)
    def update_setpoint(self, value: str | float, dt: datetime.datetime):
        self._raw_data[0] = [dt, str(value).strip()]
        self.setpoint_spin.setValue(float(self._raw_data[0][1]))

    @QtCore.Slot(str, object)
    def update_output(self, value: str | float, dt: datetime.datetime):
        self._raw_data[1] = [dt, str(value).strip()]
        self.pbar.setValue(round(float(self._raw_data[1][1]) * 100))

    @QtCore.Slot(str, object)
    def update_range(self, value: str | int, dt: datetime.datetime):
        self._raw_data[2] = [dt, str(value).strip()]
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(int(self._raw_data[2][1]))
        self.combo.blockSignals(False)

    @QtCore.Slot(str, object)
    def update_rampst(self, value: str | int, dt: datetime.datetime):
        self._raw_data[3] = [dt, str(value).strip()]
        self.ramp_check.blockSignals(True)
        if int(value) == 0:
            self.ramp_check.setChecked(False)
        else:
            self.ramp_check.setChecked(True)
        self.ramp_check.blockSignals(False)

    @QtCore.Slot(str, object)
    def update_ramprate(self, value: str | float, dt: datetime.datetime):
        self._raw_data[4] = [dt, str(value).strip()]
        self.rate_spin.blockSignals(True)
        self.rate_spin.setValue(float(value))
        self.rate_spin.blockSignals(False)

    @QtCore.Slot()
    def apply_ramp(self):
        self.sigRampChanged.emit(
            int(self.ramp_check.isChecked()), self.rate_spin.value()
        )

    @QtCore.Slot()
    def apply_setpoint(self):
        self.sigSetpChanged.emit(self.target_spin.value())

    @QtCore.Slot(float)
    def set_target(self, value: float):
        self.target_spin.setValue(value)

    @QtCore.Slot(int)
    def _format_output(self, value: int):
        self.pbar.setFormat(f"{value / 100:.2f}%")


class HeaterWidget(HeaterWidgetGUI):
    sigSETP = QtCore.Signal(str, object)
    sigRAMP = QtCore.Signal(str, object)
    sigHTR = QtCore.Signal(str, object)
    sigRANGE = QtCore.Signal(str, object)
    sigOUTMODE = QtCore.Signal(str, object)

    def __init__(
        self,
        *args,
        instrument: VISAThread | None = None,
        output: str,
        loop: str | None = None,
        use_cmode: bool = False,
        **kwargs,
    ):
        super().__init__(*args, instrument=instrument, **kwargs)
        self.output = output
        if loop is None:
            loop = self.output
        self.loop = loop

        self._curr_spin: QtWidgets.QDoubleSpinBox | None = None

        self._use_cmode: bool = use_cmode

        self.sigSETP.connect(self.update_setpoint)
        self.sigRAMP.connect(self.update_ramp)
        self.sigHTR.connect(self.update_output)
        self.sigRANGE.connect(self.update_range)
        self.sigOUTMODE.connect(self.update_outmode_or_cmode)

        self.sigSetpChanged.connect(self.change_setpoint)
        self.sigRampChanged.connect(self.change_ramp)
        self.sigRangeChanged.connect(self.change_range)
        self.sigUpdateTarget.connect(self.target_current)

    @property
    def curr_spin(self) -> QtWidgets.QDoubleSpinBox | None:
        if self._curr_spin is not None:
            return self._curr_spin()
        return None

    @curr_spin.setter
    def curr_spin(self, value: QtWidgets.QDoubleSpinBox):
        self._curr_spin = weakref.ref(value)

    @QtCore.Slot(str, object)
    def update_ramp(self, value: str, dt: datetime.datetime):
        st, rate = value.split(",")
        self.update_rampst(st, dt)
        self.update_ramprate(rate, dt)

    @QtCore.Slot(str, object)
    def update_outmode_or_cmode(self, value: str, dt: datetime.datetime):
        if self._use_cmode:
            self.update_cmode(value, dt)
        else:
            self.update_outmode(value, dt)

    @QtCore.Slot(str, object)
    def update_cmode(self, value: str, dt: datetime.datetime):
        # CMODE command parsed assuming 331 controller
        mode = value.strip()
        match int(mode):
            case 1:
                # Manual PID (default)
                self.sigPIDInputSet.emit(self, 1)
            case 2:
                self.set_heater_mode("Zone")
            case 3:
                self.set_heater_mode("Open Loop")
            case 4:
                self.set_heater_mode("AutoTune PID")
            case 5:
                self.set_heater_mode("AutoTune PI")
            case 6:
                self.set_heater_mode("AutoTune P")

    @QtCore.Slot(str, object)
    def update_outmode(self, value: str, dt: datetime.datetime):
        # OUTMODE command parsed assuming 336 controller
        mode, input_number, _ = value.split(",")
        match int(mode):
            case 0:
                # Heater output off
                self.set_heater_mode("Heater OFF")
            case 1:
                # Closed loop PID (default)
                self.sigPIDInputSet.emit(self, int(input_number))
            case 2:
                self.set_heater_mode("Zone")
            case 3:
                self.set_heater_mode("Open Loop")
            case 4:
                self.set_heater_mode("Monitor")
            case 5:
                self.set_heater_mode("Warmup")

    @QtCore.Slot(float)
    def change_setpoint(self, value: float):
        cmd = "SETP "
        cmd += ",".join([self.loop, str(value)])
        self.instrument.request_write(cmd)
        self.trigger_update()

    @QtCore.Slot(int, float)
    def change_ramp(self, state: int, rate: float):
        cmd = "RAMP "
        cmd += ",".join([self.loop, str(state), str(rate)])
        self.instrument.request_write(cmd)
        self.trigger_update()

    @QtCore.Slot(int)
    def change_range(self, value: int):
        cmd = "RANGE "
        if len(self.output) > 0:
            cmd += f"{self.output},"
        cmd += str(value)
        self.instrument.request_write(cmd)
        self.trigger_update()

    @QtCore.Slot()
    def target_current(self):
        if self.curr_spin is not None:
            self.set_target(self.curr_spin.value())

    def trigger_outmode_update(self):
        if self._use_cmode:
            self.instrument.request_query(
                f"CMODE? {self.loop}".strip(), self.sigOUTMODE, loglevel=5
            )
        else:
            self.instrument.request_query(
                f"OUTMODE? {self.loop}".strip(), self.sigOUTMODE, loglevel=5
            )

    def trigger_update(self):
        self.instrument.request_query(
            f"SETP? {self.loop}".strip(), self.sigSETP, loglevel=5
        )
        self.instrument.request_query(
            f"RAMP? {self.loop}".strip(), self.sigRAMP, loglevel=5
        )
        self.instrument.request_query(
            f"HTR? {self.output}".strip(), self.sigHTR, loglevel=5
        )
        self.instrument.request_query(
            f"RANGE? {self.output}".strip(), self.sigRANGE, loglevel=5
        )


class ReadingWidgetGUI(VISAWidgetBase):
    def __init__(
        self,
        *args,
        inputs: Sequence[str],
        names: Sequence[str] | None = None,
        hide_srdg: bool = True,
        decimals: int = 3,
        **kwargs,
    ):
        # Do not reconnect on error, reconnecting will be handled by CommandWidget
        kwargs["reconnect_on_error"] = False
        super().__init__(*args, **kwargs)

        if names is not None and len(names) != len(inputs):
            raise ValueError("Length of names must match length of inputs")

        self.inputs = inputs

        self.setLayout(QtWidgets.QGridLayout())
        self.name_labels: list[QtWidgets.QLabel] = []
        self.krdg_spins: list[QtWidgets.QDoubleSpinBox] = []
        self.srdg_spins: list[QtWidgets.QDoubleSpinBox] = []
        self.krdg_units: list[QtWidgets.QLabel] = []
        self.srdg_units: list[QtWidgets.QLabel] = []

        boldfont = QtGui.QFont()
        boldfont.setBold(True)
        smallfont = QtGui.QFont()
        smallfont.setPointSize(9)
        smallerfont = QtGui.QFont()
        smallerfont.setPointSize(8)

        for i in range(len(self.inputs)):
            input_label = QtWidgets.QLabel(self.inputs[i])
            input_label.setFont(boldfont)

            name_label = QtWidgets.QLabel()
            name_label.setFont(smallfont)
            name_label.setWordWrap(True)
            name_label.setMinimumWidth(100)

            krdg_spin = QtWidgets.QDoubleSpinBox()
            krdg_spin.setReadOnly(True)
            krdg_spin.setDecimals(decimals)
            krdg_spin.setRange(0.0, 500.0)
            krdg_spin.setButtonSymbols(krdg_spin.ButtonSymbols.NoButtons)
            krdg_spin.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            krdg_spin.setMinimumWidth(55)

            krdg_unit = QtWidgets.QLabel("[K]")
            krdg_unit.setFont(smallerfont)

            srdg_spin = QtWidgets.QDoubleSpinBox()
            srdg_spin.setReadOnly(True)
            srdg_spin.setDecimals(5)
            srdg_spin.setRange(0.0, 10000.0)
            srdg_spin.setButtonSymbols(srdg_spin.ButtonSymbols.NoButtons)
            srdg_spin.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

            srdg_unit = QtWidgets.QLabel("[SU]")
            srdg_unit.setFont(smallerfont)

            name_label.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.MinimumExpanding,
                QtWidgets.QSizePolicy.Policy.Preferred,
            )

            for w in (input_label, krdg_unit, srdg_unit):
                w.setSizePolicy(
                    QtWidgets.QSizePolicy.Policy.Maximum,
                    QtWidgets.QSizePolicy.Policy.Preferred,
                )
            for w in (krdg_spin, srdg_spin):
                w.setSizePolicy(
                    QtWidgets.QSizePolicy.Policy.Maximum,
                    QtWidgets.QSizePolicy.Policy.Fixed,
                )

            self.layout().addWidget(input_label, i, 0, 1, 1)
            self.layout().addWidget(name_label, i, 1, 1, 3)
            self.layout().addWidget(krdg_spin, i, 4, 1, 2)
            self.layout().addWidget(krdg_unit, i, 6, 1, 1)
            self.layout().addWidget(srdg_spin, i, 7, 1, 2)
            self.layout().addWidget(srdg_unit, i, 9, 1, 1)

            # self.layout().addWidget(input_label, 2 * i, 0, 2, 1)
            # self.layout().addWidget(name_label, 2 * i, 1, 2, 3)
            # self.layout().addWidget(krdg_spin, 2 * i, 4, 1, 2)
            # self.layout().addWidget(srdg_spin, 2 * i + 1, 4, 1, 2)
            # self.layout().addWidget(krdg_unit, 2 * i, 6, 1, 1)
            # self.layout().addWidget(srdg_unit, 2 * i + 1, 6, 1, 1)

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
        return self.srdg_spins[0].isVisible()

    # @property
    # def krdg_dict(self) -> dict[str, float]:
    #     return {
    #         label.text(): spin.value()
    #         for label, spin in zip(self.name_labels, self.krdg_spins)
    #     }

    # @property
    # def srdg_dict(self) -> dict[str, float]:
    #     return {
    #         f"{label.text()} (SU)": spin.value()
    #         for label, spin in zip(self.name_labels, self.srdg_spins)
    #     }

    def set_srdg_visible(self, visible: bool):
        for i in range(len(self.krdg_spins)):
            self.srdg_spins[i].setVisible(visible)
            self.srdg_units[i].setVisible(visible)
            # if visible:
            #     self.layout().addWidget(self.krdg_spins[i], 2 * i, 4, 1, 2)
            #     self.layout().addWidget(self.krdg_units[i], 2 * i, 6, 1, 1)
            # else:
            #     self.layout().addWidget(self.krdg_spins[i], 2 * i, 4, 2, 2)
            #     self.layout().addWidget(self.krdg_units[i], 2 * i, 6, 2, 1)

    def update_names(self, names: list[str]):
        self.names = names
        for label, name in zip(self.name_labels, names, strict=True):
            label.setText(name)

    def update_krdg(self, readings: list[float]):
        for spin, value in zip(self.krdg_spins, readings, strict=True):
            spin.setValue(value)

    def update_srdg(self, readings: list[float]):
        for spin, value in zip(self.srdg_spins, readings, strict=True):
            spin.setValue(value)


class ReadingWidget(ReadingWidgetGUI):
    sigKRDG = QtCore.Signal(str, object)
    sigSRDG = QtCore.Signal(str, object)

    def __init__(
        self,
        *args,
        instrument: VISAThread | None = None,
        inputs: Sequence[str],
        num_raw_readings: int,
        indexer: slice | None = None,
        krdg_command: str | None = None,
        srdg_command: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, instrument=instrument, inputs=inputs, **kwargs)
        self.indexer = indexer
        if krdg_command is None:
            krdg_command = "KRDG? 0"
        if srdg_command is None:
            srdg_command = "SRDG? 0"
        self.krdg_command = krdg_command
        self.srdg_command = srdg_command

        # number of values returned by krdg_command and srdg_command
        self.n_raw = int(num_raw_readings)

        self._raw_krdg: tuple[datetime.datetime, list[str]] = (
            datetime.datetime.now(),
            ["nan"] * self.n_raw,
        )
        self._raw_srdg: tuple[datetime.datetime, list[str]] = (
            datetime.datetime.now(),
            ["nan"] * self.n_raw,
        )

        self.sigKRDG.connect(self.update_krdg)
        self.sigSRDG.connect(self.update_srdg)

    def get_raw_krdg(
        self, threshold: float, return_datetime: bool = False
    ) -> list[str] | tuple[list[str], datetime.datetime]:
        dt, vals = self._raw_krdg

        now = datetime.datetime.now()
        if now - dt > datetime.timedelta(seconds=threshold):
            out = ["nan"] * len(vals)
        else:
            out = vals

        if len(out) >= 9:
            log.critical(
                "KRDG size mismatch for our controllers, raw krdg read as %s",
                self._raw_krdg[1],
            )

        if return_datetime:
            return out, dt
        return out

    def get_raw_srdg(self, threshold: float) -> list[str]:
        dt, vals = self._raw_srdg

        now = datetime.datetime.now()
        if now - dt > datetime.timedelta(seconds=threshold):
            return ["nan"] * len(vals)
        return vals

    def trigger_update(self):
        self.instrument.request_query(self.krdg_command, self.sigKRDG, loglevel=5)
        self.instrument.request_query(self.srdg_command, self.sigSRDG, loglevel=5)

    @QtCore.Slot(str, object)
    def update_krdg(self, message: str, dt: datetime.datetime):
        krdg_raw: list[str] = message.strip().split(",")
        if self.indexer is not None:
            krdg_raw = krdg_raw[self.indexer]

        self._raw_krdg = (dt, krdg_raw)
        super().update_krdg([float(t) for t in krdg_raw])

    @QtCore.Slot(str, object)
    def update_srdg(self, message: str, dt: datetime.datetime):
        srdg_raw: list[str] = message.strip().split(",")
        if self.indexer is not None:
            srdg_raw = srdg_raw[self.indexer]

        self._raw_srdg = (dt, srdg_raw)
        super().update_srdg([float(t) for t in srdg_raw])


class CommandWidget(
    *uic.loadUiType(os.path.join(os.path.dirname(__file__), "command.ui"))
):
    sigWrite = QtCore.Signal(str)
    sigQuery = QtCore.Signal(str)
    sigReply = QtCore.Signal(str, object)

    def __init__(self, *args, instrument: VISAThread | None = None, **kwargs):
        super().__init__(
            *args, instrument=instrument, reconnect_on_error=True, **kwargs
        )
        self.setupUi(self)

        self.write_btn.clicked.connect(self.write)
        self.query_btn.clicked.connect(self.query)

        self.sigReply.connect(self.set_reply)

    @property
    def input(self) -> str:
        return self.text_in.toPlainText().strip()

    @QtCore.Slot(str, object)
    def set_reply(self, message: str, _: datetime.datetime):
        self.text_out.setPlainText(message)

    @QtCore.Slot()
    def write(self):
        self.instrument.request_write(self.input)

    @QtCore.Slot()
    def query(self):
        self.instrument.request_query(self.input, self.sigReply)


class PlottingWidget(
    *uic.loadUiType(os.path.join(os.path.dirname(__file__), "plotting.ui"))
):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle("1KARPES Temperature Controller")
        self.plotwidget = pg.PlotWidget(
            plotItem=DynamicPlotItemTwiny(
                legendtableview=self.legendtable,
                plot_cls=XDateSnapCurvePlotDataItem,
                xformat=XDateSnapCurvePlotDataItem.format_x,
                yformat=XDateSnapCurvePlotDataItem.format_y,
                **kwargs,
            )
        )
        self.centralWidget().layout().addWidget(self.plotwidget)

        self.plotItem.showGrid(x=True, y=True, alpha=1.0)
        self.plotItem.setAxisItems({"bottom": pg.DateAxisItem()})
        self.plotItem.setup_twiny()

        self.plotItem.getAxis("left").setLabel("Temperature")
        self.plotItem.getAxis("right").setLabel("Pump & Shields")

        self.actioncursor.triggered.connect(self.plotItem.toggle_cursor)
        self.actioncentercursor.triggered.connect(self.plotItem.center_cursor)
        self.actionsnap.triggered.connect(self.plotItem.toggle_snap)
        self.actionlogy1.triggered.connect(lambda: self.plotItem.toggle_logy(False))
        self.actionlogy2.triggered.connect(lambda: self.plotItem.toggle_logy(True))

    def set_datalist(self, *args, **kwargs):
        self.plotItem.set_datalist(*args, **kwargs)

    @property
    def plotItem(self) -> DynamicPlotItemTwiny:
        return self.plotwidget.plotItem


class HeatSwitchWidget(
    *uic.loadUiType(os.path.join(os.path.dirname(__file__), "heatswitch.ui"))
):
    sigVOUTRead = QtCore.Signal(str, object)
    sigVSETRead = QtCore.Signal(str, object)
    sigSTATUSRead = QtCore.Signal(str, object)

    def __init__(self, instrument: VISAThread | None = None, parent=None):
        super().__init__(parent, instrument=instrument)
        self.setupUi(self)
        self._raw_vout: tuple[datetime.datetime, str] = (None, "nan")

        self.check.toggled.connect(self.change_output)

        self.dial.valueChanged.connect(self.dial_changed)
        self.apply_btn.clicked.connect(self.change_vset)

        self.sigVOUTRead.connect(self.update_vout)
        self.sigVSETRead.connect(self.update_vset)
        self.sigSTATUSRead.connect(self.update_status)

        self.dial.setEnabled(self.check.isChecked())

    def get_raw_vout(self, threshold: float) -> str:
        now = datetime.datetime.now()
        if self._raw_vout[0] is None or now - self._raw_vout[0] > datetime.timedelta(
            seconds=threshold
        ):
            return "nan"
        return self._raw_vout[1]

    @QtCore.Slot(str, object)
    def update_vout(self, value: str | float, dt: datetime.datetime):
        self._raw_vout = (dt, str(value).strip())
        self.vout_spin.setValue(float(self._raw_vout[1]))

        if not self.dial.isSliderDown():
            self.dial.blockSignals(True)
            self.dial.setValue(round(float(value) * 100))
            self.dial.blockSignals(False)

    @QtCore.Slot(str, object)
    def update_vset(self, value: str | float, _: datetime.datetime):
        self.vset_spin.setValue(float(value))

    @QtCore.Slot(str, object)
    def update_status(self, message: str, _: datetime.datetime):
        # 0: 0 CC, 1 CV (when output is on)
        # 4: Beep
        # 5: OCP
        # 6: Output
        # 7: OVP

        # Char to integer ASCII
        byte_value = ord(message[0])
        # Bitwise AND with shifting
        res: list[bool] = [bool((byte_value >> i) & 1) for i in range(8)]

        self.setDisabled(False)
        if res[6] != self.check.isChecked():
            self.dial.setEnabled(res[6])
            self.check.blockSignals(True)
            self.check.setChecked(res[6])
            self.check.blockSignals(False)

    @QtCore.Slot(int)
    def dial_changed(self, value: int):
        self.spin.setValue(value / 100)
        self.change_vset()

    @QtCore.Slot()
    def change_vset(self):
        self.instrument.request_write(f"VSET1:{self.spin.value():.3f}")
        self.trigger_update()

    @QtCore.Slot()
    def change_output(self):
        value = 1 if self.check.isChecked() else 0
        self.instrument.request_write(f"OUT{value}")
        self.dial.setEnabled(self.check.isChecked())
        self.trigger_update()

    def trigger_update(self):
        self.instrument.request_query("STATUS?", self.sigSTATUSRead, loglevel=5)
        self.instrument.request_query("VSET1?", self.sigVSETRead, loglevel=5)
        self.instrument.request_query("VOUT1?", self.sigVOUTRead, loglevel=5)


if __name__ == "__main__":
    qapp = QtWidgets.QApplication(sys.argv)
    # qapp.setStyle("Fusion")

    # import tomlkit
    # import erlab.io

    # with open(
    #     "/Users/khan/Source/python/1KARPES_DAQ/src/tempcontrol/config.toml", "r"
    # ) as f:
    #     config = tomlkit.load(f)
    # names = (
    #     config["general"]["names_336"]
    #     + config["general"]["names_218"]
    #     + config["general"]["names_331"]
    # )
    # ds = erlab.io.load_hdf5("/Users/khan/test_log.h5")
    # x = ds["Time"].astype(int).values * 1e-9
    # yvals = [ds[n].values for n in names]

    # # win = HeaterWidget()
    # win = PlottingWidget(twinx_labels=["He pump", "1K Cold finger"])
    # win.plotItem.set_labels(names)
    # win.plotItem.set_datalist(x, yvals)
    win = HeatSwitchWidget()

    # print(win.plotItem.plots[0].curve.parentItem().parentItem().parentItem())

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
