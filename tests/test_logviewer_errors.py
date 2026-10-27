import datetime
import os
import tempfile
import time
import traceback
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import logviewer.main as logviewer
import pandas as pd
from logviewer.logreader import LogLoader
from qtpy import QtCore, QtWidgets


class LogViewerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
            cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.config_path = Path(directory) / "config.toml"
        self.config_path.write_text(
            "[plotting]\nsecondary_axes = []\ncolors = [[255, 0, 0]]\n",
            encoding="utf-8",
        )
        self.settings_data = {"config_file": str(self.config_path)}
        self.settings = mock.Mock()
        self.settings.value.side_effect = lambda key, default=None: (
            self.settings_data.get(key, default)
        )
        self.settings.setValue.side_effect = self.settings_data.__setitem__
        self.stack.enter_context(
            mock.patch.object(logviewer.QtCore, "QSettings", return_value=self.settings)
        )
        self.errors = []
        self.original_critical = logviewer.MessageDialog.critical
        self.stack.enter_context(
            mock.patch.object(
                logviewer.MessageDialog, "critical", side_effect=self.capture_error
            )
        )
        self.releases = []
        with mock.patch.object(logviewer.MainWindow, "_start_load"):
            self.window = self.new_window()
        self.window.startdateedit.setDateTime(
            QtCore.QDateTime(QtCore.QDate(2026, 10, 27), QtCore.QTime(0, 0))
        )
        self.window.enddateedit.setDateTime(
            QtCore.QDateTime(QtCore.QDate(2026, 10, 27), QtCore.QTime(12, 35))
        )

    def new_window(self):
        window = logviewer.MainWindow()
        self.addCleanup(self.close_window, window)
        return window

    def wait_until(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() >= deadline:
                self.fail("Timed out waiting for the background load")
            self.app.processEvents()
            time.sleep(0.001)

    def wait_idle(self, window=None):
        window = self.window if window is None else window
        self.wait_until(
            lambda: window._active_task is None and window._pending_request is None
        )

    def close_window(self, window):
        for release in self.releases:
            release.set()
        window.update_timer.stop()
        window.updatetime_check.blockSignals(True)
        window.updatetime_check.setChecked(False)
        window.updatetime_check.blockSignals(False)
        self.wait_idle(window)
        # Dispose graphics while their Python wrappers are still alive.
        for plot in window.plot_items:
            plot.clear()
            for view in getattr(plot, "vbs", [plot.vb]):
                view.clear()
        window.graphics_layout.close()
        central_widget = window.takeCentralWidget()
        central_widget.deleteLater()
        window.close()
        window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete
        )

    def capture_error(self, *args, **kwargs):
        self.errors.append((args, kwargs, traceback.format_exc()))

    @staticmethod
    def temperature_frame():
        return pd.DataFrame(
            {"Sample": [2.5]},
            index=pd.DatetimeIndex([datetime.datetime(2026, 10, 27, 12, 34, 56)]),
        )

    @staticmethod
    def pressure_frame():
        return pd.DataFrame(
            {"IG Main": [1e-8], "IG Middle": [2e-8]},
            index=pd.DatetimeIndex([datetime.datetime(2026, 10, 27, 12, 34, 56)]),
        )

    def load_frames(self, temperature, pressure):
        with mock.patch.object(
            self.window._log_loader, "load", return_value=(temperature, pressure)
        ):
            assert self.window.load_data() is True
            self.wait_idle()

    def assert_load_error(self, message):
        assert len(self.errors) == 1
        args, kwargs, details = self.errors[0]
        assert args[1] == "Failed to Load Logs"
        assert message in kwargs["informative_text"]
        assert "Traceback (most recent call last)" in details
        return details


