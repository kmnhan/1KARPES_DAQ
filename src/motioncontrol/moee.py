"""Python interface for the MMC1 piezomotor controller"""
import enum
import logging
import socket
import sys
import time

from qtpy import QtCore, QtGui, QtWidgets, uic

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
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
    sigDeltaChanged = QtCore.Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.moving: bool = False
        self.initialized: bool = False

    def connect(self, host: str | None = None, port: int = 5000):
        if host is None:
            host = "192.168.0.210"

        log.info(f"connecting to host {host} on port {port}")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect((host, port))

        log.info("connected")
        self.reset()

    def disconnect(self):
        self.mmsend(MMCommand.DISCONNECT)
        self.mmrecv()
        log.info("disconnected, closing socket...")
        self.sock.close()
        log.info("socket closed")

    def mmsend(self, command: int, channel: int = 0, value: int = 0):
        """Send a command over the socket to the controller.

        Parameters
        ----------
        command
            `MMCommand` to send.
        channel
            Channel to send.
        value
            Integer value to send. The value is automatically converted to a uint8 array
            of length 4, which combined with the command and the channel results in a
            message of length 6.

        """
        tmp, x1 = divmod(value, 256)
        tmp, x2 = divmod(tmp, 256)
        x4, x3 = divmod(tmp, 256)
        msg = bytes([int(command), int(channel), int(x1), int(x2), int(x3), int(x4)])
        totalsent = 0
        while totalsent < 6:
            sent = self.sock.send(msg[totalsent:])
            if sent == 0:
                log.critical("Socket connection broken.")
            totalsent = totalsent + sent
        log.debug(f"sent cmd {command} to ch {channel} with val {value}")

    def mmrecv(self) -> int:
        """Receives a message over the socket from the controller.

        Returns
        -------
        int
            Received integer.

        """
        raw = self.sock.recv(4)
        val = sum([raw[i] * 256**i for i in range(4)])
        log.debug(f"received value {val} {tuple(raw)}")
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
        """Return current frequency in Hz."""
        self.mmsend(MMCommand.READSIGTIME, channel)
        sigtime = self.mmrecv()
        return 50000000 / sigtime

    def set_frequency(self, channel: int, frequency: int | float):
        if (frequency >= 50) and (frequency <= 500):
            sigtime = round(50000000 / frequency)
        else:
            sigtime = int(50000000 / 200)
        log.info(f"setting frequency to {50000000 / sigtime}")
        self.mmsend(MMCommand.SETSIGTIME, int(channel), sigtime)
        return self.mmrecv()

    def get_amplitude(self, channel: int) -> float:
        """Return current signal amplitude (voltage)."""
        self.mmsend(MMCommand.READSIGAMP, channel)
        amp = self.mmrecv()
        return amp / 65535 * 60.0

    def set_amplitude(self, channel: int, amplitude: int | float):
        sigamp = min((65535, round(amplitude * 65535 / 60)))
        log.info(f"setting amplitude to {sigamp / 65535 * 60.0}")
        self.mmsend(MMCommand.SETSIGAMP, int(channel), sigamp)
        return self.mmrecv()

    def set_direction(self, channel: int, direction: int):
        log.info(f"setting direction to {direction}")
        self.mmsend(MMCommand.SETSIGDIR, int(channel), direction)
        return self.mmrecv()

    def reset(self):
        self.mmsend(MMCommand.RESET)
        return self.mmrecv()

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
        self._sigtime = frequency
        self._amplitude = amplitude
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
            self.reset()

            # set amplitude
            self.set_amplitude(self._channel, self._amplitude)

            # set frequency
            self.set_frequency(self._channel, self._sigtime)

            delta_list: list[int] = [self._target - self.get_position(self._channel)]
            direction: int | None = None
            amplitude_adjusted = 0

            while True:
                self.sigDeltaChanged.emit(self._channel, delta_list)
                if abs(delta_list[-1]) < self._threshold:
                    # position has converged
                    break
                    #

                if len(delta_list) >= 50:
                    # check for alternating sign in delta
                    # the `n_alt` most recent delta are alternating in sign
                    s0 = delta_list[-1] >= 0
                    n_alt = 0
                    for n in reversed(delta_list[-50:]):
                        s1 = n < 0
                        if s0 == s1:
                            break
                        n_alt += 1
                        s0 = s1
                    if n_alt >= 4:
                        # recent 4 delta are alternating
                        if self._amplitude > 18:
                            amplitude_adjusted += 1

                            decay_constant = 5
                            new_amp = (self._amplitude - 18) * 2.718281828459045 ** (
                                -amplitude_adjusted / decay_constant
                            ) + 18
                        else:
                            new_amp = 18
                        self.set_amplitude(self._channel, new_amp)
                    if n_alt == 50:
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
                    self.set_direction(self._channel, direction)

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
