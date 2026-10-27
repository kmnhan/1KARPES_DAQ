# ruff: noqa: PT027
import datetime
import os
import tempfile
import threading
import unittest
from collections import Counter
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

import pandas as pd

from logviewer import logreader


class LogLoadingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cryo = Path(self.directory.name) / "temperature"
        self.pressure = Path(self.directory.name) / "pressure"
        self.cryo.mkdir()
        self.pressure.mkdir()
        self.start = datetime.datetime(2026, 10, 25)
        self.end = datetime.datetime(2026, 10, 28, 23, 59, 59)
        self.loader = logreader.LogLoader()

    def write_logs(self, count=1):
        for day in range(count):
            value = self.start + datetime.timedelta(days=day, hours=12)
            filename = value.strftime("%y%m%d.csv")
            (self.cryo / filename).write_text(
                f"Time,Sample\n{value.isoformat()},2.5\n", encoding="utf-8"
            )
            (self.pressure / filename).write_text(
                f"{value.isoformat()},1e-8,2e-8\n", encoding="utf-8"
            )

    def load(self, loader=None, *, start=None, end=None, **kwargs):
        return (self.loader if loader is None else loader).load(
            self.start if start is None else start,
            self.end if end is None else end,
            cryo_dir=str(self.cryo),
            pressure_dir=str(self.pressure),
            **kwargs,
        )

    def test_auto_uses_executor_default_and_explicit_workers_are_capped_to_jobs(self):
        self.write_logs()
        with mock.patch.object(
            logreader, "ThreadPoolExecutor", wraps=ThreadPoolExecutor
        ) as executor:
            self.load(max_workers=None)
        executor.assert_called_once()
        assert executor.call_args.kwargs.get("max_workers") is None
        with mock.patch.object(
            logreader, "ThreadPoolExecutor", wraps=ThreadPoolExecutor
        ) as executor:
            self.load(
                logreader.LogLoader(),
                end=self.start + datetime.timedelta(hours=23),
                max_workers=32,
            )
        executor.assert_called_once_with(max_workers=2)

    def test_cached_file_signatures_are_checked_in_parallel_workers(self):
        self.write_logs()
        end = self.start + datetime.timedelta(hours=23)
        self.load(end=end)
        signature = logreader._signature
        barrier = threading.Barrier(2, timeout=5)
        worker_ids = set()
        lock = threading.Lock()

        def check_signature(path):
            with lock:
                worker_ids.add(threading.get_ident())
            barrier.wait()
            return signature(path)

        with mock.patch.object(logreader, "_signature", side_effect=check_signature):
            temperature, pressure = self.load(end=end, max_workers=2)
        assert len(temperature) == len(pressure) == 1
        assert len(worker_ids) == 2
        assert threading.get_ident() not in worker_ids

    def test_file_reading_runs_concurrently_with_the_requested_limit(self):
        self.write_logs(4)
        parser = logreader.parse_single_mg15
        barrier = threading.Barrier(2, timeout=5)
        lock = threading.Lock()
        active = 0
        peak = 0
        worker_ids = set()

        def read_pressure(path):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                worker_ids.add(threading.get_ident())
            try:
                barrier.wait()
                return parser(path)
            finally:
                with lock:
                    active -= 1

        frame = logreader.get_log(
            self.start, self.end, str(self.pressure), read_pressure, max_workers=2
        )
        assert len(frame) == 4
        assert peak == 2
        assert len(worker_ids) == 2
        assert threading.get_ident() not in worker_ids

    def test_both_sources_share_one_pool(self):
        self.write_logs()
        barrier = threading.Barrier(2, timeout=5)
        cryo_parser = logreader.parse_single_cryo
        pressure_parser = logreader.parse_single_mg15

        def read_cryo(path):
            barrier.wait()
            return cryo_parser(path)

        def read_pressure(path):
            barrier.wait()
            return pressure_parser(path)

        with (
            mock.patch.object(logreader, "parse_single_cryo", side_effect=read_cryo),
            mock.patch.object(
                logreader, "parse_single_mg15", side_effect=read_pressure
            ),
            mock.patch.object(
                logreader, "ThreadPoolExecutor", wraps=ThreadPoolExecutor
            ) as executor,
        ):
            temperature, pressure = self.load(max_workers=2)
        executor.assert_called_once_with(max_workers=2)
        assert len(temperature) == len(pressure) == 1

    def test_serial_and_parallel_results_match(self):
        self.write_logs(4)
        serial = self.load(logreader.LogLoader(), max_workers=1)
        parallel = self.load(logreader.LogLoader(), max_workers=4)
        for expected, result in zip(serial, parallel, strict=True):
            pd.testing.assert_frame_equal(result, expected)
            assert result.index.is_monotonic_increasing

    def test_public_reader_accepts_unhashable_callable_instances(self):
        self.write_logs(2)
        parser = logreader.parse_single_mg15

        @dataclass
        class Reader:
            scale: float = 2.0

            def __call__(self, path):
                return parser(path) * self.scale

        frame = logreader.get_log(
            self.start, self.end, str(self.pressure), Reader(), max_workers=2
        )
        assert frame["IG Main"].to_list() == [2e-8, 2e-8]

    def test_cache_distinguishes_equal_callable_instances(self):
        self.write_logs()
        parser = logreader.parse_single_mg15

        @dataclass
        class Reader:
            scale: float = 1.0
            calls: int = field(default=0, compare=False)

            def __call__(self, path):
                self.calls += 1
                return parser(path) * self.scale

        first, second = Reader(), Reader()
        assert first == second
        for reader in (first, second, first):
            with mock.patch.object(logreader, "parse_single_mg15", reader):
                _, frame = self.load()
                assert frame.iloc[0, 0] == 1e-8
        assert first.calls == second.calls == 1

    def test_equal_timestamps_keep_file_order_when_workers_finish_out_of_order(self):
        self.write_logs(2)
        (self.pressure / "261025.csv").write_text(
            "2026-10-26T12:00:00,1,2\n", encoding="utf-8"
        )
        (self.pressure / "261026.csv").write_text(
            "2026-10-26T12:00:00,3,4\n", encoding="utf-8"
        )
        second_finished = threading.Event()
        parser = logreader.parse_single_mg15

        def read_pressure(path):
            frame = parser(path)
            if Path(path).name == "261025.csv":
                assert second_finished.wait(timeout=5)
            else:
                second_finished.set()
            return frame

        frame = logreader.get_log(
            self.start,
            self.end,
            str(self.pressure),
            read_pressure,
            max_workers=2,
        )
        assert frame["IG Main"].to_list() == [1, 3]

    def test_cache_reuses_files_and_invalidates_changed_content(self):
        self.write_logs()
        with mock.patch.object(
            logreader, "parse_single_mg15", wraps=logreader.parse_single_mg15
        ) as parser:
            _, first = self.load()
            # Changing an output frame must not corrupt the cached daily data.
            first.iloc[0, 0] = 99
            _, second = self.load()
            assert parser.call_count == 1
            assert second.iloc[0, 0] == 1e-8
            path = self.pressure / "261025.csv"
            previous = path.stat()
            path.write_text("2026-10-25T12:00:00,9e-8,2e-8\n", encoding="utf-8")
            os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000))
            _, changed = self.load()
        assert parser.call_count == 2
        assert changed.iloc[0, 0] == 9e-8

    def test_cache_is_byte_bounded_and_evicts_oldest_daily_frame(self):
        self.write_logs(2)
        # Isolate the pressure source so the budget holds exactly one daily frame.
        for path in self.cryo.iterdir():
            path.unlink()
        frame = logreader.parse_single_mg15(self.pressure / "261025.csv")
        budget = int(frame.memory_usage(index=True, deep=True).sum())
        loader = logreader.LogLoader(cache_max_bytes=budget)
        day_one_end = self.start + datetime.timedelta(hours=23)
        day_two = self.start + datetime.timedelta(days=1)
        day_two_end = day_two + datetime.timedelta(hours=23)
        calls = Counter()
        parser = logreader.parse_single_mg15

        def read_pressure(path):
            calls[Path(path).name] += 1
            return parser(path)

        with mock.patch.object(
            logreader, "parse_single_mg15", side_effect=read_pressure
        ):
            self.load(loader, end=day_one_end)
            self.load(loader, start=day_two, end=day_two_end)
            self.load(loader, start=day_two, end=day_two_end)
            self.load(loader, end=day_one_end)
        assert calls == {"261025.csv": 2, "261026.csv": 1}
        assert 0 < loader.cache_bytes <= budget
        loader.clear_cache()
        assert loader.cache_bytes == 0

    def test_a_file_larger_than_the_cache_budget_is_not_retained(self):
        self.write_logs()
        loader = logreader.LogLoader(cache_max_bytes=1)
        with mock.patch.object(
            logreader, "parse_single_mg15", wraps=logreader.parse_single_mg15
        ) as parser:
            self.load(loader)
            self.load(loader)
        assert parser.call_count == 2
        assert loader.cache_bytes == 0

    def test_missing_files_are_not_negatively_cached(self):
        assert self.load() == (None, None)
        self.write_logs()
        temperature, pressure = self.load()
        assert len(temperature) == len(pressure) == 1

    def test_missing_files_keep_existing_public_error_behavior(self):
        assert (
            logreader.get_log(
                self.start,
                self.end,
                str(self.pressure),
                logreader.parse_single_mg15,
                error=False,
            )
            is None
        )
        with self.assertRaisesRegex(ValueError, "No log files"):
            logreader.get_log(
                self.start, self.end, str(self.pressure), logreader.parse_single_mg15
            )

    def test_stable_parser_errors_keep_filename_and_traceback(self):
        self.write_logs()

        def broken_parser(path):
            raise ValueError("invalid timestamp")

        with self.assertRaisesRegex(ValueError, "invalid timestamp") as caught:
            logreader.get_log(self.start, self.end, str(self.pressure), broken_parser)
        assert str(self.pressure / "261025.csv") in "\n".join(
            caught.exception.__notes__
        )

    def test_file_changed_during_read_is_retried_then_cached(self):
        self.write_logs()
        parser = logreader.parse_single_mg15
        calls = 0

        def changing_parser(path):
            nonlocal calls
            calls += 1
            frame = parser(path)
            if calls == 1:
                with open(path, "a", encoding="utf-8") as stream:
                    stream.write("2026-10-25T13:00:00,3e-8,4e-8\n")
            return frame

        with mock.patch.object(
            logreader, "parse_single_mg15", side_effect=changing_parser
        ):
            _, frame = self.load()
            _, cached = self.load()
        assert calls == 2
        assert len(frame) == len(cached) == 2

    def test_an_unstable_file_is_never_cached(self):
        self.write_logs()
        for path in self.cryo.iterdir():
            path.unlink()
        parser = logreader.parse_single_mg15
        calls = 0

        def changing_parser(path):
            nonlocal calls
            calls += 1
            frame = parser(path)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(f"2026-10-25T13:{calls:02d}:00,3e-8,4e-8\n")
            return frame

        with mock.patch.object(
            logreader, "parse_single_mg15", side_effect=changing_parser
        ):
            _, first = self.load()
            assert self.loader.cache_bytes == 0
            _, second = self.load()
        assert calls == 4
        assert len(first) == 2
        assert len(second) == 4
        assert self.loader.cache_bytes == 0

    def test_transient_parser_failure_is_retried_when_the_file_changed(self):
        self.write_logs()
        parser = logreader.parse_single_mg15
        calls = 0

        def changing_parser(path):
            nonlocal calls
            calls += 1
            if calls == 1:
                with open(path, "a", encoding="utf-8") as stream:
                    stream.write("2026-10-25T13:00:00,3e-8,4e-8\n")
                raise ValueError("incomplete concurrent write")
            return parser(path)

        with mock.patch.object(
            logreader, "parse_single_mg15", side_effect=changing_parser
        ):
            _, frame = self.load()
        assert calls == 2
        assert len(frame) == 2

    def test_cancellation_before_dispatch_does_not_construct_a_pool(self):
        self.write_logs()
        with (
            mock.patch.object(logreader, "ThreadPoolExecutor") as executor,
            self.assertRaises(CancelledError),
        ):
            self.load(cancelled=lambda: True)
        executor.assert_not_called()

    def test_cancellation_prevents_queued_reads_from_starting(self):
        self.write_logs(4)
        cancelled = threading.Event()
        parser = logreader.parse_single_mg15
        calls = 0
        for path in self.cryo.iterdir():
            path.unlink()

        def cancelling_parser(path):
            nonlocal calls
            calls += 1
            cancelled.set()
            return parser(path)

        with (
            mock.patch.object(
                logreader, "parse_single_mg15", side_effect=cancelling_parser
            ),
            self.assertRaises(CancelledError),
        ):
            self.load(max_workers=1, cancelled=cancelled.is_set)
        assert calls == 1

    def test_invalid_worker_and_cache_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            self.load(max_workers=0)
        with self.assertRaises(ValueError):
            logreader.LogLoader(cache_max_bytes=-1)


if __name__ == "__main__":
    unittest.main()
