from collections.abc import Sequence

import qtawesome as qta
from qtpy import QtCore, QtGui, uic


class StautsIconWidget(qta.IconWidget):
    def __init__(self, *icons: Sequence[str | dict | QtGui.QIcon], parent=None):
        super().__init__(parent=parent)
        self._icons: list[QtGui.QIcon] = []
        for icn in icons:
            if isinstance(icn, str):
                self._icons.append(qta.icon(icn))
            elif isinstance(icn, dict):
                self._icons.append(qta.icon(**icn))
            elif isinstance(icn, QtGui.QIcon):
                self._icons.append(icn)
            else:
                raise TypeError(f"Unrecognized icon type `{type(icn)}`")
        self._state: int = 0
        self.setState(self._state)

    def setText(self, *args, **kwargs):
        return

    def icons(self) -> Sequence[QtGui.QIcon]:
        return self._icons

    def state(self) -> int:
        return self._state

    def nstates(self) -> int:
        return len(self.icons())

    def setState(self, state: int):
        self._state = int(state)
        self.setIcon(self.icons()[self._state])

    def setIconSize(self, size: QtCore.QSize, update: bool = False):
        super().setIconSize(size)
        if update:
            self.update()

    def update(self, *args, **kwargs):
        self._icon = self.icons()[self._state]
        return super().update(*args, **kwargs)


class ServerStatus(StautsIconWidget):
    def __init__(self, parent=None):
        super().__init__(
            qta.icon("mdi6.close-circle", color="#e50000"),
            qta.icon("mdi6.checkbox-marked-circle", color="#15b01a"),
            parent=parent,
        )
        self.setIconSize(QtCore.QSize(20, 20), update=True)

    def setState(self, value: bool):
        super().setState(1 if value else 0)


class ServerControlWidget(*uic.loadUiType("server_status.ui")):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setRestartEnabled(True)
        self.restart_btn.clicked.connect(self.restart_server)
        self.restart_btn.setText("")
        self.restart_btn.setIcon(qta.icon("mdi6.restart"))

        self.server: QtCore.QThread | None = None

    def restartEnabled(self) -> bool:
        return self._restart_enabled

    def setRestartEnabled(self, value: bool):
        self._restart_enabled = bool(value)
        self.restart_btn.setDisabled(not self.restartEnabled())

    def setLabel(self, *args, **kwargs):
        self.server_label.setText(*args, **kwargs)

    def set_server(self, server: type[QtCore.QThread], *args, **kwargs):
        self.server = server(*args, **kwargs)

        self.server.sigSocketBound.connect(lambda: self.status_label.setState(True))
        self.server.sigSocketClosed.connect(lambda: self.status_label.setState(False))

    def start_server(self):
        print("starting server...")
        self.server.start()

    def stop_server(self, timeout: int | None = None):
        print("stopping server...")
        self.server.running = False
        if timeout is None:
            return self.server.wait()
        else:
            return self.server.wait(timeout)

    def restart_server(self):
        if not self.stop_server(5000):
            self.server.terminate()
            self.server.wait()
        self.start_server()

    def closeEvent(self, event):
        if not self.stop_server(2000):
            self.server.terminate()
            self.server.wait()
        super().closeEvent(event)
