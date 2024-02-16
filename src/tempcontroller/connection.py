import pyvisa
from qtpy import QtCore, QtGui, QtWidgets, uic
import time
import threading
import queue


class RequestHandler:
    def __init__(self, resource_name: str, baud_rate: int | None = None):
        self.resource_name = resource_name
        self._baud_rate = baud_rate

    def open(self):
        self.inst = pyvisa.ResourceManager().open_resource(self.resource_name)
        if self._baud_rate is not None:
            self.inst.baud_rate = self._baud_rate
        self._last_update = time.perf_counter_ns()

    def wait_time(self):
        while (time.perf_counter_ns() - self._last_update) < 50000:
            time.sleep(1e-3)

    def write(self, *args, **kwargs):
        self.wait_time()
        res = self.inst.write(*args, **kwargs)
        self._last_update = time.perf_counter_ns()
        return res

    def query(self, *args, **kwargs):
        self.wait_time()
        res = self.inst.query(*args, **kwargs)
        self._last_update = time.perf_counter_ns()
        return res

    def read(self, *args, **kwargs):
        self.wait_time()
        res = self.inst.query(*args, **kwargs)
        self._last_update = time.perf_counter_ns()
        return res

    def close(self):
        self.inst.close()


class LakeshoreThread(QtCore.QThread):

    sigWritten = QtCore.Signal()
    sigQueried = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.controller = RequestHandler(*args, **kwargs)
        self.stopped = threading.Event()
        self.mutex: QtCore.QMutex | None = None

    def lock_mutex(self):
        if self.mutex is not None:
            self.mutex.lock()

    def unlock_mutex(self):
        if self.mutex is not None:
            self.mutex.unlock()

    def request_query(self, message: str, signal: QtCore.SignalInstance):
        self.lock_mutex()
        self.queue.put((message, signal))
        self.unlock_mutex()

    def request_write(self, message: str):
        self.lock_mutex()
        self.queue.put((message, None))
        self.unlock_mutex()

    def run(self):
        self.mutex = QtCore.QMutex()
        self.queue = queue.Queue()

        self.stopped.clear()

        self.controller.open()

        while not self.stopped.is_set():
            if not self.queue.empty():
                message, reply_signal = self.queue.get()
                if reply_signal is None:  # Write only
                    self.controller.write(message)
                    self.sigWritten.emit()
                else:  # Query
                    rep = self.controller.query(message)
                    reply_signal.emit(rep)
                    self.sigQueried.emit()
                self.queue.task_done()
            time.sleep(1e-3)

        self.controller.close()