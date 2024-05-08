import os
import sys
import threading
import time
from multiprocessing import shared_memory

from qtpy import QtCore, QtGui, QtWidgets, uic

from attributeserver.getter import SLIT_TABLE, get_pressure_list, get_temperature_list
from attributeserver.server import AttributeServer

try:
    os.chdir(sys._MEIPASS)
except:  # noqa: E722
    pass


class SlitTableModel(QtCore.QAbstractTableModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def data(self, index, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return str(SLIT_TABLE[index.row()][index.column()])
        elif role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return int(
                QtCore.Qt.AlignmentFlag.AlignCenter
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )

    def headerData(self, section, orientation, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if orientation == QtCore.Qt.Orientation.Horizontal:
                return ("#", "width (mm)", "aperture")[section]
        elif role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return int(
                QtCore.Qt.AlignmentFlag.AlignCenter
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )

    def rowCount(self, index):
        return len(SLIT_TABLE)

    def columnCount(self, index):
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
            sum([view.columnWidth(i) for i in range(model.columnCount(0))])
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

        while not self.stopped.is_set():
            try:
                temp = [str(float(v)) for v in get_temperature_list()]
            except FileNotFoundError:
                # Shared memory not present, temperature controller may be off
                temp = [""] * 3
            except ValueError as e:
                # Something went wrong while reading shared memory, try again
                print(f"Error while reading shared temperature: {e}")
                continue
            self.sigTUpdate.emit(temp)

            try:
                pressure: list[str] = get_pressure_list()
            except FileNotFoundError:
                pressure: list[str] = [""]
            except ValueError as e:
                print(f"Error while reading shared pressure: {e}")
                continue
            self.sigPUpdate.emit(pressure)
            time.sleep(0.1)


class StatusWidget(*uic.loadUiType("attributeserver/status.ui")):
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
