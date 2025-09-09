from __future__ import annotations

import contextlib
import datetime
import logging
import os
import sys

# import cv2
import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
import xarray as xr
from pypylon import genicam, pylon
from qt_extensions.colors import BetterColorBarItem, BetterImageItem
from qtpy import QtCore, QtGui, QtWidgets, uic

log = logging.getLogger("pyloncam")
log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)


with contextlib.suppress(Exception):
    os.chdir(sys._MEIPASS)

EXCLUDED_DEVICES: tuple[str, ...] = (
    "40049666",
)  #: Tuple of string of serial numbers to exclude from search.

DEVICE_ALIASES: dict[str, str] = {
    "40155047": "sample camera"
}  #: Mapping from serial number to custom label.

SAVE_DIR: str = "D:/Camera/Sample Camera"  #: Directory to save the image to.

PIXEL_BITS: int = 8  #: Pixel format bits, 8 or 10 for our sample camera.

tlf: pylon.TlFactory = pylon.TlFactory.GetInstance()  #: The transport layer factory.
img: pylon.PylonImage = pylon.PylonImage()  #: Handles image saving.


def format_datetime(dt: datetime.datetime) -> str:
    return dt.isoformat(sep="_", timespec="milliseconds").replace(":", "-")


class CameraConfiguration(pylon.ConfigurationEventHandler, QtCore.QObject):
    def OnOpened(self, camera):
        try:
            # # Maximize the Image AOI.
            # if genicam.IsWritable(camera.OffsetX):
            #     camera.OffsetX.Value = camera.OffsetX.Min
            # if genicam.IsWritable(camera.OffsetY):
            #     camera.OffsetY.Value = camera.OffsetY.Min
            # camera.Width.Value = camera.Width.Max
            # camera.Height.Value = camera.Height.Max

            # Flip image.
            if genicam.IsWritable(camera.ReverseX):
                camera.ReverseX.Value = True
            if genicam.IsWritable(camera.ReverseY):
                camera.ReverseY.Value = False

            if genicam.IsWritable(camera.GainAuto):
                camera.GainAuto.Value = "Off"

            if genicam.IsWritable(camera.GammaSelector):
                camera.GammaSelector.Value = "sRGB"

            if genicam.IsWritable(camera.ExposureAuto):
                camera.ExposureAuto.Value = "Off"

            # Set the pixel data format.
            camera.PixelFormat.Value = f"Mono{PIXEL_BITS}"
        except genicam.GenericException as e:
            raise genicam.RuntimeException(
                "Could not apply configuration."
                "GenICam::GenericException caught in OnOpened method"
            ) from e


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


class ConfigDialog(*uic.loadUiType("cameramonitor_config.ui")):
    def __init__(
        self, parent: QtWidgets.QWidget | None = None, *, settings: QtCore.QSettings
    ):
        super().__init__(parent=parent)
        self.setupUi(self)
        self.setWindowTitle("Camera Monitor Settings")
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self.settings: QtCore.QSettings = settings
        self.populate()

    def show(self):
        self.populate()
        super().show()

    def populate(self):
        self.horiz_spin.setValue(float(self.settings.value("calibration/h", 0.011)))
        self.vert_spin.setValue(float(self.settings.value("calibration/v", 0.011)))
        self.hoff_spin.setValue(float(self.settings.value("calibration/hoff", 0.0)))
        self.voff_spin.setValue(float(self.settings.value("calibration/voff", 0.0)))
        self.autosave_spin.setValue(
            float(self.settings.value("autosave_interval", 300))
        )

    def accept(self):
        self.settings.setValue("calibration/h", self.horiz_spin.value())
        self.settings.setValue("calibration/v", self.vert_spin.value())
        self.settings.setValue("calibration/hoff", self.hoff_spin.value())
        self.settings.setValue("calibration/voff", self.voff_spin.value())
        self.settings.setValue("autosave_interval", self.autosave_spin.value())
        super().accept()


uiclass, baseclass = uic.loadUiType("pyloncam.ui")


