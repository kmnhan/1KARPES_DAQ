import csv
import datetime
import multiprocessing
import os
import time
from multiprocessing import shared_memory

import numpy as np

from erpes_daq.sescontrol.plugins.optics import HWP

LOG_FILE = "D:/Logs/Misc/250728_glb_hwp_rpm_try2.csv"


class LoggingProc(multiprocessing.Process):
    def __init__(self):
        super().__init__()
        self._stopped = multiprocessing.Event()
        self.queue = multiprocessing.Manager().Queue()

    def run(self):
        self._stopped.clear()
        while not self._stopped.is_set():
            time.sleep(0.2)

            if self.queue.empty():
                continue

            # retrieve message from queue
            msg = self.queue.get()

            try:
                with open(LOG_FILE, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(msg)
            except PermissionError:
                # put back the retrieved message in the queue
                n_left = int(self.queue.qsize())
                self.queue.put(msg)
                for _ in range(n_left):
                    self.queue.put(self.queue.get())
                continue

    def stop(self):
        n_left = int(self.queue.qsize())
        if n_left != 0:
            print(
                f"Failed to write {n_left} log "
                + ("entries:" if n_left > 1 else "entry:")
            )
            for _ in range(n_left):
                msg = self.queue.get()
                print(msg)
        self._stopped.set()
        self.join()

    def add_content(self, content: str | list[str]):
        if isinstance(content, str):
            content = [content]
        self.queue.put(content)


def get_power() -> float:
    shm = shared_memory.SharedMemory(name="laser_power")
    out = float(np.ndarray((1,), dtype="f8", buffer=shm.buf)[0])
    shm.close()
    return out


if __name__ == "__main__":
    # hwp_targets = np.linspace(0, 358, 180)
    hwp_targets = np.linspace(0, 356, 90)

    logger = LoggingProc()
    logger.start()

    hwp = HWP()
    hwp.pre_motion()
    for ang in hwp_targets:
        hwp.move(ang)
        time.sleep(0.4)
        pwr = get_power()
        logger.add_content([ang, pwr])

    hwp.post_motion()
    time.sleep(1)  # wait until logger finishes logging
    logger.stop()
