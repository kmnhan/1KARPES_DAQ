import datetime
import threading
from unittest import mock

import logviewer._loading as loading
import logviewer.main as logviewer
from qtpy import QtCore
from test_logviewer_errors import LogViewerTestCase


class LogViewerLoadingTests(LogViewerTestCase):
    def event(self):
        event = threading.Event()
        self.releases.append(event)
        return event

    def test_file_and_configuration_reads_leave_the_gui_responsive(self):
        started, release, pulse = self.event(), self.event(), self.event()
        threads = {}
        original_config_load = loading.tomlkit.load
        original_apply = self.window._apply_result

        def read_files(*args, **kwargs):
            threads["files"] = threading.get_ident()
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release file read")
            return self.temperature_frame(), self.pressure_frame()

        def read_config(*args, **kwargs):
            threads["config"] = threading.get_ident()
            return original_config_load(*args, **kwargs)

        def apply_result(*args, **kwargs):
            threads["apply"] = threading.get_ident()
            return original_apply(*args, **kwargs)

        main_thread = threading.get_ident()
        with (
            mock.patch.object(self.window._log_loader, "load", side_effect=read_files),
            mock.patch.object(loading.tomlkit, "load", side_effect=read_config),
            mock.patch.object(self.window, "_apply_result", side_effect=apply_result),
        ):
            assert self.window.load_data() is True
            self.wait_until(started.is_set)
            assert not self.window.loading_label.isHidden()
            QtCore.QTimer.singleShot(0, pulse.set)
            self.wait_until(pulse.is_set)
            assert self.window._active_task is not None
            release.set()
            self.wait_idle()
        assert not self.errors
        assert threads["files"] != main_thread
        assert threads["config"] == threads["files"]
        assert threads["apply"] == main_thread
        assert self.window.loading_label.isHidden()

    def test_auto_and_explicit_concurrency_are_forwarded_and_persisted(self):
        assert self.window.concurrency_spin.value() == 0
        assert self.window.concurrency_spin.text() == "Auto"
        for value, expected in ((0, None), (7, 7), (0, None)):
            with (
                self.subTest(value=value),
                mock.patch.object(
                    self.window._log_loader,
                    "load",
                    return_value=(None, self.pressure_frame()),
                ) as read,
            ):
                self.window.concurrency_spin.setValue(value)
                assert self.window.load_data() is True
                self.wait_idle()
                assert read.call_args.kwargs["max_workers"] == expected
        assert self.settings_data["max_workers"] == 0
        self.window.concurrency_spin.setValue(9)
        with mock.patch.object(logviewer.MainWindow, "_start_load"):
            restored = self.new_window()
        assert restored.concurrency_spin.value() == 9

    def test_latest_request_replaces_pending_request_without_parallel_loads(self):
        started, release = self.event(), self.event()
        requests = []
        first = self.pressure_frame()
        latest = first * 3

        def read_files(start, end, **kwargs):
            requests.append((start, end))
            if len(requests) == 1:
                started.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release file read")
                return None, first
            return None, latest

        with mock.patch.object(self.window._log_loader, "load", side_effect=read_files):
            self.window.load_data()
            self.wait_until(started.is_set)
            self.window.enddateedit.setDateTime(
                self.window.enddateedit.dateTime().addSecs(60)
            )
            self.window.load_data()
            self.window.enddateedit.setDateTime(
                self.window.enddateedit.dateTime().addSecs(60)
            )
            self.window.load_data()
            assert len(requests) == 1
            release.set()
            self.wait_idle()
        assert len(requests) == 2
        assert requests[-1][1] == self.window.end_datetime
        assert self.window.df_mg15 is latest
        assert not self.errors

    def test_changing_range_without_loading_discards_old_result(self):
        started, release = self.event(), self.event()
        old = self.pressure_frame()
        self.window.df_mg15 = old

        def read_files(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release file read")
            return None, old * 2

        with mock.patch.object(self.window._log_loader, "load", side_effect=read_files):
            self.window.load_data()
            self.wait_until(started.is_set)
            self.window.enddateedit.setDateTime(
                self.window.enddateedit.dateTime().addSecs(60)
            )
            release.set()
            self.wait_idle()
        assert self.window.df_mg15 is old
        assert not self.errors

    def test_superseded_error_does_not_interrupt_new_request(self):
        started, release = self.event(), self.event()
        reads = 0
        frame = self.pressure_frame()

        def read_files(*args, **kwargs):
            nonlocal reads
            reads += 1
            if reads == 1:
                started.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release file read")
                raise ValueError("Error from obsolete request")
            return None, frame

        with mock.patch.object(self.window._log_loader, "load", side_effect=read_files):
            self.window.load_data()
            self.wait_until(started.is_set)
            self.window.load_data()
            release.set()
            self.wait_idle()
        assert reads == 2
        assert self.window.df_mg15 is frame
        assert not self.errors

    def test_refresh_timer_waits_for_loading_to_finish(self):
        started, release = self.event(), self.event()

        def read_files(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release file read")
            return None, self.pressure_frame()

        with mock.patch.object(self.window._log_loader, "load", side_effect=read_files):
            self.window.updatetime_check.setChecked(True)
            self.wait_until(started.is_set)
            assert not self.window.update_timer.isActive()
            release.set()
            self.wait_idle()
        assert self.window.update_timer.isActive()
        assert not self.errors

    def test_closing_waits_for_running_reads_without_destroying_the_thread(self):
        started, release = self.event(), self.event()

        def read_files(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release file read")
            return None, self.pressure_frame()

        with mock.patch.object(self.window._log_loader, "load", side_effect=read_files):
            self.window.show()
            self.window.load_data()
            self.wait_until(started.is_set)
            task = self.window._active_task
            assert self.window.close() is False
            assert self.window._closing
            assert task.isInterruptionRequested()
            assert task.isRunning()
            assert not self.window.isEnabled()
            release.set()
            self.wait_idle()
        assert not self.window.isVisible()
        assert self.window.df_mg15 is None
        assert not self.errors

    def test_invalid_range_reports_validation_without_starting_a_worker(self):
        self.window.startdateedit.setDateTime(
            QtCore.QDateTime(
                QtCore.QDate(2026, 10, 28),
                QtCore.QTime(0, 0),
            )
        )
        with mock.patch.object(logviewer.QtWidgets.QMessageBox, "critical") as error:
            assert self.window.load_data() is False
        assert error.call_args.args[1] == "Invalid Date Range"
        assert self.window._active_task is None
        assert not self.window.update_timer.isActive()
