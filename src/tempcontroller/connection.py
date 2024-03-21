import datetime
import logging
import queue
import threading
import time

import pyvisa
from qtpy import QtCore, QtWidgets

log = logging.getLogger("tempctrl")


class RequestHandler:
    """A wrapper around pyvisa that limits the rate of requests.

    Parameters
    ----------
    resource_name (str)
        The name of the resource.
    interval_ms (int)
        The interval in milliseconds between requests.
    **kwargs
        Additional keyword arguments to be passed to the resource.

    """

    def __init__(self, resource_name: str, interval_ms: int = 50, **kwargs):
        self.resource_name = resource_name
        self.interval_ms = interval_ms
        self._resource_kwargs = kwargs

    def open(self):
        """Opens the pyvisa resource."""
        self.inst = pyvisa.ResourceManager().open_resource(
            self.resource_name, **self._resource_kwargs
        )
        self._last_update = time.perf_counter_ns()

    def wait_time(self):
        """Wait until the interval between requests has passed."""
        while (time.perf_counter_ns() - self._last_update) <= self.interval_ms * 1e3:
            time.sleep(1e-4)

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
        """Reads data from the resource.

        This is not very likely to be used. It may cause problems due to the wait time.
        Use `query` instead.
        """
        self.wait_time()
        res = self.inst.read(*args, **kwargs)
        self._last_update = time.perf_counter_ns()
        log.log(loglevel, f"{self.resource_name}  ->  {res}")
        return res

    def close(self):
        self.inst.close()


class VISAThread(QtCore.QThread):
    """A QThread subclass for handling communication with a VISA instrument.

    This class provides a thread for sending queries and write commands to a VISA device.
    It uses a queue to manage the requests and executes them in a separate thread.
    """

    sigWritten = QtCore.Signal(object)
    sigQueried = QtCore.Signal(object)
    sigVisaError = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.controller = RequestHandler(*args, **kwargs)
        self.stopped = threading.Event()
        self.stopped.set()
        self.mutex: QtCore.QMutex | None = None

    def lock_mutex(self):
        """Locks the mutex to ensure thread safety."""
        if self.mutex is not None:
            self.mutex.lock()

    def unlock_mutex(self):
        """Unlocks the mutex to release the lock."""
        if self.mutex is not None:
            self.mutex.unlock()

    def request_query(
        self,
        message: str,
        signal: QtCore.SignalInstance,
        *,
        loglevel: int = logging.DEBUG,
    ):
        """Add a query request to the queue.

        Parameters
        ----------
        message : str
            The query message to send.
        signal : QtCore.SignalInstance
            The signal to emit the result of the query when the query is complete.
        loglevel : int, optional
            The log level for the query. Defaults to `logging.DEBUG`.
        """
        self.lock_mutex()
        self.queue.put((message, signal, loglevel))
        self.unlock_mutex()

    def request_write(
        self,
        message: str,
        *,
        loglevel: int = logging.DEBUG,
    ):
        """Add a write request to the queue.

        Parameters
        ----------
        message : str
            The message to write.
        loglevel : int, optional
            The log level for the write. Defaults to `logging.DEBUG`.
        """
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
                        time_written = datetime.datetime.now()
                        self.controller.write(message, loglevel=loglevel)
                    except (pyvisa.VisaIOError, pyvisa.InvalidSession) as e:
                        self.sigVisaError.emit(e)
                    else:
                        self.sigWritten.emit(time_written)
                else:  # Query
                    try:
                        time_queried = datetime.datetime.now()
                        rep = self.controller.query(message, loglevel=loglevel)
                    except (pyvisa.VisaIOError, pyvisa.InvalidSession) as e:
                        self.sigVisaError.emit(e)
                    else:
                        reply_signal.emit(rep)
                        self.sigQueried.emit(time_queried)
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


class VISAWidgetBase(QtWidgets.QWidget):
    """Base class for widgets that connect to VISA instruments.

    This class provides a base implementation for widgets that interact with VISA
    instruments. It handles the connection to the instrument, error handling, and
    reconnection logic.

    Parameters
    ----------
    instrument
        The VISA instrument thread to connect to. It can be set later using the
        `instrument` property setter.
    reconnect_on_error
        Flag indicating whether to automatically reconnect on error. Defaults to True.
    reconnect_interval
        The interval in ms between reconnection attempts. Defaults to 3000.

    Attributes
    ----------
    instrument : VISAThread or None
        The VISA instrument thread currently connected to.

    """

    def __init__(
        self,
        *args,
        instrument: VISAThread | None = None,
        reconnect_on_error: bool = True,
        reconnect_interval: int = 3000,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        self._instrument: VISAThread | None = None
        self.instrument = instrument

        self._reconnect_on_error: bool = reconnect_on_error
        self._reconnect_interval: int = reconnect_interval

    @property
    def instrument(self) -> VISAThread | None:
        return self._instrument

    @instrument.setter
    def instrument(self, instrument: VISAThread | None):
        if self._instrument is not None:
            self._instrument.sigWritten.disconnect(self.write_complete)
            self._instrument.sigQueried.disconnect(self.query_complete)
            self._instrument.sigVisaError.disconnect(self.connection_error)
        self._instrument: VISAThread | None = instrument
        if self._instrument is not None:
            self._instrument.sigWritten.connect(self.write_complete)
            self._instrument.sigQueried.connect(self.query_complete)
            self._instrument.sigVisaError.connect(self.connection_error)

    @QtCore.Slot()
    def write_complete(self):
        """Slot called when a write operation is completed."""
        if not self.isEnabled():
            self.setEnabled(True)

    @QtCore.Slot()
    def query_complete(self):
        """Slot called when a query operation is completed."""
        if not self.isEnabled():
            self.setEnabled(True)

    @QtCore.Slot(object)
    def connection_error(self, error: Exception):
        """Slot called when an error occurs.

        This function disables the widget and tries to reconnect.
        It also logs the error message.

        Parameters
        ----------
        error
            The error object or message.
        """
        self.setDisabled(True)
        log.error(
            f"Failed to communicate with {self.instrument.controller.resource_name}: "
            f"{error}"
        )
        if self._reconnect_on_error:
            restart_visathread(self.instrument, self._reconnect_interval)
