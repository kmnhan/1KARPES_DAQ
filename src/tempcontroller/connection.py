import logging
import queue
import threading
import time

import pyvisa
from qtpy import QtCore

log = logging.getLogger("tempctrl")


class RequestHandler:
    def __init__(self, resource_name: str, interval_ms: int = 50, **kwargs):
        self.resource_name = resource_name
        self.interval_ms = interval_ms
        self._resource_kwargs = kwargs

    def open(self):
        self.inst = pyvisa.ResourceManager().open_resource(
            self.resource_name, **self._resource_kwargs
        )
        self._last_update = time.perf_counter_ns()

    def wait_time(self):
        while (time.perf_counter_ns() - self._last_update) <= self.interval_ms * 1e3:
            time.sleep(5e-4)

    def write(self, *args, loglevel: int = logging.DEBUG, **kwargs):
        self.wait_time()
        res = self.inst.write(*args, **kwargs)
        self._last_update = time.perf_counter_ns()
        log.log(loglevel, f"{self.resource_name}  <-  {args[0]}")
        return res

    def query(self, *args, loglevel: int = logging.DEBUG, **kwargs):
        self.wait_time()
        res = self.inst.query(*args, **kwargs)
        self._last_update = time.perf_counter_ns()
        log.log(loglevel, f"{self.resource_name}  <-  {args[0]}")
        log.log(loglevel, f"{self.resource_name}  ->  {res}")
        return res

    def read(self, *args, loglevel: int = logging.DEBUG, **kwargs):
        self.wait_time()
        res = self.inst.query(*args, **kwargs)
        self._last_update = time.perf_counter_ns()
        log.log(loglevel, f"{self.resource_name}  ->  {res}")
        log.log()
        return res

    def close(self):
        self.inst.close()


class VISAThread(QtCore.QThread):

    sigWritten = QtCore.Signal()
    sigQueried = QtCore.Signal()
    sigVisaError = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.controller = RequestHandler(*args, **kwargs)
        self.stopped = threading.Event()
        self.stopped.set()
        self.mutex: QtCore.QMutex | None = None

    def lock_mutex(self):
        if self.mutex is not None:
            self.mutex.lock()

    def unlock_mutex(self):
        if self.mutex is not None:
            self.mutex.unlock()

    def request_query(
        self,
        message: str,
        signal: QtCore.SignalInstance,
        *,
        loglevel: int = logging.DEBUG,
    ):
        self.lock_mutex()
        self.queue.put((message, signal, loglevel))
        self.unlock_mutex()

    def request_write(self, message: str, *, loglevel: int = logging.DEBUG):
        self.lock_mutex()
        self.queue.put((message, None, loglevel))
        self.unlock_mutex()

    def run(self):
        self.mutex = QtCore.QMutex()
        self.queue = queue.Queue()
        self.stopped.clear()
        try:
            self.controller.open()
        except pyvisa.VisaIOError as e:
            self.sigVisaError.emit(e)

        while not self.stopped.is_set():
            if not self.queue.empty():
                message, reply_signal, loglevel = self.queue.get()
                if reply_signal is None:  # Write only
                    try:
                        self.controller.write(message, loglevel=loglevel)
                    except (pyvisa.VisaIOError, pyvisa.InvalidSession) as e:
                        self.sigVisaError.emit(e)
                    else:
                        self.sigWritten.emit()
                else:  # Query
                    try:
                        rep = self.controller.query(message, loglevel=loglevel)
                    except (pyvisa.VisaIOError, pyvisa.InvalidSession) as e:
                        self.sigVisaError.emit(e)
                    else:
                        reply_signal.emit(rep)
                        self.sigQueried.emit()
                self.queue.task_done()
            time.sleep(1e-3)

        self.controller.close()


def start_visathread(thread: VISAThread):
    thread.start()
    while thread.stopped.is_set():
        time.sleep(1e-4)


def stop_visathread(thread: VISAThread):
    thread.stopped.set()
    thread.wait()


def restart_visathread(thread: VISAThread, msec: int = 0):
    stop_visathread(thread)
    QtCore.QTimer.singleShot(int(msec), lambda: start_visathread(thread))
