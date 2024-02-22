import csv
import datetime
import glob
import os
import time
import zipfile
from collections import deque
from collections.abc import Iterable
from multiprocessing import shared_memory

import numpy as np
import pywinauto
import pywinauto.win32functions
import win32.lib.pywintypes
from qtpy import QtCore

from sescontrol.plugins import Motor
from sescontrol.ses_win import get_ses_properties

SES_DIR = os.getenv("SES_BASE_PATH", "D:/SES_1.9.6_Win64")


"""
Limitations

Only `zip-format` must be selected in file options
Multiple DA maps in a single region not supported


"""


class MotorPosWriter(QtCore.QRunnable):
    def __init__(self):
        super().__init__()
        self._stopped: bool = False
        self.messages: deque[list[str]] = deque()
        self.dirname: str | os.PathLike | None = None
        self.filename: str | os.PathLike | None = None
        self.prefix: str | None = None

    def run(self):
        self._stopped = False
        while not self._stopped:
            time.sleep(0.02)
            if len(self.messages) == 0:
                continue
            msg = self.messages.popleft()
            try:
                # if file without prefix exists, the scan has finished but we have
                # remaining log entries to enter.
                fname = os.path.join(self.dirname, self.filename)
                if not os.path.isfile(fname):
                    fname = os.path.join(self.dirname, self.prefix + str(self.filename))
                with open(fname, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(msg)
            except PermissionError:
                self.messages.appendleft(msg)
                continue

    def stop(self):
        n_left = len(self.messages)
        if n_left != 0:
            print(
                f"Failed to write {n_left} " + ("entries:" if n_left > 1 else "entry:")
            )
            for msg in self.messages:
                print(",".join(msg))
        self._stopped = True

    def set_file(
        self, dirname: str | os.PathLike, filename: str | os.PathLike, prefix: str
    ):
        self.dirname = dirname
        self.filename = filename
        self.prefix = prefix

    def write_pos(self, content: str | list[str]):
        """Appends content to log file."""
        if isinstance(content, str):
            content = [content]
        self.messages.append(content)

    def write_header(self, header: str | list[str]):
        """Creates and appends a header to log file.

        If a file with the same name already exists, it will be removed.

        """

        file_name = os.path.join(self.dirname, self.prefix + str(self.filename))
        if os.path.isfile(file_name):
            os.remove(file_name)
        self.write_pos(header)


class ScanWorkerSignals(QtCore.QObject):
    sigStepFinished = QtCore.Signal(int, object, object)
    sigStepStarted = QtCore.Signal(int)
    sigFinished = QtCore.Signal()


class ScanWorker(QtCore.QRunnable):
    def __init__(
        self,
        motor_args: list[tuple[str, np.ndarray]],
        base_dir: str,
        base_file: str,
        data_idx: int,
        valid_ext: Iterable[str],
        has_da: bool,
    ):
        super().__init__()

        self.axes: list[Motor] = []
        self.coords: list[np.ndarray] = []
        for ma in motor_args:
            self.axes.append(Motor.plugins[ma[0]]())
            self.coords.append(ma[1])

        self.base_dir = base_dir
        self.base_file = base_file
        self.data_idx = data_idx
        self.valid_ext = valid_ext
        self.has_da = has_da

        self.signals = ScanWorkerSignals()
        self._pid, self._hwnd = get_ses_properties()
        self._ses_app = pywinauto.Application(backend="win32").connect(
            process=self._pid
        )

        self._stop: bool = False
        self._stopnow: bool = False

    @property
    def data_name(self) -> str:
        return f"{self.base_file}{str(self.data_idx).zfill(4)}"

    def check_finished(self) -> bool:
        """Returns whether if sequence is finished."""
        path = (
            self._ses_app.window(handle=self._hwnd)
            .menu()
            .get_menu_path("Sequence->Run")
        )
        return path[-1].is_enabled()

    def click_sequence_button(self, button: str):
        """Click a button in the Sequence menu."""
        while True:
            try:
                path = (
                    self._ses_app.window(handle=self._hwnd)
                    .menu()
                    .get_menu_path(f"Sequence->{button}")
                )
                path[-1].ctrl.send_message(path[-1].menu.COMMAND, path[-1].item_id())
                pywinauto.win32functions.WaitGuiThreadIdle(path[-1].ctrl.handle)
            except win32.lib.pywintypes.error as e:
                print(e)
                continue
            else:
                break

    def stop_after_point(self):
        """Stop after acquiring current motor point."""
        self._stop = True

    def cancel_stop_after_point(self):
        """Stop after acquiring current motor point."""
        self._stop = False

    def force_stop(self):
        """Force stop now."""
        self._stop = True
        self._stopnow = True

    def update_seq_start_time(self):
        """Write current time to shared memory if exists.

        The shared memory is accessed by the attribute server.
        """
        try:
            shm = shared_memory.SharedMemory(name="seq_start")
        except FileNotFoundError:
            pass
        else:
            np.ndarray((1,), "f8", shm.buf)[0] = datetime.datetime.now().timestamp()
            shm.close()

    def sequence_run_wait(self) -> int:
        """Run sequence and wait until it finishes."""

        workfiles = os.listdir(os.path.join(SES_DIR, "work"))

        # click run button
        self.click_sequence_button("Run")
        self.update_seq_start_time()

        time.sleep(0.01)

        # keep checking for abort during scan
        aborted: bool = False
        while True:
            if (not aborted) and self._stopnow:
                self.click_sequence_button("Force Stop")
                aborted = True
            if self.check_finished():
                break
            time.sleep(0.001)

        if self.has_da:
            # DA maps take time to save even after scan ends, let's try to wait
            timeout_start = time.perf_counter()
            fname = os.path.join(self.base_dir, f"{self.data_name}.zip")
            while True:
                time.sleep(0.2)
                if os.path.isfile(fname) and os.stat(fname).st_size != 0:
                    try:
                        with zipfile.ZipFile(fname, "r") as _:
                            # do nothing, just trying to open the file
                            pass
                    except zipfile.BadZipFile:
                        continue
                    else:
                        # zipfile is intact, check work folder to confirm
                        if len(workfiles) == len(
                            os.listdir(os.path.join(SES_DIR, "work"))
                        ):
                            break
                elif self._stop and time.perf_counter() > timeout_start + 20:
                    # SES 상에서 stop after something 누른 다음 stop after point를 통해
                    # abort할 시에는 DA map이 영영 저장되지 않을 수도 있으니까 20초
                    # 기다려서 안 되면 그냥 안 되는갑다 하기
                    break
        if aborted:
            return 1
        return 0

    def run(self):
        if len(self.axes) == 0:
            # no motors, single scan
            self.signals.sigStepStarted.emit(1)
            self.sequence_run_wait()
            self.signals.sigStepFinished.emit(1, 0, 0)
        else:
            if len(self.axes) == 1:
                self.coords.append([[0]])

            for i, ax in enumerate(self.axes):
                ax.pre_motion()

                # last sanity check of bounds before motion
                if (ax.minimum is not None and min(self.coords[i]) < ax.minimum) or (
                    ax.maximum is not None and max(self.coords[i]) > ax.maximum
                ):
                    ax.post_motion()
                    self.signals.sigFinished.emit()
                    print("PARAMETERS OUT OF MOTOR BOUNDS")
                    return

            self._motion_loop()

            for ax in self.axes:
                ax.post_motion()

            # restore mangled filenames
            self._restore_filenames()

        self.signals.sigFinished.emit()

    def _rename_file(self, index: int):
        """Renames the data file to include the slice index.

        This function adjusts file names to maintain a constant file number during
        scans. File names are temporarily modified during scanning by adding a prefix,
        which is later restored using `_restore_filenames` when all scans are completed.

        This is possible because SES determines the sequence number by parsing the name
        of the files in the data directory.

        Parameters
        ----------
        index : int
            Index of the scan to rename.

        """
        for ext in self.valid_ext:
            f = os.path.join(self.base_dir, f"{self.data_name}{ext}")
            new = os.path.join(
                self.base_dir,
                "_scan_"
                + self.base_file
                + str(self.data_idx).zfill(4)
                + f"_S{str(index).zfill(5)}"
                + ext,
            )
            if os.path.isfile(f):
                while True:
                    try:
                        os.rename(f, new)
                    except PermissionError:
                        time.sleep(0.001)
                        continue
                    else:
                        break

    def _restore_filenames(self):
        files = []
        for ext in list(self.valid_ext) + [".csv"]:
            files += glob.glob(
                os.path.join(self.base_dir, f"_scan_{self.base_file}*{ext}")
            )
        for f in files:
            new = f.replace(
                os.path.basename(f), os.path.basename(f).replace("_scan_", "")
            )
            while True:
                try:
                    os.rename(f, new)
                except PermissionError:
                    time.sleep(0.001)
                    continue
                except FileExistsError:
                    if f.endswith(".csv"):
                        with open(f, "r", newline="") as source_csv:
                            source_reader = csv.reader(source_csv)
                            with open(new, "a", newline="") as dest_csv:
                                dest_writer = csv.writer(dest_csv)
                                for row in source_reader:
                                    dest_writer.writerow(row)
                        os.remove(f)
                    break
                else:
                    break

    def _motion_loop(self):
        niter: int = 1
        for i, val0 in enumerate(self.coords[0]):
            if self._stopnow:
                # aborted before initial move
                break

            # move outer loop to val 0
            pos0 = self.axes[0].move(val0)

            if (i % 2) != 0:
                # if outer loop index is odd, inner loop is reversed
                coord1_iter = reversed(self.coords[1])
            else:
                coord1_iter = self.coords[1]
            for val1 in coord1_iter:
                if len(self.axes) == 2:
                    # move inner loop to val 1
                    pos1 = self.axes[1].move(val1)
                else:
                    pos1 = None

                self.signals.sigStepStarted.emit(niter)

                # execute sequence and wait until it finishes
                ret = self.sequence_run_wait()
                if ret == 1:
                    # aborted during scan, return
                    return

                # mangle filename so that SES ignores it
                self._rename_file(niter)
                self.signals.sigStepFinished.emit(niter, pos0, pos1)

                if self._stop:
                    # aborted after scan
                    return

                niter += 1
