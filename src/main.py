import multiprocessing
import sys
from multiprocessing import shared_memory

import numpy as np
import zmq
from qtpy import QtCore, QtWidgets, uic

from attributeserver.widgets import SlitWidget
from attributeserver.server import AttributeServer


class MainWindowGUI(*uic.loadUiType("main.ui")):

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("1KARPES Data Acquisition")


class MainWindow(MainWindowGUI):
    def __init__(self):
        super().__init__()
        # Initialize shared memory
        self.shm_slit = shared_memory.SharedMemory(name="slit_idx", create=True, size=1)
        self.shm_seq = shared_memory.SharedMemory(name="seq_start", create=True, size=8)

    def closeEvent(self, *args, **kwargs):
        self.shm_slit.close()
        self.shm_slit.unlink()
        self.shm_seq.close()
        self.shm_seq.unlink()
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)
    qapp.setStyle("Fusion")
    win = MainWindow()
    win.show()
    win.activateWindow()
    qapp.exec()
