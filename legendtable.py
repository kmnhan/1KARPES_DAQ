import datetime
import os
import platform
import sys
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyqtgraph as pg
import seaborn as sns
from qtpy import QtCore, QtGui, QtWidgets, uic
from collections.abc import Iterable

import erlab.interactive.colors


class LegendTableModel(QtCore.QAbstractTableModel):
    sigCurveToggled = QtCore.Signal(int)
    sigColorChanged = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled: list[bool] = []
        self._entries: Iterable[str] = []
        self.colors: list[QtGui.QColor] = []

    @property
    def entries(self) -> Iterable[str]:
        return self._entries

    @entries.setter
    def entries(self, values: Iterable[str]):
        self.beginResetModel()
        entries_old = list(self._entries)
        enabled_old = list(self.enabled)

        self._entries = values
        self.enabled = [False] * len(self._entries)

        for i, ent in enumerate(self._entries):
            try:
                old_ind = entries_old.index(ent)
                self.enabled[i] = enabled_old[old_ind]
            except ValueError:
                pass

        self.colors = [
            erlab.interactive.colors.color_to_QColor(clr)
            for clr in sns.color_palette("bright", len(self._entries))
        ]

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

    def setData(self, index, value, role=QtCore.Qt.ItemDataRole.EditRole):
        if index.column() == 0:
            if role == QtCore.Qt.ItemDataRole.CheckStateRole:
                if value == QtCore.Qt.CheckState.Checked.value:
                    self.enabled[index.row()] = True
                else:
                    self.enabled[index.row()] = False
                self.sigCurveToggled.emit(index.row())
                self.dataChanged.emit(
                    index, index, [QtCore.Qt.ItemDataRole.CheckStateRole]
                )
        elif index.column() == 2:
            if role == QtCore.Qt.ItemDataRole.EditRole:
                self.colors[index.row()] = value
                self.dataChanged.emit(index, index, [QtCore.Qt.ItemDataRole.EditRole])
                self.sigColorChanged.emit(index.row())
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
        return editor

    def setEditorData(self, editor, index):
        model_value = index.model().data(index, QtCore.Qt.ItemDataRole.UserRole)
        editor.setColor(model_value, finished=True)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.color(mode="qcolor"), QtCore.Qt.EditRole)


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

    def set_items(self, items: Iterable[str]):
        self.model().entries = items
