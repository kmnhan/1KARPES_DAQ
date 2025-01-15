"""Functions that use the Windows API to control SES.exe windows and menus."""

import glob
import logging
import os
import sys
from collections.abc import Callable, Iterable

sys.coinit_flags = 2

import configparser
import shutil
import tempfile

import psutil
import pywinauto
import win32com.client
import win32con
import win32gui

SES_DIR = os.getenv("SES_BASE_PATH", "D:/SES_1.9.6_Win64")
log = logging.getLogger("scan")

SES_ACTIONS: dict[str, tuple[str, Callable[[str], bool]] | None] = {
    "Calibrate Voltages": (
        "Calibration->Voltages...",
        lambda title: title == "Voltage Calibration",
    ),
    "File Opts.": (
        "Setup->File Options...",
        lambda title: title == "File Options",
    ),
    "Sequences": (
        "Sequence->Setup...",
        lambda title: title.startswith("Sequence Editor"),
    ),
    "Control Theta": (
        "DA30->Control Theta...",
        lambda title: title == "Control Theta",
    ),
    "Center Deflection": (
        "DA30->Center Deflection",
        None,
    ),
}
"""
Actions to be added to the widget.

The keys are the labels of the buttons, and the values are tuples. The first element of
the tuple is a string that indicates the path to the menu item, and the second element
is a callable that takes a string and returns whether it matches the title of the window
that is meant to be opened by the action. If the action does not open a window, the
second element can be None.

"""


def get_ses_proc() -> psutil.Process:
    for proc in psutil.process_iter():
        if "Ses.exe" == proc.name():
            return proc
    raise RuntimeError("SES is not running")


def get_matching_window(
    process: psutil.Process | int, match: Callable[[str], bool]
) -> int:
    """Get the first window handle of given process that matches the given function."""
    if isinstance(process, int):
        process = psutil.Process(process)
    windows = []
    for thread in process.threads():
        if len(windows) > 0:
            break

        def enum_windows_callback(hwnd, lParam):
            if match(win32gui.GetWindowText(hwnd)):
                windows.append(hwnd)
            return True

        thread_id = thread.id
        win32gui.EnumThreadWindows(thread_id, enum_windows_callback, 0)
    if len(windows) == 0:
        raise RuntimeError("Matching window not found")
    return windows[0]


def get_ses_window(process: psutil.Process | int) -> int:
    """Return the first window handle of process that has the title `SES`."""

    def func(x: str) -> bool:
        return x == "SES"

    return get_matching_window(process, func)


def get_ses_properties() -> tuple[int, int]:
    """Return the pid and hwnd of the SES.exe main window."""
    proc = get_ses_proc()
    return proc.pid, get_ses_window(proc)


def get_file_info() -> tuple[str, str, set[str], int, list[dict[str, str]]]:
    """Read and parse the `factory.seq` file in the SES folder.

    From the sequence file, we can determine where the current data is being saved.

    """
    config = configparser.RawConfigParser()
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp = shutil.copy(os.path.join(SES_DIR, "sequences", "factory.seq"), tmpdirname)
        with open(tmp) as f:
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

    seq_enabled: list[dict[str, str]] = [
        dict(v) for v in config.values() if int(v.get("Enabled", 0))
    ]

    return base_dir, base_file, valid_ext, spec.get("saveafter"), seq_enabled


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


class SESController:
    def __init__(self):
        self._pid: int | None = None
        self.try_connect()

    def try_connect(self):
        try:
            self._pid, self._hwnd = get_ses_properties()
        except RuntimeError:
            return
        self._ses_app = pywinauto.Application(backend="win32").connect(
            process=self._pid
        )

    def is_window_visible(self, match: Callable[[str], bool]) -> bool:
        if not self.alive:
            raise RuntimeError("SES is not running")
        handle = get_matching_window(self._pid, match)
        return bool(win32gui.IsWindowVisible(handle))

    def click_menu(self, path: str, match: Callable[[str], bool] | None = None) -> int:
        # Click menu given by path. If the menu item opens some window, match needs to
        # be given as a function that returns True only for the window title.
        if not self.alive:
            raise RuntimeError("SES is not running")
        if match is not None:
            handle = get_matching_window(self._pid, match)
            if bool(win32gui.IsWindowVisible(handle)):
                # If already visible, avoid queuing another message
                win32gui.BringWindowToTop(handle)
                return 0

        path = self._ses_app.window(handle=self._hwnd).menu().get_menu_path(path)
        if path[-1].is_enabled():
            path[-1].ctrl.post_message(path[-1].menu.COMMAND, path[-1].item_id())
            pywinauto.win32functions.WaitGuiThreadIdle(path[-1].ctrl.handle)
            if match is not None:
                # Bring the window to the top
                win32gui.BringWindowToTop(handle)
            return 0
        else:
            return 1

    @property
    def alive(self) -> bool:
        """Returns wheter SES is running."""
        if self._pid is None:
            return False
        try:
            proc = psutil.Process(self._pid)
        except psutil.NoSuchProcess:
            return False
        return proc.name() == "Ses.exe"

    def run_sequence(self):
        return self.click_menu("Sequence->Run")
