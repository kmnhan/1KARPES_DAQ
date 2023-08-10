from __future__ import annotations

import logging
import os
import platform
import sys
import time

import numpy as np
import pyqtgraph as pg
from erlab.interactive.utilities import BetterColorBarItem, BetterImageItem
from pypylon import genicam, pylon
from qtpy import QtCore, QtGui, QtWidgets, uic

EXCLUDED_DEVICES: tuple[str, ...] = (
    "40049666",
)  #: Tuple of string of serial numbers to exclude from search.
DEVICE_ALIASES: dict[str, str] = {
    "40155047": "sample camera"
}  #: Mapping from serial number to custom label.
SAVE_DIR: str = os.path.join(
    os.path.expanduser("~"), "Pictures", "Sample Camera"
)  #: Directory to save the image to.
tlf: pylon.TlFactory = pylon.TlFactory.GetInstance()  #: The transport layer factory.
img: pylon.PylonImage = pylon.PylonImage()  #: Handles image saving.


class RowOrderingWidget(QtWidgets.QWidget):
    def __init__(self, row, col):
        super().__init__()
        self.setLayout(QtWidgets.QHBoxLayout())
        self.layout().setContentsMargins(1, 1, 1, 1)
        self.layout().setSpacing(1)

        self.row_index = row
        self.col_index = col

        self.up = QtWidgets.QPushButton("▲")
        self.down = QtWidgets.QPushButton("▼")
        self.layout().addWidget(self.up)
        # ˄ ˅ ⌃ ⌄ ⇧ ⇩ ⬆️ ⬇️ ▲ ▼
        self.layout().addWidget(self.down)

        self.up.setStyleSheet("QPushButton { border: none; }")
        self.down.setStyleSheet("QPushButton { border: none; }")
        self.up.setFixedWidth(20)
        self.down.setFixedWidth(20)

        self.up.clicked.connect(self.swap_row_up)
        self.down.clicked.connect(self.swap_row_down)

    @property
    def _table_widget(self):
        return self.parentWidget().parentWidget()

    def swap_row_up(self):
        r0 = self.row_index
        if r0 == 0:
            return
        self.swap_rows(r0, r0 - 1)

    def swap_row_down(self):
        r0 = self.row_index
        if r0 == self._table_widget.rowCount() - 1:
            return
        self.swap_rows(r0, r0 + 1)

    def swap_rows(self, r0: int, r1: int):
        r0_items = [
            self._table_widget.takeItem(r0, i)
            for i in range(self._table_widget.columnCount())
        ]
        for i in range(self._table_widget.columnCount()):
            self._table_widget.setItem(r0, i, self._table_widget.takeItem(r1, i))
            self._table_widget.setItem(r1, i, r0_items[i])

            if i == self.col_index:
                self._table_widget.cellWidget(r0, i).row_index = r0
                self._table_widget.cellWidget(r1, i).row_index = r1


uiclass, baseclass = uic.loadUiType("framegrab.ui")


