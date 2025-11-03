import csv
import datetime
import multiprocessing
import os
import time
from multiprocessing import shared_memory

import numpy as np
from erpes_daq.sescontrol.plugins.optics import HWP, QWP

# LOG_FILE = "D:/Logs/Misc/250729_hwp_qwp_rpm_try2.csv"
LOG_FILE = "D:/Logs/Misc/250730_glb_qwp_rpm.csv"


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
    # wp_targets = np.linspace(0, 358, 180)
    wp_targets = np.linspace(0, 356, 90)

    logger = LoggingProc()
    logger.start()

    # wp = HWP()
    wp = QWP()
    wp.pre_motion()
    for ang in wp_targets:
        wp.move(ang)
        time.sleep(0.7)
        pwr = get_power()
        logger.add_content([ang, pwr])

    wp.post_motion()
    time.sleep(1)  # wait until logger finishes logging
    logger.stop()


# if __name__ == "__main__":
#     qwp_targets = np.linspace(0, 356, 90)
#     hwp_targets = 22.5 + qwp_targets / 2

#     logger = LoggingProc()
#     logger.start()

#     wp = HWP()

#     wp.pre_motion()
#     for hwp_ang, qwp_ang in zip(hwp_targets, qwp_targets, strict=True):
#         wp.AXIS = 1
#         wp.move(qwp_ang)

#         wp.AXIS = 0
#         wp.move(hwp_ang)

#         time.sleep(0.4)
#         pwr = get_power()
#         logger.add_content([hwp_ang, qwp_ang, pwr])

#     wp.post_motion()
#     time.sleep(1)  # wait until logger finishes logging
#     logger.stop()