class MainWindowGUI(uiclass, baseclass):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.setWindowTitle("1KARPES Camera Monitor")

        # add plot and image
        self.plot_item = self.graphics_layout.addPlot()
        self.plot_item.setDefaultPadding(0)
        # self.plot_item.vb.invertY(False)

        self.plot_item.vb.setCursor(QtGui.QCursor(QtCore.Qt.CrossCursor))
        self.image_item = BetterImageItem(axisOrder="row-major")
        self.plot_item.addItem(self.image_item)

        # target & circle roi
        self.target = pg.TargetItem(pen="r")
        self.circle = pg.CircleROI(self.target.pos(), size=(1138, 1138), movable=False)
        self.target.sigPositionChanged.connect(self.target_moved)
        self.target_check.stateChanged.connect(
            lambda: self.target.setVisible(self.target_check.isChecked())
        )
        self.target_check.setChecked(True)
        self.actioncircle.toggled.connect(
            lambda: self.circle.setVisible(self.actioncircle.isChecked())
        )
        self.actioncircle.setChecked(False)

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
        self.actioncrosshair.toggled.connect(
            lambda: [
                ln.setVisible(self.actioncrosshair.isChecked()) for ln in self.lines
            ]
        )

        # color related widgets
        self.cmap_combo.setDefaultCmap("gray")
        self.cmap_combo.textActivated.connect(self.update_cmap)
        self.gamma_widget.setValue(0.5)
        self.gamma_widget.valueChanged.connect(self.update_cmap)
        self.actioninvert.toggled.connect(self.update_cmap)
        self.contrast_check.stateChanged.connect(self.update_cmap)
        self.update_cmap()

        # add colorbar
        self.cbar = BetterColorBarItem(limits=(0, 2**PIXEL_BITS - 1))
        self.cbar.setImageItem(image=self.image_item, insert_in=self.plot_item)
        self.cbar.set_width(20)
        self.auto_clim_check.stateChanged.connect(
            lambda: self.cbar.setAutoLevels(self.auto_clim_check.isChecked())
        )

        # get settings
        self.settings = QtCore.QSettings("erlab", "Frame Grabber")
        self.load_pos_from_settings()

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
        self.pos_table.cellChanged.connect(self.write_pos_to_settings)
        for i in (0, 3):
            self.pos_table.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeToContents
            )
        self.pos_table.selectRow(0)
        self.load_btn.click()

        # Setup autosave timer
        self.autosave_timer = QtCore.QTimer(self)
        self.autosave_check.toggled.connect(self.toggle_autosave)

        # Initialize calibration factors
        self._cal_h: float = 0.011
        self._cal_v: float = 0.011
        self._off_h: float = 0.0
        self._off_v: float = 0.0

        # Config dialog
        self.config_dialog = ConfigDialog(self, settings=self.settings)
        self.config_dialog.accepted.connect(self.refresh_settings)
        self.refresh_settings()
        self.actionsettings.triggered.connect(lambda: self.config_dialog.show())

    @QtCore.Slot(bool)
    def toggle_autosave(self, value: bool):
        if value:
            self.autosave_timer.start()
        else:
            self.autosave_timer.stop()

    @QtCore.Slot()
    def target_moved(self):
        w, h = self.circle.size()
        x, y = self.target.pos()
        self.circle.setPos(x - w / 2, y - h / 2)

    @QtCore.Slot()
    def load_position(self):
        row_idx = self.pos_table.currentRow()
        x_item, y_item = (
            self.pos_table.item(row_idx, 1),
            self.pos_table.item(row_idx, 2),
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

    def update_rect(self):
        raise NotImplementedError

    @property
    def rect(self) -> QtCore.QRectF:
        raise NotImplementedError

    def refresh_settings(self):
        self._cal_h = float(self.settings.value("calibration/h", 0.011))
        self._cal_v = float(self.settings.value("calibration/v", 0.011))
        self._off_h = float(self.settings.value("calibration/hoff", 0.0))
        self._off_v = float(self.settings.value("calibration/voff", 0.0))
        self.circle.setSize((2276 * self._cal_h, 2276 * self._cal_h))
        self.target_moved()
        self.update_rect()
        self.autosave_timer.setInterval(
            int(float(self.settings.value("autosave_interval", 300)) * 1e3)
        )

    def load_pos_from_settings(self):
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

    def write_pos_to_settings(self):
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
            reverse=self.actioninvert.isChecked(),
            highContrast=self.contrast_check.isChecked(),
            update=True,
        )

    def mouse_moved(self, pos):
        # if not self.plot_item.vb.itemBoundingRect(self.image_item).contains(pos):
        if not self.plot_item.sceneBoundingRect().contains(pos):
            # self.statusBar().clearMessage()
            return
        point = self.plot_item.vb.mapSceneToView(pos)
        # self.statusBar().showMessage(f"X = {point.x():.6g}, Z = {point.y():.6g}")
        if self.actioncrosshair.isChecked():
            self.lines[0].setPos(point.x())
            self.lines[1].setPos(point.y())


