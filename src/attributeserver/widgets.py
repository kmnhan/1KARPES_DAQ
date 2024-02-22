from multiprocessing import shared_memory

from getter import SLIT_TABLE
from qtpy import QtCore, QtWidgets


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
        self.slit_combo.setView(view)
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
