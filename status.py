import sys

import zmq
from qtpy import QtCore, QtWidgets, uic

from constants import CRYO_PORT, MG15_PORT, SLIT_TABLE
from servers import PressureServer, SlitServer, TemperatureServer


class SlitTable(QtCore.QAbstractTableModel):
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


class MainWindow(*uic.loadUiType("status.ui")):
    sigSlitChanged = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("1KARPES Status")

        # setup slit combobox and slit table
        model = SlitTable()
        view = QtWidgets.QTableView()
        view.setCornerButtonEnabled(False)
        view.verticalHeader().hide()
        view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.slit_combo.setModel(model)
        self.slit_combo.setView(view)
        view.resizeColumnsToContents()
        view.setMinimumWidth(
            sum([view.columnWidth(i) for i in range(model.columnCount(0))])
        )

        # initialize servers
        self.server_controls = tuple(getattr(self, f"sc{i}") for i in range(3))
        self.server_controls[0].set_server(
            SlitServer, value=self.slit_combo.currentIndex()
        )
        self.server_controls[1].set_server(TemperatureServer)
        self.server_controls[2].set_server(PressureServer)
        for sc, name in zip(self.server_controls, ("Slit", "Cryo", "MG15")):
            sc.setLabel(name)

        # connect signals (slit)
        self.slit_combo.currentIndexChanged.connect(self.set_slit_index)
        self.sigSlitChanged.connect(self.server_controls[0].server.set_value)

        # start slit server
        self.start_servers()

        # setup timer
        self.client_timer = QtCore.QTimer(self)
        self.client_timer.setInterval(round(self.updatetime_spin.value() * 1000))
        self.client_timer.timeout.connect(self.update_info)
        self.updatetime_spin.valueChanged.connect(
            lambda val: self.client_timer.setInterval(round(val * 1000))
        )
        self.update_info()
        self.client_timer.start()

    def get_response(self, port: int):
        context = zmq.Context()
        socket: zmq.Socket = context.socket(zmq.REQ)
        socket.connect(f"tcp://localhost:{port}")
        socket.send(b"")
        return socket.recv_json()

    @QtCore.Slot()
    def update_info(self):
        data = self.get_response(CRYO_PORT)
        self.TA.setText(data["1K Cold finger"])
        self.TB.setText(data["Sample stage"])
        self.TC.setText(data["Tilt bracket"])
        data = self.get_response(MG15_PORT)
        self.pressure.setText(f"{float(data['IG Main']):.3e}")

    @QtCore.Slot()
    def set_slit_index(self):
        self.sigSlitChanged.emit(self.slit_combo.currentIndex())

    def start_servers(self):
        for sc in self.server_controls:
            sc.start_server()

    def stop_servers(self):
        for sc in self.server_controls:
            sc.stop_server()

    def closeEvent(self, event):
        self.client_timer.stop()
        self.stop_servers()
        super().closeEvent(event)


if __name__ == "__main__":
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)

    win = MainWindow()
    win.show()
    win.activateWindow()

    qapp.exec()