class LogViewerErrorTests(LogViewerTestCase):
    def test_startup_parse_failure_is_reported(self):
        with mock.patch.object(
            LogLoader, "load", side_effect=ValueError("invalid log time")
        ):
            window = self.new_window()
            self.wait_idle(window)
        details = self.assert_load_error("invalid log time")
        assert "ValueError: invalid log time" in details

    def test_manual_load_reports_chained_reader_error_and_keeps_previous_data(self):
        old_temperature = self.temperature_frame()
        old_pressure = self.pressure_frame()
        self.window.df = old_temperature
        self.window.df_mg15 = old_pressure

        def read_pressure(*args, **kwargs):
            raise ValueError("cannot parse pressure log") from OSError(
                "network share disconnected"
            )

        with mock.patch.object(
            self.window._log_loader, "load", side_effect=read_pressure
        ):
            self.window.load_btn.click()
            self.wait_idle()
        details = self.assert_load_error("cannot parse pressure log")
        assert "read_pressure" in details
        assert "OSError: network share disconnected" in details
        assert "The above exception was the direct cause" in details
        assert "ValueError: cannot parse pressure log" in details
        assert self.window.df is old_temperature
        assert self.window.df_mg15 is old_pressure

    def test_error_dialog_contains_the_full_chained_traceback(self):
        dialogs = []

        def fake_exec(dialog):
            dialogs.append(
                (
                    dialog.windowTitle(),
                    dialog.informativeText(),
                    dialog._details.toPlainText(),
                )
            )
            return QtWidgets.QDialog.DialogCode.Accepted

        def read_temperature(*args, **kwargs):
            raise ValueError("Invalid <timestamp> & data") from OSError(
                "Could not open <file.csv> & share"
            )

        with (
            mock.patch.object(
                logviewer.MessageDialog, "critical", self.original_critical
            ),
            mock.patch.object(logviewer.MessageDialog, "exec", fake_exec),
            mock.patch.object(
                self.window._log_loader, "load", side_effect=read_temperature
            ),
        ):
            assert self.window.load_data() is True
            self.wait_idle()
        assert len(dialogs) == 1
        title, info, details = dialogs[0]
        assert title == "Failed to Load Logs"
        assert "Invalid <timestamp> & data" in info
        assert "Traceback (most recent call last)" in details
        assert "read_temperature" in details
        assert "OSError: Could not open <file.csv> & share" in details
        assert "The above exception was the direct cause" in details
        assert "ValueError: Invalid <timestamp> & data" in details

    def test_configuration_failure_is_reported(self):
        self.config_path.write_text("[plotting\n", encoding="utf-8")
        self.load_frames(self.temperature_frame(), None)
        assert len(self.errors) == 1
        assert "tomlkit" in self.errors[0][2]
        assert "Unexpected character" in self.errors[0][1]["informative_text"]

    def test_plotting_failure_during_load_is_reported(self):
        with mock.patch.object(
            self.window, "_update_plot", side_effect=RuntimeError("invalid plot data")
        ):
            self.load_frames(None, self.pressure_frame())
        self.assert_load_error("invalid plot data")

    def test_direct_plotting_failure_is_reported(self):
        with mock.patch.object(
            self.window, "_update_plot", side_effect=RuntimeError("invalid plot data")
        ):
            self.window.update_plot()
        self.assert_load_error("invalid plot data")

    def test_plotting_failure_keeps_new_data_consistent_with_new_legend(self):
        old_frame = self.temperature_frame().rename(columns={"Sample": "Old sensor"})
        new_frame = self.temperature_frame().assign(Shield=3.5)
        self.load_frames(old_frame, None)
        with mock.patch.object(
            self.window, "_update_plot", side_effect=RuntimeError("invalid plot data")
        ):
            self.load_frames(new_frame, None)
        self.assert_load_error("invalid plot data")
        assert self.window.df is new_frame
        self.window.legendtable.set_enabled(1, True)
        self.window.curve_toggled()

    def test_enabling_refresh_does_not_restart_timer_after_failure(self):
        with mock.patch.object(
            self.window._log_loader, "load", side_effect=OSError("log file unavailable")
        ):
            self.window.updatetime_check.setChecked(True)
            self.wait_idle()
        self.assert_load_error("log file unavailable")
        assert not self.window.updatetime_check.isChecked()
        assert not self.window.update_timer.isActive()

    def test_timer_failure_disables_further_refreshes(self):
        with mock.patch.object(
            self.window._log_loader,
            "load",
            return_value=(None, self.pressure_frame()),
        ):
            self.window.updatetime_check.setChecked(True)
            self.wait_idle()
        assert self.window.update_timer.isActive()
        assert not self.errors
        with mock.patch.object(
            self.window._log_loader, "load", side_effect=OSError("log file unavailable")
        ):
            self.window.update_timer.timeout.emit()
            self.wait_idle()
        self.assert_load_error("log file unavailable")
        assert not self.window.updatetime_check.isChecked()
        assert not self.window.update_timer.isActive()

    def test_no_data_failure_identifies_range_and_log_directories(self):
        for frame in (None, pd.DataFrame()):
            with self.subTest(frame=type(frame).__name__):
                self.errors.clear()
                self.load_frames(frame, frame)
                assert len(self.errors) == 1
                details = self.errors[0][2]
                assert "ValueError" in details
                assert "2026-10-27" in details
                assert logviewer.CRYO_DIR in details
                assert logviewer.MG15_DIR in details

    def test_one_available_source_can_be_loaded(self):
        for temperature, pressure in (
            (self.temperature_frame(), None),
            (None, self.pressure_frame()),
            (self.temperature_frame(), pd.DataFrame()),
            (pd.DataFrame(), self.pressure_frame()),
        ):
            with self.subTest(temperature=temperature is not None):
                self.load_frames(temperature, pressure)
                assert not self.errors
                assert self.window.df is (
                    temperature
                    if temperature is not None and not temperature.empty
                    else None
                )
                assert self.window.df_mg15 is (
                    pressure if pressure is not None and not pressure.empty else None
                )

    def test_partial_load_clears_previous_curves_for_missing_source(self):
        self.window.pressure_check.setChecked(True)
        for missing_temperature in (True, False):
            with self.subTest(missing_temperature=missing_temperature):
                temperature = self.temperature_frame()
                pressure = self.pressure_frame()
                self.load_frames(temperature, pressure)
                missing_plot = (
                    self.window.plot0 if missing_temperature else self.window.plot1
                )
                remaining_plot = (
                    self.window.plot1 if missing_temperature else self.window.plot0
                )
                assert all(curve.xData is not None for curve in missing_plot.plots)
                for curve in missing_plot.plots:
                    curve.curve.target.show()
                self.load_frames(
                    None if missing_temperature else temperature,
                    pressure if missing_temperature else None,
                )
                assert not self.errors
                assert all(curve.xData is None for curve in missing_plot.plots)
                assert all(
                    not curve.curve.target.isVisible() for curve in missing_plot.plots
                )
                assert all(curve.xData is not None for curve in remaining_plot.plots)


if __name__ == "__main__":
    unittest.main()
