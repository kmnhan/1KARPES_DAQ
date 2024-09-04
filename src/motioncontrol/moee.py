"""Python interface for the MMC1 piezomotor controller."""

import enum
import logging
import socket
import sys
import threading
import time
from multiprocessing import shared_memory

from qtpy import QtCore, QtGui, QtWidgets

log = logging.getLogger("moee")
log.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
_fh = logging.FileHandler(f"D:/daq_logs/{log.name}.log", mode="a", encoding="utf-8")
_sh = logging.StreamHandler(sys.stdout)
_fh.setFormatter(_fmt)
_sh.setFormatter(_fmt)
log.addHandler(_fh)
log.addHandler(_sh)


class MMStatus(enum.IntEnum):
    Moving = 1
    Done = 2
    Aborted = 3
    Error = 4


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
    SETRELAY = 11
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
    sigMoveStarted(channel, unique_id)

    sigMoveFinished(channel, unique_id)

    sigCapRead(channel, value)

    sigPosRead(channel, value)

    sigAvgPosRead(channel, value)

    """

    sigMoveStarted = QtCore.Signal(int, str)
    sigMoveFinished = QtCore.Signal(int, str)
    sigCapRead = QtCore.Signal(int, float)
    sigPosRead = QtCore.Signal(int, int)
    sigAvgPosRead = QtCore.Signal(int, float)
    sigDeltaChanged = QtCore.Signal(int, object, object)

    def __init__(self, index: int, parent=None, compat: bool = False):
        super().__init__(parent)
        self.index: int = index
        self.stopped: bool = False
        self.initialized: bool = False
        self.compat = compat

    def connect(self, host: str, port: int = 5000):
        log.info(f"ctrl{self.index} connecting to host {host} on port {port}")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect((host, port))

        log.info(f"ctrl{self.index} connected")
        self.reset()

    def disconnect(self):
        self.mmsend(MMCommand.DISCONNECT)
        self.mmrecv()
        log.info(f"ctrl{self.index} disconnected, closing socket...")
        self.sock.close()
        log.info(f"ctrl{self.index} socket closed")

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
        log.debug(
            f"ctrl{self.index} sent cmd {command} to ch {channel} with val {value}"
        )

    def mmrecv(self) -> int:
        """Receives a message over the socket from the controller.

        Returns
        -------
        int
            Received integer.

        """
        raw = self.sock.recv(4)
        val = sum(raw[i] * 256**i for i in range(4))
        log.debug(f"ctrl{self.index} received value {val} {tuple(raw)}")
        return val

    def get_capacitance(self, channel: int) -> float:
        """Return capacitance in uF."""
        self.set_relay(channel, 0)
        time.sleep(0.5)

        self.mmsend(MMCommand.MESCAP, channel)
        self.mmrecv()
        if self.compat:
            time.sleep(0.2)

        self.mmsend(MMCommand.READCAP, channel)
        val = self.mmrecv() / 0.89 * 1e-3

        self.sigCapRead.emit(channel, val)

        self.set_relay(channel, 1)
        return val

    def get_frequency(self, channel: int) -> float:
        """Return current frequency in Hz."""
        self.mmsend(MMCommand.READSIGTIME, channel)
        sigtime = self.mmrecv()

        if self.compat:
            return 50000000 / sigtime
        else:
            usec = sigtime / 50
            freq = 1e6 / usec
            return freq

    def set_frequency(self, channel: int, frequency: int | float):
        if self.compat:
            if (frequency >= 50) and (frequency <= 500):
                sigtime = round(50000000 / frequency)
            else:
                sigtime = int(50000000 / 200)
            log.info(f"ctrl{self.index} setting frequency to {50000000 / sigtime}")
        else:
            period_usec = 1e6 / frequency
            sigtime = round(period_usec * 50)
            log.info(f"ctrl{self.index} setting frequency to {1e6/(sigtime/50)}")
        self.mmsend(MMCommand.SETSIGTIME, int(channel), sigtime)
        return self.mmrecv()

    def get_amplitude(self, channel: int) -> float:
        """Return current signal amplitude (voltage)."""
        self.mmsend(MMCommand.READSIGAMP, channel)
        amp = self.mmrecv()
        return amp / 65535 * 60.0

    def set_amplitude(self, channel: int, amplitude: int | float):
        sigamp = min((65535, round(amplitude * 65535 / 60)))
        log.info(f"ctrl{self.index} setting amplitude to {sigamp / 65535 * 60.0:.2f}")
        self.mmsend(MMCommand.SETSIGAMP, int(channel), sigamp)
        return self.mmrecv()

    def set_direction(self, channel: int, direction: int):
        log.info(f"ctrl{self.index} setting direction to {direction}")
        self.mmsend(MMCommand.SETSIGDIR, int(channel), int(direction))
        return self.mmrecv()

    def set_pulse_train(self, channel: int, train: int):
        log.info(f"ctrl{self.index} setting pulse train {train}")
        self.mmsend(MMCommand.SETSIGNUM, int(channel), int(train))
        return self.mmrecv()

    def set_relay(self, channel: int, state: int):
        if self.compat:
            return

        if state not in (0, 1):
            raise ValueError("State must be 0 or 1.")
        log.info(f"ctrl{self.index} setting relay {state}")
        self.mmsend(MMCommand.SETRELAY, int(channel), int(state))
        return self.mmrecv()

    def reset(self, channel: int | None = None):
        log.info(f"ctrl{self.index} resetting channel {channel}")
        if channel is None:
            self.mmsend(MMCommand.RESET)
        else:
            self.mmsend(MMCommand.RESET, int(channel))
        return self.mmrecv()

    def wait_busy(self):
        while True:
            self.mmsend(MMCommand.CHKSIGBUSY)
            if self.mmrecv() == 0:
                break

    def _set_reading_params(self, channel: int) -> None:
        # Set controller parameters for position reading: 0 volts and max frequency.
        self.set_pulse_train(channel, 1)
        self.set_amplitude(channel, 0)
        self.set_frequency(channel, 500)
        self.set_direction(channel, 1)

    def _read_averaged_position(
        self, channel: int, navg: int
    ) -> tuple[int | float, float]:
        vals: list[int] = []
        for _ in range(navg):
            self._send_signal_once(channel)
            vals.append(self.get_position(channel, emit=False))

        if navg == 1:
            return vals[0], 0.0
        else:
            avg = float(sum(vals) / len(vals))
            return avg, (sum(abs(v - avg) ** 2 for v in vals) / len(vals)) ** (1 / 2)

    def _send_signal_once(self, channel: int) -> None:
        self.mmsend(MMCommand.SENDSIGONCE, int(channel))
        self.mmrecv()

    def get_refreshed_position(
        self,
        channel: int,
        navg: int = 1,
    ) -> int | float:
        # Just reading the position will not return the correct values... probably
        # controller error? So actuate with 0V first
        self._set_reading_params(channel)

        avg, std = self._read_averaged_position(channel, navg)

        if navg == 1:
            log.info(f"ctrl{self.index} Read pos {avg}")
            self.sigPosRead.emit(channel, avg)
        else:
            log.info(f"ctrl{self.index} Read pos {avg:.2f} ± {std:.2f}")
            self.sigAvgPosRead.emit(channel, avg)

        return avg

    def get_refreshed_position_live(
        self, channel: int, navg: int, pulse_train: int, direction: int
    ) -> int:
        """Restore actuation parameters after fine position reading."""
        amp = self.get_amplitude(channel)
        freq = self.get_frequency(channel)

        val = self.get_refreshed_position(channel, navg)

        if pulse_train > 1:
            self.set_pulse_train(channel, pulse_train)
        if direction != 1:
            self.set_direction(channel, direction)
        self.set_amplitude(channel, amp)
        self.set_frequency(channel, freq)

        return val

    def get_position(self, channel: int, emit: bool = True) -> int:
        """Return raw position integer."""
        # seems to return correct values only when called after actuating
        self.wait_busy()
        time.sleep(1e-3)
        self.mmsend(MMCommand.READPOS, channel)
        val = self.mmrecv()
        # log.info(f"received position {val}")
        if emit:
            self.sigPosRead.emit(channel, val)
        return val

    # def freq_test(self, channel: int):
    #     import numpy as np

    #     self.reset()
    #     self.set_frequency(channel, 300)
    #     # amps = (30, 35, 40, 45, 50, 55)
    #     amps = np.arange(30, 62, 2)

    #     niter = 100

    #     vals = np.zeros((len(amps), 2, niter), dtype=int)

    #     p0 = self.get_position(channel)
    #     for i, amp in enumerate(amps):
    #         self.set_amplitude(channel, amp)
    #         for j in range(niter):
    #             self.set_direction(channel, 0)

    #             self.mmsend(MMCommand.SENDSIGONCE, channel)
    #             self.mmrecv()
    #             p1 = self.get_position(channel)
    #             vals[i, 0, j] = p1 - p0

    #             self.set_direction(channel, 1)

    #             self.mmsend(MMCommand.SENDSIGONCE, channel)
    #             self.mmrecv()
    #             p0 = self.get_position(channel)
    #             vals[i, 1, j] = p1 - p0

    #     np.save("D:/MotionController/freqtest2.npy", vals)

    def initialize_parameters(
        self,
        channel: int,
        target: int,
        frequency: int,
        amplitude: tuple[int, int],
        threshold: int,
        high_precision: bool,
        reverse: bool,
        unique_id: str,
    ):
        log.info(
            f"ctrl{self.index} Initializing parameters "
            f"{channel} {target} {frequency} {amplitude} {threshold}"
        )
        self._channel: int = int(channel)
        self._target: int = int(target)
        self._sigtime: int = frequency
        self._amplitudes: tuple[int, int] = amplitude
        self._threshold: int = int(abs(threshold))
        self._high_precision: bool = high_precision
        self._unique_id: str = unique_id
        self._reverse: bool = reverse

        self.initialized: bool = True

    def run(self):
        if not self.initialized:
            log.warning("MMThread was not initialized prior to execution.")
            return
        self.sigMoveStarted.emit(self._channel, self._unique_id)
        self.stopped = False
        try:
            # reset
            self.reset(self._channel)

            # set pulse train
            self.set_pulse_train(self._channel, 10)

            # set amplitude if fwd and bwd are same
            direction_changes_voltage: bool = self._amplitudes[0] != self._amplitudes[1]
            if not direction_changes_voltage:
                self.set_amplitude(self._channel, self._amplitudes[0])

            # set frequency
            self.set_frequency(self._channel, self._sigtime)

            delta_list: list[int | float] = [
                self._target - self.get_position(self._channel)
            ]

            time_start = time.perf_counter()
            time_list: list[float] = [time.perf_counter() - time_start]

            pulse_reduced = 0

            # initialize direction
            direction: int | None = None

            # set relay
            self.set_relay(self._channel, 1)

            while True:
                self.sigDeltaChanged.emit(self._channel, time_list, delta_list)
                if abs(delta_list[-1]) < self._threshold:
                    # position has converged
                    break

                # determine direction
                direction_old = direction
                if delta_list[-1] > 0:
                    direction = 0  # backwards
                else:
                    direction = 1  # forwards

                if self._reverse:
                    direction = 1 - direction

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
                    if n_alt == 50:
                        log.warning(
                            f"Current threshold {self._threshold} is too small,"
                            " position does not converge. Terminating."
                        )
                        break

                # change pulse train & scale amplitude
                amplitude_changed = False
                absdelta = abs(delta_list[-1])
                if pulse_reduced == 0 and (absdelta < 250 * self._threshold):
                    self.set_pulse_train(self._channel, 5)
                    pulse_reduced += 1
                if absdelta < 40 * self._threshold:
                    if pulse_reduced < 2:
                        self.set_pulse_train(self._channel, 1)
                        pulse_reduced += 1
                if pulse_reduced == 2 and absdelta < 10 * self._threshold:
                    pulse_reduced += 1  # high precision mode

                    # factor = absdelta / (20 * self._threshold)
                    # vmin, vmax = 20, self._amplitudes[direction]
                    # decay_rate = 0.5

                    # if vmin < vmax:
                    #     new_amp = vmax - (vmax - vmin) * 2.718281828459045 ** (
                    #         -factor / (decay_rate + 1e-15)
                    #     )
                    #     self.set_amplitude(self._channel, new_amp)
                    #     amplitude_changed = True

                # set direction if changed
                if direction_old != direction:
                    self.set_direction(self._channel, direction)
                    if not amplitude_changed and direction_changes_voltage:
                        # set amplitude if not set
                        self.set_amplitude(self._channel, self._amplitudes[direction])

                # send signal
                self._send_signal_once(self._channel)

                # read position
                if self._high_precision and pulse_reduced == 3:
                    pos = self.get_refreshed_position_live(
                        self._channel, navg=20, pulse_train=1, direction=direction
                    )
                else:
                    pos = self.get_position(self._channel)
                delta_list.append(self._target - pos)
                time_list.append(time.perf_counter() - time_start)

                if self.stopped:
                    break

        except Exception as e:
            log.critical(f"ctrl{self.index} Exception while moving: {e}")
        self.initialized: bool = False
        self.sigMoveFinished.emit(self._channel, self._unique_id)


class EncoderThread(QtCore.QThread):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        *,
        mmthread: MMThread,
        sharedmem: str,
    ):
        super().__init__(parent=parent)
        self.mmthread: MMThread = mmthread
        self.stopped: threading.Event = threading.Event()
        self.sharedmem: str = sharedmem

    def run(self):
        if self.mmthread.initialized or self.mmthread.isRunning():
            log.warning("EncoderThread started while mmthread is active.")
            return

        # Shared list of bools that indicate enabled channels
        sl = shared_memory.ShareableList(name=self.sharedmem)

        try:
            for i, ch in enumerate(range(1, 4)):
                if sl[i]:
                    self.mmthread._set_reading_params(ch)

            self.stopped.clear()

            navg: int = 20
            vals: list[list[float]] = [[], [], []]
            while not self.stopped.is_set():
                for i, ch in enumerate(range(1, 4)):
                    if sl[i]:
                        if self.mmthread.initialized:
                            # Motion is about to start
                            log.warning(
                                "MMThread init detected. This should not happen"
                            )
                            self.stopped.set()
                            break
                        self.mmthread._send_signal_once(ch)
                        vals[i].append(self.mmthread.get_position(ch, emit=False))
                        if len(vals[i]) == navg:
                            self.mmthread.sigAvgPosRead.emit(ch, sum(vals[i]) / navg)
                            vals[i] = []
                time.sleep(10e-3)

        except Exception as e:
            log.critical(f"Exception while reading position: {e}")

        self.stopped.set()
        sl.shm.close()
        del sl


if __name__ == "__main__":
    soc = MMThread()
    soc.connect("192.168.0.210")
    try:
        pass
    except Exception as e:
        print("error!", e)

    soc.disconnect()
