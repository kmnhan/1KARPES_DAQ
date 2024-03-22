import csv
import datetime
import glob
import itertools
import logging
import os
import shutil
import sys
import tempfile
import time
import zipfile
from collections import deque
from collections.abc import Iterable, Sequence
from multiprocessing import shared_memory

import numpy as np
import numpy.typing as npt
import pywinauto
import pywinauto.win32functions
import win32.lib.pywintypes
from qtpy import QtCore

from sescontrol.plugins import Motor
from sescontrol.ses_win import get_ses_properties

SES_DIR = os.getenv("SES_BASE_PATH", "D:/SES_1.9.6_Win64")

log = logging.getLogger("scan")
log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)

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

        Parameters
        ----------
        header : str or list of str
            Header content to write to file.

        """

        file_name = os.path.join(self.dirname, self.prefix + str(self.filename))
        if os.path.isfile(file_name):
            os.remove(file_name)
        self.write_pos(header)


class ScanWorkerSignals(QtCore.QObject):
    sigStepFinished = QtCore.Signal(int, object)
    sigStepStarted = QtCore.Signal(int)
    sigFinished = QtCore.Signal()


class ScanWorker(QtCore.QRunnable):
    def __init__(
        self,
        motors: Sequence[str],
        motion_array: npt.NDArray[np.float64],
        base_dir: str,
        base_file: str,
        data_idx: int,
        valid_ext: Iterable[str],
        has_da: bool,
    ):
        super().__init__()

        self.motors: list[Motor] = [Motor.plugins[k]() for k in motors]
        self.array: npt.NDArray[np.float64] = motion_array
        self.base_dir: str = base_dir
        self.base_file: str = base_file
        self.data_idx: int = data_idx
        self.valid_ext: Iterable[str] = valid_ext
        self.has_da: bool = has_da

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

        # click run button
        log.debug("Clicking sequence run")
        self.click_sequence_button("Run")
        self.update_seq_start_time()

        time.sleep(0.1)

        # keep checking for abort during scan
        aborted: bool = False
        while True:
            if (not aborted) and self._stopnow:
                log.debug("Clicking force stop")
                self.click_sequence_button("Force Stop")
                aborted = True
            if self.check_finished():
                log.debug("Sequence finished")
                break
            time.sleep(0.001)

        if self.has_da:
            log.debug("Checking if the DA map is completely saved")
            # DA maps take time to save even after scan ends, let's try to wait
            timeout_start = time.perf_counter()
            fname = os.path.join(self.base_dir, f"{self.data_name}.zip")
            while True:
                time.sleep(0.2)
                if os.path.isfile(fname) and os.stat(fname).st_size != 0:
                    try:
                        # Copy the zipfile and try opening
                        with tempfile.TemporaryDirectory() as tmpdirname:
                            tmp = shutil.copy(fname, tmpdirname)
                            with zipfile.ZipFile(tmp, "r") as _:
                                # Do nothing, just trying to open the file
                                pass
                    except zipfile.BadZipFile:
                        continue
                    else:
                        log.debug("DA map file appears to be intact")
                        # zipfile is intact, check work folder to confirm
                        # <- workfile checking is not reliable, turn off for now

                        # if len(workfiles) == len(
                        #     os.listdir(os.path.join(SES_DIR, "work"))
                        # ):
                        break
                elif self._stop and time.perf_counter() > timeout_start + 10:
                    # SES 상에서 stop after something 누른 다음 stop after point를 통해
                    # abort할 시에는 DA map이 영영 저장되지 않을 수도 있으니까 10초
                    # 기다려서 안 되면 그냥 안 되는갑다 하기
                    break
            time.sleep(1)
        if aborted:
            return 1
        return 0

    def run(self):
        if len(self.motors) == 0:
            # No motors, single scan
            self.signals.sigStepStarted.emit(1)
            self.sequence_run_wait()
            self.signals.sigStepFinished.emit(1, tuple())
        else:
            for i, ax in enumerate(self.motors):
                ax.pre_motion()
                log.debug(f"Pre-motion for axis {i+1} complete, checking bounds")
                # Last sanity check of bounds before motion
                if (ax.minimum is not None and min(self.array[:, i]) < ax.minimum) or (
                    ax.maximum is not None and max(self.array[:, i]) > ax.maximum
                ):
                    ax.post_motion()
                    self.signals.sigFinished.emit()
                    log.error("Parameters outside motor bounds, aborting")
                    return

            log.info("Starting motion loop")
            self._motion_loop()

            for i, ax in enumerate(self.motors):
                ax.post_motion()
                log.debug(f"Post-motion for axis {i+1} complete")

            # Restore mangled filenames
            self._restore_filenames()
            log.info("Restored filenames")

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
        for i in range(self.array.shape[0]):
            if self._stopnow:
                # Aborted before move
                log.info("Aborted before move")
                break

            self.signals.sigStepStarted.emit(i + 1)  # Step index is 1-based
            for j in range(self.array.shape[1]):
                if i != 0 and np.isclose(self.array[i, j], self.array[i - 1, j]):
                    # Not first iteration and same position as previous, skip move
                    continue
                # Execute move
                self.motors[j].move(self.array[i, j])

            # Execute sequence and wait until it finishes
            ret = self.sequence_run_wait()
            if ret == 1:
                # Aborted during scan, return
                log.info("Aborted during scan")
                return

            # Mangle filename so that SES ignores it
            self._rename_file(i + 1)

            self.signals.sigStepFinished.emit(i + 1, tuple(self.array[i, :]))
            if self._stop:
                # Aborted after scan
                log.info("Aborted after step finished")
                return
