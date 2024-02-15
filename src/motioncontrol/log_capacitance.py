import csv
import numpy as np
import datetime
import multiprocessing
import os
import sys
import threading
import time

import pyqtgraph as pg
from moee import MMCommand, MMThread
from qtpy import QtCore, QtGui, QtWidgets

FILENAME = "D:/MotionController/logs_capacitance/240215_capacitance.csv"


# def write_log(content: list[str]):
#     while True:
#         try:
#             with open(FILENAME, "a", newline="") as f:
#                 writer = csv.writer(f)
#                 writer.writerow(content)
#         except PermissionError:
#             continue
#         else:
#             print(content)
#             break
class LoggingProc(multiprocessing.Process):
    def __init__(self):
        super().__init__()
        self._stopped = multiprocessing.Event()
        self.queue = multiprocessing.Manager().Queue()

    def run(self):
        self._stopped.clear()
        while not self._stopped.is_set():
            time.sleep(0.2)

            if self.queue.empty():
                continue

            # retrieve message from queue
            dt, msg = self.queue.get()
            try:
                with open(FILENAME, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([dt.isoformat()] + msg)
            except PermissionError:
                # put back the retrieved message in the queue
                n_left = int(self.queue.qsize())
                self.queue.put((dt, msg))
                for _ in range(n_left):
                    self.queue.put(self.queue.get())
                continue

    def stop(self):
        n_left = int(self.queue.qsize())
        if n_left != 0:
            print(
                f"Failed to write {n_left} log "
                + ("entries:" if n_left > 1 else "entry:")
            )
            for _ in range(n_left):
                dt, msg = self.queue.get()
                print(f"{dt} | {msg}")
        self._stopped.set()
        self.join()

    def add_content(self, dt: datetime.datetime, content: str | list[str]):
        if isinstance(content, str):
            content = [content]
        self.queue.put((dt, content))


class Widget(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLayout(QtWidgets.QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)

        self.plotwidget = pg.PlotWidget()
        self.plotwidget.plotItem.setAxisItems({"bottom": pg.DateAxisItem()})
        self.plots = (
            pg.PlotDataItem(pen="c"),
            pg.PlotDataItem(pen="m"),
            pg.PlotDataItem(pen="y"),
        )
        for plot in self.plots:
            self.plotwidget.plotItem.addItem(plot)

        controls = QtWidgets.QWidget()
        self.hbox = QtWidgets.QHBoxLayout()
        controls.setLayout(self.hbox)

        # self.button = QtWidgets.QPushButton("Start")
        self.check = QtWidgets.QCheckBox("Logging Enabled")
        self.hbox.addWidget(self.check)
        self.check.toggled.connect(self.toggle_logging)

        self.layout().addWidget(self.plotwidget)
        self.layout().addWidget(controls)

        # Setup logging
        self.log_writer = LoggingProc()
        self.log_writer.start()

        self.timer = QtCore.QTimer(self)
        # self.timer.setInterval(1000 * 2 * 60)  # 2 minutes
        self.timer.setInterval(1000 * 5)  # 5 secs
        self.timer.timeout.connect(self.update_data)

        self.soc = MMThread()
        self.soc.connect("192.168.0.210")

        self.datetimes: list[datetime.datetime] = []
        self.caplist: list[list[float]] = [[], [], []]

    @QtCore.Slot()
    def toggle_logging(self):
        if self.check.isChecked():
            self.timer.start()
        else:
            self.timer.stop()

    def update_data(self):
        self.datetimes.append(datetime.datetime.now())

        for i, ch in enumerate((1, 2, 3)):
            self.caplist[i].append(self.soc.get_capacitance(ch))

        self.log_writer.add_content(
            self.datetimes[-1], [str(cap[-1]) for cap in self.caplist]
        )

        for plot, cap in zip(self.plots, self.caplist):
            cap_arr = np.asarray(cap)
            cap_arr[cap_arr < 0.0025] = np.nan
            plot.setData([t.timestamp() for t in self.datetimes], cap_arr)

    def closeEvent(self, *args, **kwargs):
        self.soc.disconnect()
        self.log_writer.stop()
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":

    qapp = QtWidgets.QApplication(sys.argv)
    # qapp.setStyle("Fusion")

    win = Widget()
    win.show()
    win.activateWindow()
    qapp.exec()

    # soc = MMThread()
    # soc.connect()

    # def save_capacitance():
    #     cap_list = [datetime.datetime.now().isoformat()]
    #     for i in (1, 2, 3):
    #         cap_list.append(str(soc.get_capacitance(i)))
    #     write_log(cap_list)

    # try:
    #     t = threading.Timer(30.0, hello)
    #     # some code

    #     soc.mmsend(MMCommand.DISCONNECT)
    # except Exception as e:
    #     print("error!", e)
    #     soc.mmsend(MMCommand.DISCONNECT)

    # soc.sock.close()
