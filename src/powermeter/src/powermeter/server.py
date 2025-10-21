import io
import logging
import pickle
import threading
import typing

import zmq
from qtpy import QtCore

logger = logging.getLogger("powermeter.server")

PORT: int = 42666


_UNSET = object()


def _send_multipart(sock: zmq.Socket, obj: typing.Any, **kwargs) -> None:
    """Send a Python object as a multipart ZeroMQ message using pickle protocol 5."""
    buffers: list[pickle.PickleBuffer] = []  # out-of-band frames will be appended here
    bio = io.BytesIO()
    p = pickle.Pickler(bio, protocol=5, buffer_callback=buffers.append)
    p.dump(obj)
    header = memoryview(bio.getbuffer())
    frames = [header] + [memoryview(b) for b in buffers]
    sock.send_multipart(frames, copy=False, **kwargs)


def _recv_multipart(sock: zmq.Socket, **kwargs) -> typing.Any:
    """Receive a multipart ZeroMQ message and reconstruct the Python object."""
    parts = sock.recv_multipart(copy=False, **kwargs)
    return pickle.loads(parts[0].buffer, buffers=(p.buffer for p in parts[1:]))


class PowermeterServerThread(QtCore.QThread):
    sigRequestData = QtCore.Signal(float, float)

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)

        self._ret_val: typing.Any = _UNSET

        self._running = threading.Event()
        self._mutex = QtCore.QMutex()
        self._cv = QtCore.QWaitCondition()

    @QtCore.Slot(object)
    def set_return_value(self, value: typing.Any) -> None:
        with QtCore.QMutexLocker(self._mutex):
            self._ret_val = value
            self._cv.wakeAll()

    def run(self) -> None:
        try:
            ctx = zmq.Context.instance()
            _socket = ctx.socket(zmq.REP)
            _socket.setsockopt(zmq.SNDHWM, 0)
            _socket.setsockopt(zmq.RCVHWM, 0)
            _socket.setsockopt(zmq.LINGER, 0)
            _socket.bind(f"tcp://*:{PORT}")
            logger.info("ZMQ server bound")

            poller = zmq.Poller()
            poller.register(_socket, zmq.POLLIN)
            self._running.set()

            while self._running.is_set() and not self.isInterruptionRequested():
                events = dict(poller.poll(100))
                if _socket in events and events[_socket] & zmq.POLLIN:
                    try:
                        msg = _socket.recv(flags=zmq.NOBLOCK)
                        data = pickle.loads(msg)
                        if isinstance(data, tuple | list) and len(data) == 2:
                            a, b = data
                            self.sigRequestData.emit(float(a), float(b))
                            with QtCore.QMutexLocker(self._mutex):
                                while self._ret_val is _UNSET:
                                    self._cv.wait(self._mutex)
                                ret = self._ret_val
                                self._ret_val = _UNSET
                            _send_multipart(_socket, ret)
                        else:
                            logger.warning("Invalid message format: %r", data)
                    except Exception as exc:
                        logger.warning("Failed to process message: %s", exc)
        except Exception:
            logger.exception("ZMQ server error")
        finally:
            try:
                _socket.close(0)
            finally:
                self._running.clear()
                logger.info("ZMQ server stopped")

    def stop(self) -> None:
        self._running.clear()
        self.requestInterruption()


def get_flux_data(start_ts: float, end_ts: float, timeout_ms: int = 5000) -> typing.Any:
    ctx = zmq.Context.instance()

    sock: zmq.Socket = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
    try:
        logger.info("Connecting to server...")
        sock.connect(f"tcp://localhost:{PORT}")
    except Exception:
        logger.exception("Failed to connect to server")
    else:
        payload = pickle.dumps(
            (float(start_ts), float(end_ts)), protocol=pickle.HIGHEST_PROTOCOL
        )
        sock.send(payload)
        try:
            response = _recv_multipart(sock)
        except Exception:
            logger.exception("Failed to receive response from server")
        else:
            return response
    finally:
        sock.close()