class MainWindowGUI(uiclass, baseclass):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.setWindowTitle("1KARPES Camera Monitor")

        # add plot and image
        self.plot_item = self.graphics_layout.addPlot()
        self.plot_item.setDefaultPadding(0)
        self.plot_item.vb.invertY(True)

        self.plot_item.vb.setCursor(QtGui.QCursor(QtCore.Qt.CrossCursor))
        self.image_item = BetterImageItem(axisOrder="row-major")
        self.plot_item.addItem(self.image_item)

        # target & circle roi
        self.target = pg.TargetItem(pen="r")
        self.circle = pg.CircleROI(self.target.pos(), radius=1138, movable=False)
        self.target.sigPositionChanged.connect(self.target_moved)
        self.target_check.stateChanged.connect(
            lambda: self.target.setVisible(self.target_check.isChecked())
        )
        self.target_check.setChecked(True)
        self.circle_check.stateChanged.connect(
            lambda: self.circle.setVisible(self.circle_check.isChecked())
        )
        self.circle_check.setChecked(False)

        self.plot_item.addItem(self.target)
        self.plot_item.addItem(self.circle)

        # aspect ratio checkbox
        self.aspect_check.stateChanged.connect(self.handle_aspect)
        self.aspect_check.setChecked(True)

        # crosshair
        self.lines = (
            pg.InfiniteLine(angle=90, movable=False),
            pg.InfiniteLine(angle=0, movable=False),
        )
        for ln in self.lines:
            self.plot_item.addItem(ln, ignoreBounds=True)
            ln.setVisible(False)
        self.plot_item.scene().sigMouseMoved.connect(self.mouse_moved)
        self.crosshair_check.stateChanged.connect(
            lambda: [
                ln.setVisible(self.crosshair_check.isChecked()) for ln in self.lines
            ]
        )

        # color related widgets
        self.cmap_combo.setDefaultCmap("gray")
        self.cmap_combo.textActivated.connect(self.update_cmap)
        self.gamma_widget.valueChanged.connect(self.update_cmap)
        self.invert_check.stateChanged.connect(self.update_cmap)
        self.contrast_check.stateChanged.connect(self.update_cmap)
        self.update_cmap()

        # add colorbar
        self.cbar = BetterColorBarItem(limits=(0, 255))
        self.cbar.setImageItem(image=self.image_item, insert_in=self.plot_item)
        self.cbar.set_width(20)
        self.auto_clim_check.stateChanged.connect(
            lambda: self.cbar.setAutoLevels(self.auto_clim_check.isChecked())
        )

        # get settings
        self.settings = QtCore.QSettings("erlab", "Frame Grabber")
        self.load_from_settings()

        # save & load position
        self.load_btn.clicked.connect(self.load_position)
        self.load_btn.setDisabled(True)
        self.delete_btn.clicked.connect(self.drop_position)
        self.delete_btn.setDisabled(True)
        self.write_btn.clicked.connect(self.write_position)
        for btn in (self.delete_btn, self.load_btn):
            self.pos_table.itemSelectionChanged.connect(
                lambda *, target=btn: target.setDisabled(
                    len(self.pos_table.selectedRanges()) == 0
                )
            )
        self.pos_table.cellChanged.connect(self.write_to_settings)
        for i in (0, 3):
            self.pos_table.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeToContents
            )
        self.pos_table.selectRow(0)
        self.load_btn.click()

    @QtCore.Slot()
    def target_moved(self):
        w, h = self.circle.size()
        x, y = self.target.pos()
        self.circle.setPos(x - w / 2, y - h / 2)

    @QtCore.Slot()
    def load_position(self):
        row_idx = self.pos_table.currentRow()
        x_item, y_item = self.pos_table.item(row_idx, 1), self.pos_table.item(
            row_idx, 2
        )
        self.target.setPos(
            x_item.data(QtCore.Qt.EditRole), y_item.data(QtCore.Qt.EditRole)
        )

    @QtCore.Slot()
    def drop_position(self):
        self.pos_table.removeRow(self.pos_table.currentRow())

    def write_position(self):
        pos = self.target.pos()

        if len(self.pos_table.selectedRanges()) == 0:
            self.pos_table.insertRow(self.pos_table.rowCount())
            self.pos_table.setCurrentCell(self.pos_table.rowCount() - 1, 0)

        row_idx = self.pos_table.currentRow()
        x_item, y_item = QtWidgets.QTableWidgetItem(), QtWidgets.QTableWidgetItem()
        x_item.setData(QtCore.Qt.EditRole, pos.x())
        y_item.setData(QtCore.Qt.EditRole, pos.y())
        self.pos_table.setItem(row_idx, 1, x_item)
        self.pos_table.setItem(row_idx, 2, y_item)

        self.pos_table.setCellWidget(row_idx, 3, RowOrderingWidget(row_idx, 3))

    def load_from_settings(self):
        self.settings.beginGroup("savedPositions")
        for i, pos in enumerate(self.settings.childGroups()):
            name_item, x_item, y_item = (
                QtWidgets.QTableWidgetItem(),
                QtWidgets.QTableWidgetItem(),
                QtWidgets.QTableWidgetItem(),
            )
            name_item.setData(QtCore.Qt.EditRole, self.settings.value(f"{pos}/name"))
            x_item.setData(QtCore.Qt.EditRole, float(self.settings.value(f"{pos}/x")))
            y_item.setData(QtCore.Qt.EditRole, float(self.settings.value(f"{pos}/y")))
            self.pos_table.insertRow(i)
            self.pos_table.setItem(i, 0, name_item)
            self.pos_table.setItem(i, 1, x_item)
            self.pos_table.setItem(i, 2, y_item)
            self.pos_table.setCellWidget(i, 3, RowOrderingWidget(i, 3))

        self.settings.endGroup()

    def write_to_settings(self):
        self.settings.remove("savedPositions")
        for i in range(self.pos_table.rowCount()):
            try:
                x, y = (
                    self.pos_table.item(i, 1).data(QtCore.Qt.EditRole),
                    self.pos_table.item(i, 2).data(QtCore.Qt.EditRole),
                )
            except AttributeError:
                continue  # cell is yet to be filled
            try:
                name = self.pos_table.item(i, 0).data(QtCore.Qt.DisplayRole)
            except AttributeError:
                name = None  # name is empty
            self.settings.setValue(f"savedPositions/pos{i}/name", name)
            self.settings.setValue(f"savedPositions/pos{i}/x", x)
            self.settings.setValue(f"savedPositions/pos{i}/y", y)

    def handle_aspect(self):
        self.plot_item.vb.setAspectLocked(lock=self.aspect_check.isChecked(), ratio=1)

    @property
    def _cmap_name(self):
        name = self.cmap_combo.currentText()
        if name == self.cmap_combo.LOAD_ALL_TEXT:
            self.cmap_combo.load_all()
            return None
        return name

    @property
    def _cmap_gamma(self):
        return self.gamma_widget.value()

    def update_cmap(self):
        if self._cmap_name is None:
            return
        self.image_item.set_colormap(
            self._cmap_name,
            self._cmap_gamma,
            reverse=self.invert_check.isChecked(),
            highContrast=self.contrast_check.isChecked(),
            update=True,
        )

    def mouse_moved(self, pos):
        # if not self.plot_item.vb.itemBoundingRect(self.image_item).contains(pos):
        if not self.plot_item.sceneBoundingRect().contains(pos):
            self.statusBar().clearMessage()
            return

        point = self.plot_item.vb.mapSceneToView(pos)
        self.statusBar().showMessage(f"X = {point.x():.6g}, Z = {point.y():.6g}")
        if self.crosshair_check.isChecked():
            self.lines[0].setPos(point.x())
            self.lines[1].setPos(point.y())


