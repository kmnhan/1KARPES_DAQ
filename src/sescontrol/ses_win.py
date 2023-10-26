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
    """Returns the first window of the given process with title `SES`."""
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
    files = []
    for ext in valid_ext:
        files += glob.glob(os.path.join(base_dir, f"{base_file}*{ext}"))

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
        if not self.ses_alive:
            raise RuntimeError("SES is not running")
        shell = win32com.client.Dispatch("WScript.Shell")
        shell.SendKeys("%")
        win32gui.ShowWindow(self._hwnd, win32con.SW_NORMAL)
        path = (
            self._ses_app.window(handle=self._hwnd)
            .menu()
            .get_menu_path("->".join(path))
        )
        if path[-1].is_enabled():
            path[-1].click()
            return 0
        else:
            return 1

    @property
    def ses_alive(self) -> bool:
        try:
            proc = psutil.Process(self._pid)
        except psutil.NoSuchProcess:
            return False
        return proc.name() == "Ses.exe"

    @property
    def data_files(self) -> tuple[str, ...]:
        """Returns a tuple of wildcard strings to match against the saved data file."""
        base_dir, base_file, valid_ext, saveafter = get_file_info()
        if saveafter != "0":
            print("Autosave is on")
            pass

        # return tuple(os.path.join(base_dir, f"{base_file}*{ext}") for ext in valid_ext)

    # def calibrate_voltages(self):
    #     return self.click_menu(["Calibration", "Voltages..."])

    # def file_options(self):
    #     return self.click_menu("Setup", "File Options...")

    # def sequence_setup(self):
    #     return self.click_menu("Sequence", "Setup...")

    def run_sequence(self):
        return self.click_menu("Sequence", "Run")

    # def control_theta(self):
    #     return self.click_menu("DA30", "Control Theta...")

    # def center_deflection(self):
    #     return self.click_menu("DA30", "Center Deflection")
