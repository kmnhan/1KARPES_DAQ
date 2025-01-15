from __future__ import annotations

import os
import sys
import time

import cv2
import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets, uic

try:
    os.chdir(sys._MEIPASS)
except:  # noqa: E722
    pass


SAVE_DIR: str = os.path.join(
    os.path.expanduser("~"), "Pictures", "Camera Roll"
)  #: Directory to save the image to.


class CameraHandler(QtCore.QThread):
    sigGrabbed = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.live: bool = True
        self.focus: int = 0
        self.save_requested: bool = False

    def run(self):
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)  # 1920, 1280, 640
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)  # 1080, 720, 360
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)

        frame_rate = 30
        time_prev = time.perf_counter()
        while self.live:
            cap.set(cv2.CAP_PROP_FOCUS, int(self.focus * 5))
            if time.perf_counter() - time_prev > 1.0 / frame_rate:
                ret, image = cap.read()
                if ret:
                    self.sigGrabbed.emit(image)
                    time_prev = time.perf_counter()
                    if self.save_requested:
                        filename = os.path.join(
                            SAVE_DIR,
                            f"Image__{time.strftime('%Y-%m-%d__%H-%M-%S', time.localtime())}.jpg",
                        )
                        cv2.imwrite(filename, image)
                        self.save_requested = False
            time.sleep(0.001)
        cap.release()

    @QtCore.Slot(int)
    def set_focus(self, value: int):
        self.focus = value


uiclass, baseclass = uic.loadUiType("webcam.ui")


class MainWindow(uiclass, baseclass):
    sigFocusChanged = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.setWindowTitle("1KARPES Webcam Monitor")

        # add plot and image
        self.plot_item = self.plot_widget.plotItem
        self.plot_item.setDefaultPadding(0)
        self.plot_item.vb.invertY(True)
        self.plot_item.vb.setCursor(QtGui.QCursor(QtCore.Qt.CrossCursor))

        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.plot_item.addItem(self.image_item)
        self.plot_item.hideAxis("bottom")
        self.plot_item.hideAxis("left")

        # aspect ratio checkbox
        self.aspect_check.stateChanged.connect(self.handle_aspect)
        self.aspect_check.setChecked(True)

        # webcam handling
        self.camera_handler = CameraHandler()
        self.camera_handler.sigGrabbed.connect(self.set_image)

        self.live_check.stateChanged.connect(self.toggle_grabbing)
        self.live_check.setChecked(True)

        # focus slider
        self.focus_slider.valueChanged.connect(self.set_focus)
        self.sigFocusChanged.connect(self.camera_handler.set_focus)

        # save image
        self.save_img_btn.clicked.connect(self.save_image)

        # load settings
        self.settings = QtCore.QSettings("erlab", "1KARPES Webcam Monitor")
        focus = self.settings.value("c922pro_focus")
        if focus is not None:
            self.focus_slider.setValue(focus)

    @QtCore.Slot(object)
    def set_image(self, image):
        if image.ndim == 3:
            self.image_item.setImage(np.flip(image, -1), useRGBA=True)
        else:
            self.image_item.setImage(image)

    @QtCore.Slot(int)
    def set_focus(self, value: int):
        self.sigFocusChanged.emit(value)

    @QtCore.Slot()
    def save_image(self):
        self.camera_handler.save_requested = True

    @QtCore.Slot()
    def toggle_grabbing(self):
        if self.live_check.isChecked():
            self.camera_handler.start()
            self.camera_handler.live = True
        else:
            self.camera_handler.live = False

    @QtCore.Slot()
    def handle_aspect(self):
        self.plot_item.vb.setAspectLocked(lock=self.aspect_check.isChecked(), ratio=1)

    def closeEvent(self, *args, **kwargs):
        self.settings.setValue("c922pro_focus", self.focus_slider.value())
        self.live_check.setChecked(False)
        self.camera_handler.wait(2000)
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)

    qapp.setWindowIcon(QtGui.QIcon("./icon.ico"))

    win = MainWindow()
    win.show()
    win.activateWindow()

    qapp.exec()
