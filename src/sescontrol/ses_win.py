"""Functions that use the Windows API to control SES.exe windows and menus."""

import glob
import os
import sys
from collections.abc import Iterable, Sequence

sys.coinit_flags = 2

import configparser
import os
import shutil
import tempfile

import psutil
import pywinauto
import win32com.client
import win32con
import win32gui

SES_DIR = os.getenv("SES_BASE_PATH", "D:/SES_1.9.6_Win64")


def get_ses_proc() -> psutil.Process:
    for proc in psutil.process_iter():
        if "Ses.exe" == proc.name():
            return proc
    raise RuntimeError("SES is not running")


def get_ses_window(process: psutil.Process) -> int:
    """Returns the first window hwnd of process that has the title `SES`."""
    windows = []
    for thread in process.threads():

        def enum_windows_callback(hwnd, lParam):
            if win32gui.IsWindowVisible(hwnd):
                if win32gui.GetWindowText(hwnd) == "SES":
                    windows.append(hwnd)
            return True

        thread_id = thread.id
        win32gui.EnumThreadWindows(thread_id, enum_windows_callback, 0)
    if len(windows) == 0:
        raise RuntimeError("SES main window is not open")
    return windows[0]


def get_ses_properties() -> tuple[int, int]:
    """Returns the pid and hwnd of the SES.exe main window."""
    proc = get_ses_proc()
    return proc.pid, get_ses_window(proc)


def get_file_info() -> tuple[str, str, set[str], int]:
    """
    Reads the `factory.seq` file in the SES folder to determine where the current data
    is being saved.

    """

    config = configparser.RawConfigParser()
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp = shutil.copy(os.path.join(SES_DIR, "sequences", "factory.seq"), tmpdirname)
        with open(tmp, "r") as f:
            config.read_file(f)

    spec = config["Spectrum"]

    base_dir = spec["spectrum base directory"]
    if spec.getboolean("sort by user"):
        base_dir = os.path.join(base_dir, spec.get("user", ""))
    if spec.getboolean("sort by sample"):
        base_dir = os.path.join(base_dir, spec.get("sample", ""))

    base_file = spec["spectrum base file name"]

    valid_ext: set[str] = {".pxt"}.union(
        spec.get("spectrum file extension", ".pxt").split(",")
    )

    return base_dir, base_file, valid_ext, spec.get("saveafter")


def next_index(base_dir: str, base_file: str, valid_ext: Iterable[str]) -> int:
    """Infer the index of the upcoming data file from existing files."""
    files = []
    for ext in valid_ext:
        files += glob.glob(os.path.join(base_dir, f"{base_file}*{ext}"))

    # get all files matching signature, sorted by time of last modification
    files = [
        os.path.basename(f) for f in sorted(files, key=lambda f: os.stat(f).st_mtime)
    ]
    if len(files) == 0:
        return 1
    else:
        return int(os.path.splitext(files[-1])[0][len(base_file) :][:4]) + 1


class SESController(object):
    def __init__(self):
        super().__init__()
        self._pid, self._hwnd = get_ses_properties()
        self._ses_app = pywinauto.Application(backend="win32").connect(
            process=self._pid
        )

    def click_menu(self, path: Sequence[str]) -> int:
        if not self.alive:
            raise RuntimeError("SES is not running")
        path = (
            self._ses_app.window(handle=self._hwnd)
            .menu()
            .get_menu_path("->".join(path))
        )
        if path[-1].is_enabled():
            path[-1].ctrl.send_message(path[-1].menu.COMMAND, path[-1].item_id())
            pywinauto.win32functions.WaitGuiThreadIdle(path[-1].ctrl.handle)
            return 0
        else:
            return 1

    @property
    def alive(self) -> bool:
        """Returns wheter SES is running."""
        try:
            proc = psutil.Process(self._pid)
        except psutil.NoSuchProcess:
            return False
        return proc.name() == "Ses.exe"

    def run_sequence(self):
        return self.click_menu("Sequence", "Run")
