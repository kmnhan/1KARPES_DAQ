import contextlib
import logging
import os
import sys
import threading
import time
import typing
from multiprocessing import shared_memory

from qtpy import QtCore, QtGui, QtWidgets, uic

from erpes_daq.attributeserver.getter import (
    SLIT_TABLE,
    get_pressure_strings,
    get_temperature_strings,
)
from erpes_daq.attributeserver.server import AttributeServer

with contextlib.suppress(Exception):
    os.chdir(sys._MEIPASS)

log = logging.getLogger("attrs")


class SlitTableModel(QtCore.QAbstractTableModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def data(
        self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole
    ) -> typing.Any:
        if not index.isValid():
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return str(SLIT_TABLE[index.row()][index.column()])
        if role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return int(
                QtCore.Qt.AlignmentFlag.AlignCenter
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
        return None

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.ItemDataRole.DisplayRole,
    ) -> typing.Any:
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if orientation == QtCore.Qt.Orientation.Horizontal:
                return ("#", "width (mm)", "aperture")[section]
        elif role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return int(
                QtCore.Qt.AlignmentFlag.AlignCenter
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
        return None

    def rowCount(self, index: QtCore.QModelIndex | None = None) -> int:
        return len(SLIT_TABLE)

    def columnCount(self, index: QtCore.QModelIndex | None = None) -> int:
        return 3


class SlitWidget(QtWidgets.QComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        model = SlitTableModel()
        view = QtWidgets.QTableView()
        view.setCornerButtonEnabled(False)
        view.verticalHeader().hide()
        view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )

        self.setModel(model)
        self.setView(view)
        view.resizeColumnsToContents()
        view.setMinimumWidth(
            sum(view.columnWidth(i) for i in range(model.columnCount(0)))
        )

        self.currentIndexChanged.connect(self.update_sharedmem)

    @QtCore.Slot()
    def update_sharedmem(self):
        try:
            shm = shared_memory.SharedMemory(name="slit_idx")
        except FileNotFoundError:
            pass
        else:
            shm.buf[0] = int(self.currentIndex())
            shm.close()


class StatusThread(QtCore.QThread):
    sigTUpdate = QtCore.Signal(object)
    sigPUpdate = QtCore.Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.stopped = threading.Event()

    def run(self):
        self.stopped.clear()

        log.info("Status thread started")

        while not self.stopped.is_set():
            try:
                temp = [str(float(v)) for v in get_temperature_strings()]
            except FileNotFoundError:
                log.exception(
                    "Shared memory not found, check temperature control software"
                )
                temp = [""] * 3
            except ValueError:
                log.exception("Error while reading temperature from shared memory")
                time.sleep(0.5)
                continue

            self.sigTUpdate.emit(temp)

            try:
                pressure: list[str] = get_pressure_strings()
            except FileNotFoundError:
                log.exception("Shared memory not found, check mg15 software")
                pressure: list[str] = [""]
            except ValueError:
                log.exception("Error while reading pressure from shared memory")
                time.sleep(0.5)
                continue

            self.sigPUpdate.emit(pressure)
            time.sleep(0.5)

        log.info("Status thread stopped")


class StatusWidget(
    *uic.loadUiType(os.path.join(os.path.dirname(__file__), "status.ui"))
):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # Start attribute server
        self.attr_server = AttributeServer()
        self.attr_server.start()

        self.update_thread = StatusThread()
        self.update_thread.sigTUpdate.connect(self.update_temperature)
        self.update_thread.sigPUpdate.connect(self.update_pressure)
        self.update_thread.start()

    @QtCore.Slot(object)
    def update_temperature(self, temp: list[str]):
        self.line0.setText(temp[0])
        self.line1.setText(temp[1])
        self.line2.setText(temp[2])

    @QtCore.Slot(object)
    def update_pressure(self, pressure: list[str]):
        self.line3.setText(pressure[0])

    def closeEvent(self, event: QtGui.QCloseEvent):
        # Stop update thread
        self.update_thread.stopped.set()
        self.update_thread.wait()

        # Stop attribute server
        self.attr_server.stopped.set()
        self.attr_server.wait()
        super().closeEvent(event)
