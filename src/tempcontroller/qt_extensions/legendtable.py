__all__ = ["LegendTableView"]

from collections.abc import Sequence

import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets


class LegendTableModel(QtCore.QAbstractTableModel):
    sigCurveToggled = QtCore.Signal(int, bool)
    sigColorChanged = QtCore.Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled: list[bool] = []
        self._entries: Sequence[str] = []
        self.colors: list[QtGui.QColor] = []

    @property
    def entries(self) -> Sequence[str]:
        return self._entries

    @entries.setter
    def entries(self, values: Sequence[str]):
        if list(self._entries) == list(values):
            return
        self.beginResetModel()
        entries_old = list(self._entries)
        enabled_old = list(self.enabled)

        self._entries = values
        self.enabled = [True] * len(self._entries)

        for i, ent in enumerate(self._entries):
            try:
                old_ind = entries_old.index(ent)
                self.enabled[i] = enabled_old[old_ind]
            except ValueError:
                pass

        if len(self.colors) < len(self._entries):
            n_required = len(self._entries) - len(self.colors)
            self.colors += n_required * [QtGui.QColor("white")]
        elif len(self.colors) > len(self._entries):
            self.colors = self.colors[: len(self._entries)]
        self.endResetModel()

    def flags(self, index):
        if index.column() == 0:
            return super().flags(index) | QtCore.Qt.ItemIsUserCheckable
        elif index.column() == 2:
            return super().flags(index) | QtCore.Qt.ItemIsEditable
        else:
            return super().flags(index)

    def data(self, index, role):
        if index.column() == 0:
            if role == QtCore.Qt.ItemDataRole.CheckStateRole:
                if self.enabled[index.row()]:
                    return QtCore.Qt.CheckState.Checked
                else:
                    return QtCore.Qt.CheckState.Unchecked
        elif role == QtCore.Qt.ItemDataRole.DisplayRole:
            if index.column() == 1:
                return str(self.entries[index.row()])
        elif role == QtCore.Qt.ItemDataRole.UserRole:
            if index.column() == 2:
                return self.colors[index.row()]
        elif role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            if index.column() == 1:
                return int(
                    QtCore.Qt.AlignmentFlag.AlignLeft
                    | QtCore.Qt.AlignmentFlag.AlignVCenter
                )
            else:
                return int(QtCore.Qt.AlignmentFlag.AlignCenter)

    def setData(self, index, value, role=QtCore.Qt.ItemDataRole.EditRole):
        if index.column() == 0:
            if role == QtCore.Qt.ItemDataRole.CheckStateRole:
                if value == QtCore.Qt.CheckState.Checked.value:
                    self.enabled[index.row()] = True
                else:
                    self.enabled[index.row()] = False
                self.sigCurveToggled.emit(index.row(), self.enabled[index.row()])
                self.dataChanged.emit(
                    index, index, [QtCore.Qt.ItemDataRole.CheckStateRole]
                )
        elif index.column() == 2:
            if role == QtCore.Qt.ItemDataRole.EditRole:
                self.colors[index.row()] = value
                self.dataChanged.emit(index, index, [QtCore.Qt.ItemDataRole.EditRole])
                self.sigColorChanged.emit(index.row(), value)
        return True

    def rowCount(self, index=None):
        return len(self._entries)

    def columnCount(self, index=None):
        return 3


class ColorButtonDelegate(QtWidgets.QItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)

    def createEditor(self, parent, option, index):
        editor = pg.ColorButton(parent, padding=10)
        editor.setFlat(True)
        editor.setStyleSheet("background-color: rgba(255, 255, 255, 0); ")
        editor.sigColorChanged.connect(self.commitAndCloseEditor)
        return editor

    def setEditorData(self, editor, index):
        model_value = index.model().data(index, QtCore.Qt.ItemDataRole.UserRole)
        editor.setColor(model_value, finished=False)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.color(mode="qcolor"), QtCore.Qt.EditRole)

    def commitAndCloseEditor(self):
        editor = self.sender()
        self.commitData.emit(editor)
        self.closeEditor.emit(editor)


class LegendTableView(QtWidgets.QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        model = LegendTableModel(parent)
        self.setModel(model)
        self.setSelectionBehavior(self.SelectionBehavior.SelectRows)
        self.setItemDelegateForColumn(2, ColorButtonDelegate(parent))
        self.verticalHeader().hide()
        self.horizontalHeader().hide()
        self.setShowGrid(False)
        self.model().modelReset.connect(self._update_view)

    def _update_view(self):
        for i in range(self.model().rowCount()):
            self.openPersistentEditor(self.model().createIndex(i, 2))
        self.resizeColumnsToContents()
        self.setFixedWidth(
            sum([self.columnWidth(i) for i in range(self.model().columnCount())])
            + self.verticalScrollBar().sizeHint().width()
            + 2
        )

    @property
    def enabled(self) -> list[bool]:
        return self.model().enabled

    @property
    def colors(self) -> list[QtGui.QColor]:
        return self.model().colors

    @property
    def entries(self) -> Sequence[str]:
        return self.model().entries

    def set_items(self, items: Sequence[str]):
        self.model().entries = items

    def set_enabled(self, index: int, value: bool):
        self.model().setData(
            index=self.model().createIndex(index, 0),
            value=(
                QtCore.Qt.CheckState.Checked.value
                if value
                else QtCore.Qt.CheckState.Unchecked.value
            ),
            role=QtCore.Qt.ItemDataRole.CheckStateRole,
        )

    def set_color(self, index: int, color: QtGui.QColor):
        self.model().setData(
            index=self.model().createIndex(index, 2),
            value=color,
            role=QtCore.Qt.ItemDataRole.EditRole,
        )