class CameraConfiguration(pylon.ConfigurationEventHandler, QtCore.QObject):
    def OnOpened(self, camera):
        try:
            # Maximize the Image AOI.
            if genicam.IsWritable(camera.OffsetX):
                camera.OffsetX = camera.OffsetX.Min
            if genicam.IsWritable(camera.OffsetY):
                camera.OffsetY = camera.OffsetY.Min
            camera.Width = camera.Width.Max
            camera.Height = camera.Height.Max

            # Flip image.
            if genicam.IsWritable(camera.ReverseX):
                camera.ReverseX = True
            if genicam.IsWritable(camera.ReverseY):
                camera.ReverseY = False

            if genicam.IsWritable(camera.GainAuto):
                camera.GainAuto = "Off"

            if genicam.IsWritable(camera.GammaSelector):
                camera.GammaSelector = "sRGB"

            if genicam.IsWritable(camera.ExposureAuto):
                camera.ExposureAuto = "Off"

            # Set the pixel data format.
            camera.PixelFormat = "Mono8"
        except genicam.GenericException as e:
            raise genicam.RuntimeException(
                "Could not apply configuration. GenICam::GenericException \
                                            caught in OnOpened method msg=%s"
                % e.what()
            )


class FrameGrabber(QtCore.QThread):
    sigGrabbed = QtCore.Signal(object)
    sigExposureRead = QtCore.Signal(int, int, int)
    # sigFailed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.live: bool = True
        self._camera = None
        self.save_requested: bool = False
        self.set_srgb(True)

    @property
    def camera(self) -> pylon.InstantCamera:
        return self._camera

    def set_device(self, device) -> None:
        if isinstance(device, pylon.DeviceInfo):
            device = tlf.CreateDevice(device)
        if self._camera is None:
            self._camera = pylon.InstantCamera(device, pylon.Cleanup_Delete)
            self._camera.RegisterConfiguration(
                CameraConfiguration(),
                pylon.RegistrationMode_Append,
                pylon.Cleanup_Delete,
            )
        else:
            self._camera.Attach(device)

    @QtCore.Slot(int)
    def set_exposure(self, value: int):
        self.exposure: int = value

    @QtCore.Slot(bool)
    def set_srgb(self, value: bool):
        self.srgb_gamma: bool = value

    def run(self):
        self.camera.MaxNumBuffer = 10
        self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

        if genicam.IsReadable(self.camera.ExposureTimeRaw):
            self.sigExposureRead.emit(
                self.camera.ExposureTimeRaw.Min,
                self.camera.ExposureTimeRaw.Max,
                self.camera.ExposureTimeRaw.Value,
            )
        else:
            self.sigExposureRead.emit(0, 0, 0)

        while self.camera.IsGrabbing():
            # Wait for an image and then retrieve it. A timeout of 5000 ms is used.
            grabResult = self.camera.RetrieveResult(
                5000, pylon.TimeoutHandling_ThrowException
            )

            # Image grabbed successfully?
            if grabResult.GrabSucceeded():
                try:
                    self.sigGrabbed.emit(grabResult.GetArray(raw=False))
                except ValueError:
                    logging.exception("Exception while getting array from grabResult!")
                else:
                    if self.save_requested:
                        img.AttachGrabResultBuffer(grabResult)
                        filename = os.path.join(
                            SAVE_DIR,
                            f"Image__{time.strftime('%Y-%m-%d__%H-%M-%S',time.localtime())}",
                        )
                        if platform.system() == "Windows":
                            ipo = pylon.ImagePersistenceOptions()
                            ipo.SetQuality(100)
                            img.Save(pylon.ImageFileFormat_Jpeg, f"{filename}.jpg", ipo)
                        else:
                            img.Save(pylon.ImageFileFormat_Png, f"{filename}.png")
                        img.Release()
                        self.save_requested = False
            else:
                try:
                    pass
                    # print(
                    #     f"Error {grabResult.ErrorCode}: ", grabResult.ErrorDescription
                    # )
                except UnicodeDecodeError:
                    print(f"Error {grabResult.ErrorCode}")

            grabResult.Release()
            if genicam.IsWritable(self.camera.ExposureTimeRaw):
                
                if self.camera.ExposureTimeRaw.Value != self.exposure:
                    print(self.exposure)
                    self.camera.ExposureTimeRaw = self.exposure

            if genicam.IsWritable(self.camera.GammaEnable):
                if bool(self.camera.GammaEnable.Value) != self.srgb_gamma:
                    self.camera.GammaEnable = self.srgb_gamma

            if not self.live:
                self.camera.StopGrabbing()
        self.camera.Close()