class FrameGrabber(QtCore.QThread):
    sigGrabbed = QtCore.Signal(object, object)
    sigExposureRead = QtCore.Signal(int, int, int)
    # sigFailed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self._live: bool = True
        self._camera = None
        self.save_requested: bool = False
        self._img_file: str | None = None
        self.mutex: QtCore.QMutex | None = None
        self.set_srgb(False)

    @property
    def camera(self) -> pylon.InstantCamera:
        return self._camera

    @property
    def live(self) -> bool:
        return self._live

    @live.setter
    def live(self, value: bool):
        if self.mutex is not None:
            self.mutex.lock()
        self._live = value
        if self.mutex is not None:
            self.mutex.unlock()

    @QtCore.Slot()
    @QtCore.Slot(str)
    def request_save(self, filename: str | None = None):
        if self.mutex is not None:
            self.mutex.lock()

        self.save_requested: bool = True
        self._img_file: str | None = filename

        if self.mutex is not None:
            self.mutex.unlock()

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
        if self.mutex is not None:
            self.mutex.lock()
        self.exposure: int = value
        if self.mutex is not None:
            self.mutex.unlock()

    @QtCore.Slot(bool)
    def set_srgb(self, value: bool):
        if self.mutex is not None:
            self.mutex.lock()
        self.srgb_gamma: bool = value
        if self.mutex is not None:
            self.mutex.unlock()

    def run(self):
        self.mutex = QtCore.QMutex()

        # save memory
        self.camera.MaxNumBuffer = 5
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
            grab_time = datetime.datetime.now()
            grab_result = self.camera.RetrieveResult(
                5000, pylon.TimeoutHandling_ThrowException
            )

            # Image grabbed successfully?
            if grab_result.GrabSucceeded():
                try:
                    self.sigGrabbed.emit(grab_time, grab_result.GetArray(raw=False))
                except ValueError:
                    log.exception("Exception while getting array from grabResult!")
                else:
                    if self.save_requested:
                        img.AttachGrabResultBuffer(grab_result)

                        if self._img_file is None:
                            filename = os.path.join(
                                SAVE_DIR, f"Image_{format_datetime(grab_time)}.tiff"
                            )
                        else:
                            filename = self._img_file
                        img.Save(pylon.ImageFileFormat_Tiff, filename)
                        img.Release()

                        self.save_requested = False
                        self._img_file = None

            grab_result.Release()
            if genicam.IsWritable(self.camera.ExposureTimeRaw) and (
                self.camera.ExposureTimeRaw.Value != self.exposure
            ):
                self.camera.ExposureTimeRaw.Value = self.exposure

            if genicam.IsWritable(self.camera.GammaEnable) and (
                bool(self.camera.GammaEnable.Value) != self.srgb_gamma
            ):
                self.camera.GammaEnable.Value = self.srgb_gamma

            if not self.live:
                self.camera.StopGrabbing()
        self.camera.Close()
        self.mutex = None


