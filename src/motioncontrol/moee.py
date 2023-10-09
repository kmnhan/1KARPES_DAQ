"""Python interface for the MMC1 piezomotor controller"""
import enum
import logging
import socket
import sys
import time

from qtpy import QtCore, QtGui, QtWidgets, uic

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
# handler = logging.FileHandler("motion_logs.log", encoding="utf-8")
# handler = logging.NullHandler()
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)


class MMStatus(enum.Enum):
    MOVING = 1
    DONE = 2
    ABORTED = 3
    ERROR = 4


class MMCommand(enum.IntEnum):
    DISCONNECT = 0
    RESET = 1
    SETSIGNUM = 2
    SETSIGAMP = 3
    SETSIGDIR = 4
    SETSIGTIME = 5
    MESCAP = 6
    READCAP = 7
    SENDSIGONCE = 8
    CHKSIGBUSY = 9
    READPOS = 10
    READSIGNUM = 12
    READSIGAMP = 13
    READSIGDIR = 14
    READSIGTIME = 15
    MVFWD = 16
    MVBWD = 17


class MMThread(QtCore.QThread):
    """A `QtCore.QThread` that handles communication with the motor controllers.

    Signals
    -------
    sigMoveStarted(channel)

    sigMoveFinished(channel)

    sigCapRead(channel, value)

    sigPosRead(channel, value)s

    """

    sigMoveStarted = QtCore.Signal(int)
    sigMoveFinished = QtCore.Signal(int)
    sigCapRead = QtCore.Signal(int, float)
    sigPosRead = QtCore.Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.moving: bool = False
        self.initialized: bool = False

    def connect(self, host: str | None = None, port: int = 5000):
        if host is None:
            host = "192.168.0.210"

        log.debug(f"connecting to host {host} on port {port}")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect((host, port))

        log.debug("connected")

    def disconnect(self):
        self.mmsend(MMCommand.DISCONNECT)
        self.mmrecv()
        log.debug("disconnected, closing socket...")
        self.sock.close()
        log.debug("socket closed")

    def mmsend(self, command: int, channel: int = 0, value: int = 0):
        tmp, x1 = divmod(value, 256)
        tmp, x2 = divmod(tmp, 256)
        x4, x3 = divmod(tmp, 256)
        msg = bytes([command, channel, int(x1), int(x2), int(x3), int(x4)])
        totalsent = 0
        while totalsent < 6:
            sent = self.sock.send(msg[totalsent:])
            if sent == 0:
                log.critical("Socket connection broken.")
            totalsent = totalsent + sent
        log.debug(f"sent cmd {command} to ch {channel} with val {value}")

    def mmrecv(self):
        raw = self.sock.recv(4)
        val = sum([raw[i] * 256**i for i in range(4)])
        log.debug(f"received value {val} {raw}")
        return val

    def get_capacitance(self, channel: int) -> float:
        """Return capacitance in uF."""
        self.mmsend(MMCommand.MESCAP, channel)
        time.sleep(1)
        self.mmrecv()
        self.mmsend(MMCommand.READCAP, channel)
        val = self.mmrecv() / 0.89 * 1e-3
        self.sigCapRead.emit(channel, val)
        return val

    def get_frequency(self, channel: int) -> float:
        """Return current frequency."""
        self.mmsend(MMCommand.READSIGTIME, channel)
        sigtime = self.mmrecv()
        return 50000000 / sigtime
        # return 1 / (sigtime / 50 / 1000)

    def get_amplitude(self, channel: int) -> float:
        """Return current signal amplitude (voltage)."""
        self.mmsend(MMCommand.READSIGAMP, channel)
        amp = self.mmrecv()
        return amp / 65535 * 60.0

    def get_position(self, channel: int) -> int:
        """Return raw position integer."""
        while True:
            self.mmsend(MMCommand.CHKSIGBUSY)
            if self.mmrecv() == 0:
                break
        time.sleep(1e-3)
        self.mmsend(MMCommand.READPOS, channel)
        val = self.mmrecv()
        self.sigPosRead.emit(channel, val)
        return val

    @QtCore.Slot(int, int, int, int, int)
    def initialize_parameters(
        self, channel: int, target: int, frequency: int, amplitude: int, threshold: int
    ):
        log.info(
            f"Initializing parameters {channel} {target} {frequency} {amplitude} {threshold}"
        )
        self._channel = int(channel)
        self._target = int(target)
        if (frequency >= 50) and (frequency <= 500):
            self._sigtime = round(50000000 / frequency)
        else:
            self._sigtime = int(50000000 / 200)
        self._amplitude = min((65535, round(amplitude * 65535 / 60)))
        self._threshold = int(abs(threshold))
        self.initialized = True

    def run(self):
        if not self.initialized:
            log.warning("MMSocket was not initialized prior to execution.")
            return

        self.sigMoveStarted.emit(self._channel)
        self.moving = True
        try:
            # reset
            self.mmsend(MMCommand.RESET, self._channel)
            self.mmrecv()

            # set amplitude
            self.mmsend(MMCommand.SETSIGAMP, self._channel, self._amplitude)
            self.mmrecv()

            # set frequency
            self.mmsend(MMCommand.SETSIGTIME, self._channel, self._sigtime)
            self.mmrecv()

            delta_list: list[int] = [self._target - self.get_position(self._channel)]
            direction: int | None = None

            while True:
                if abs(delta_list[-1]) < self._threshold:
                    # position has converged
                    break
                if len(delta_list) >= 20:
                    # check whether last 20 delta are alternating in sign
                    # if so, position is not converging, we need a larger threshold
                    s0 = delta_list[-20] >= 0
                    alternating = True
                    for n in delta_list[-20:]:
                        s1 = n < 0
                        if s0 == s1:
                            alternating = False
                            break
                        s0 = s1
                    if alternating:
                        log.warning(
                            f"Current threshold {self._threshold} is too small,"
                            " position does not converge. Terminating."
                        )
                        break

                direction_old = direction
                if delta_list[-1] > 0:
                    direction = 0  # backwards
                else:
                    direction = 1  # forwards
                if direction_old != direction:
                    log.info(f"changing direction to {direction}")
                    self.mmsend(MMCommand.SETSIGDIR, self._channel, direction)
                    self.mmrecv()

                # send signal & read position
                self.mmsend(MMCommand.SENDSIGONCE, self._channel)
                self.mmrecv()
                pos = self.get_position(self._channel)
                delta_list.append(self._target - pos)

                if not self.moving:
                    break
        except Exception:
            log.exception("Exception while moving!")
        self.moving = False
        self.initialized = False
        self.sigMoveFinished.emit(self._channel)


if __name__ == "__main__":
    soc = MMThread()
    soc.connect()
    try:
        # soc.get_capacitance(1)
        # soc.get_capacitance(2)
        # soc.get_capacitance(3)
        # soc.get_amplitude(1)
        # soc.get_amplitude(2)
        # soc.get_amplitude(3)
        soc.get_frequency(1)
        soc.get_frequency(2)
        soc.get_frequency(3)

        soc.mmsend(MMCommand.DISCONNECT)

    except Exception as e:
        print("error!", e)

        soc.mmsend(MMCommand.DISCONNECT)

    soc.sock.close()