class MainWindow(MainWindowGUI):
    sigExposureChanged = QtCore.Signal(int)
    sigGammaToggled = QtCore.Signal(bool)

    def __init__(self):
        super().__init__()

        # handle image grabbing
        self.frame_grabber = FrameGrabber()
        self.frame_grabber.sigGrabbed.connect(
            lambda arr: self.image_item.setImage(arr, autoLevels=False)
        )
        self.frame_grabber.sigExposureRead.connect(self.update_exposure_slider)
        # self.frame_grabber.sigFailed.connect(lambda: self.live_check.setChecked(False))

        self._devices: list[pylon.DeviceInfo] | None = None
        self.live_check.stateChanged.connect(self.toggle_grabbing)
        self.live_check.setChecked(True)

        # connect srgb and exposure settings
        self.exposure_slider.valueChanged.connect(self.set_exposure)
        self.sigExposureChanged.connect(self.frame_grabber.set_exposure)
        self.srgb_check.stateChanged.connect(
            lambda: self.sigGammaToggled.emit(self.srgb_check.isChecked())
        )
        self.sigGammaToggled.connect(self.frame_grabber.set_srgb)

        # save image
        self.save_img_btn.clicked.connect(self.save_image)
        self.save_profile_btn.setDisabled(True)  # not implemented

    def closeEvent(self, *args, **kwargs):
        self.live_check.setChecked(False)
        super().closeEvent(*args, **kwargs)

    def refresh_devices(self):
        self.camera_combo.clear()

        self._devices = []
        for d in tlf.EnumerateDevices():
            if d.GetSerialNumber() not in EXCLUDED_DEVICES:
                self._devices.append(d)

        self.camera_combo.addItems(
            [
                DEVICE_ALIASES.get(d.GetSerialNumber(), d.GetFriendlyName())
                for d in self.devices
            ]
        )

    @property
    def devices(self) -> list[pylon.DeviceInfo]:
        if self._devices is None:
            self.refresh_devices()
        return self._devices

    def update_exposure_slider(self, mn, mx, val):
        self.exposure_slider.setDisabled(mn == mx == val == 0)
        self.exposure_spin.setDisabled(mn == mx == val == 0)

        self.frame_grabber.set_exposure(val)
        
        self.exposure_slider.setMinimum(mn)
        self.exposure_slider.setMaximum(mx)
        self.exposure_spin.setMinimum(mn)
        self.exposure_spin.setMaximum(mx)
        # self.exposure_slider.blockSignals(True)
        # self.exposure_spin.blockSignals(True)
        self.exposure_slider.setValue(val)
        # self.exposure_spin.setValue(val)
        # self.exposure_spin.blockSignals(False)
        # self.exposure_slider.blockSignals(False)

    @QtCore.Slot(object)
    def set_image(self, image):
        if image.ndim == 3:
            self.image_item.setImage(np.flip(image, -1), useRGBA=True)
        else:
            self.image_item.setImage(image)

    @QtCore.Slot(int)
    def set_exposure(self, value: int):
        self.sigExposureChanged.emit(value)

    @QtCore.Slot()
    def save_image(self):
        self.frame_grabber.save_requested = True

    @QtCore.Slot()
    def toggle_grabbing(self):
        if self.live_check.isChecked():
            if len(self.devices) <= 0:
                self.live_check.setChecked(False)
            else:
                self.frame_grabber.set_device(
                    self.devices[self.camera_combo.currentIndex()]
                )
                self.frame_grabber.start()
                self.frame_grabber.live = True
        else:
            self.frame_grabber.live = False


if __name__ == "__main__":
    qapp: QtWidgets.QApplication = QtWidgets.QApplication.instance()
    if not qapp:
        qapp = QtWidgets.QApplication(sys.argv)

    win = MainWindow()
    win.show()
    win.activateWindow()

    qapp.exec()