class MainWindow(MainWindowGUI):
    sigExposureChanged = QtCore.Signal(int)
    sigGammaToggled = QtCore.Signal(bool)

    def __init__(self):
        super().__init__()

        # Store grabbed time here
        self.grab_time: datetime.datetime | None = None

        # Handle image grabbing
        self.frame_grabber = FrameGrabber()
        self.frame_grabber.sigGrabbed.connect(self.grabbed)
        self.frame_grabber.sigExposureRead.connect(self.update_exposure_slider)

        self._devices: list[pylon.DeviceInfo] | None = None
        self.live_check.stateChanged.connect(self.toggle_grabbing)
        self.live_check.setChecked(True)

        # Connect srgb and exposure settings
        self.exposure_slider.valueChanged.connect(self.set_exposure)
        self.sigExposureChanged.connect(self.frame_grabber.set_exposure)
        self.srgb_check.stateChanged.connect(
            lambda: self.sigGammaToggled.emit(self.srgb_check.isChecked())
        )
        self.sigGammaToggled.connect(self.frame_grabber.set_srgb)

        # Setup image saving
        self.actionsave.triggered.connect(self.save_image)
        self.actionsaveh5.triggered.connect(self.save_hdf5)
        self.actionsaveas.triggered.connect(self.save_dialog)
        self.autosave_timer.timeout.connect(self.save_image)

    def save_dialog(self):
        # Set the file filters
        filters = [
            "TIFF Image (*.tiff *.tif)",
            "HDF5 File (*.h5)",
        ]

        # Show the file dialog
        file_dialog = QtWidgets.QFileDialog()
        file_dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setFileMode(QtWidgets.QFileDialog.FileMode.AnyFile)
        file_dialog.setNameFilters(filters)
        file_dialog.setDirectory(SAVE_DIR)

        if file_dialog.exec():
            file = file_dialog.selectedFiles()[0]
            self.save_image_as(file)

    def closeEvent(self, *args, **kwargs):
        self.live_check.setChecked(False)
        self.frame_grabber.wait(2000)
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

    def image_to_xarray(self, image) -> xr.DataArray:
        shape = image.shape
        xlim, zlim = self._cal_h * (shape[1] - 1) / 2, self._cal_v * (shape[0] - 1) / 2
        return xr.DataArray(
            image,
            dims=("z", "x"),
            coords={
                "z": np.linspace(-zlim, zlim, shape[0]) + self._off_v,
                "x": np.linspace(-xlim, xlim, shape[1]) + self._off_h,
            },
        )

    def get_rect(self, shape) -> QtCore.QRectF:
        x, y = -self._cal_h * (shape[1] - 1) / 2, -self._cal_v * (shape[0] - 1) / 2
        w, h = -2 * x, -2 * y
        x += self._off_h
        y += self._off_v
        return QtCore.QRectF(x, y, w, h)

    @QtCore.Slot(object, object)
    def grabbed(self, grabtime: datetime.datetime, image: npt.NDArray):
        self.grab_time: datetime.datetime = grabtime
        image = np.flip(image, axis=0)

        if self.image_item.image is None:
            self.image_item.setImage(image, autoLevels=False, axisOrder="row-major")
            # self.update_rect()
            self.image_item.setRect(self.get_rect(image.shape))
        else:
            self.image_item.setImage(
                image,
                autoLevels=False,
                axisOrder="row-major",
                rect=self.get_rect(image.shape),
            )
        self._image_array = image

        # msg = "Last Update "
        # msg += self.grab_time.isoformat(sep=" ", timespec="milliseconds")

        # max_val = 2**PIXEL_BITS - 1
        # if (
        #     np.amax(self._image_array) == max_val
        #     and sum(self._image_array.flatten() == max_val) > 1
        # ):
        #     msg += " | "
        #     msg += "Saturation detected! Consider lowering exposure."\
        # self.statusBar().showMessage(msg)
        # self.statusBar().showMessage(
        #     f"focus parameter: {cv2.Laplacian(image, cv2.CV_64F).var()}"
        # )

    @QtCore.Slot()
    def update_rect(self):
        with contextlib.suppress(AttributeError):
            self.image_item.setRect(self.get_rect(self.image_item.image.shape))

    # @QtCore.Slot(object)
    # def set_image(self, image):
    #     # I don't remember why this method exists...
    #     if image.ndim == 3:
    #         self.image_item.setImage(np.flip(image, -1), useRGBA=True)
    #     else:
    #         self.image_item.setImage(image)

    @QtCore.Slot(int)
    def set_exposure(self, value: int):
        self.sigExposureChanged.emit(value)

    @QtCore.Slot()
    def save_image(self):
        self.frame_grabber.request_save()

    @QtCore.Slot(str)
    def save_image_as(self, filename: str):
        if filename.endswith(".h5"):
            self.save_hdf5(filename)
        else:
            self.frame_grabber.request_save(filename)

    @QtCore.Slot()
    def save_hdf5(self, filename: str | None = None):
        data = self.image_to_xarray(self._image_array)

        if filename is None:
            filename = os.path.join(
                SAVE_DIR, f"Image_{format_datetime(self.grab_time)}.h5"
            )

        # Compatibility with Igor HDF5 loader
        scaling = [[1, 0]]
        for i in range(data.ndim):
            coord = data[data.dims[i]].values
            delta = coord[1] - coord[0]
            scaling.append([delta, coord[0]])
        if data.ndim == 4:
            scaling[0] = scaling.pop(-1)
        data.attrs["IGORWaveScaling"] = scaling

        data.to_netcdf(
            filename,
            encoding={
                var: {"compression": "gzip", "compression_opts": 9}
                for var in data.coords
            },
            engine="h5netcdf",
            invalid_netcdf=True,
        )

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
            self.actionsave.setEnabled(True)
        else:
            self.frame_grabber.live = False
            self.actionsave.setEnabled(False)


if __name__ == "__main__":
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setWindowIcon(QtGui.QIcon("./icon.ico"))
    qapp.setStyle("Fusion")

    win = MainWindow()
    win.show()
    win.activateWindow()

    qapp.exec()
