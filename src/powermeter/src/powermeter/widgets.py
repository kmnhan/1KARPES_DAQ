import datetime
import os

from qtpy import QtCore, QtGui, QtWidgets, uic

from powermeter.connection import VISAThread


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
