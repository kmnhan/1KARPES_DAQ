import datetime
import io
import pathlib
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from logviewer.logreader import (
    datetime_to_filename,
    get_log,
    log_index_to_unix_seconds,
    parse_single_cryo,
    parse_single_mg15,
)


class LogTimestampTests(unittest.TestCase):
    def test_plot_times_are_independent_of_datetime_resolution(self):
        for unit, fraction in (
            ("s", 0),
            ("ms", 123000),
            ("us", 123456),
            ("ns", 123456),
        ):
            with self.subTest(unit=unit):
                value = datetime.datetime(2026, 10, 27, 12, 34, 56, fraction)
                index = pd.DatetimeIndex([value]).as_unit(unit)
                # The monitoring PC uses local Korea time (UTC+09:00).
                expected = value.replace(
                    tzinfo=datetime.timezone(datetime.timedelta(hours=9))
                ).timestamp()
                with mock.patch("logviewer.logreader.time.timezone", -9 * 3600):
                    result = log_index_to_unix_seconds(index)
                np.testing.assert_allclose(result, [expected], rtol=0, atol=1e-6)

    def test_pressure_log_with_mixed_timestamp_precision(self):
        source = io.StringIO(
            "2026-10-27T12:34:56,1e-8,2e-8\n"
            "2026-10-27T12:34:57.123456,3e-8,4e-8\n"
            "2026-10-27 12:34:58.654321,5e-8,6e-8\n"
        )
        frame = parse_single_mg15(source)
        assert frame.index.name == "time"
        assert frame.index.to_list() == [
            datetime.datetime(2026, 10, 27, 12, 34, 56),
            datetime.datetime(2026, 10, 27, 12, 34, 57, 123456),
            datetime.datetime(2026, 10, 27, 12, 34, 58, 654321),
        ]
        np.testing.assert_allclose(
            frame.to_numpy(), [[1e-8, 2e-8], [3e-8, 4e-8], [5e-8, 6e-8]]
        )

    def test_legacy_pressure_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "261027.csv"
            path.write_text("261027123456\t1e-8\t2e-8\n", encoding="utf-8")
            frame = parse_single_mg15(path)
        assert frame.index[0] == datetime.datetime(2026, 10, 27, 12, 34, 56)
        np.testing.assert_allclose(frame.iloc[0], [1e-8, 2e-8])

    def test_cryocooler_log_after_header_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "261027.csv"
            path.write_text(
                "Time,Old sensor\n2026-10-27T12:34:55.123456,1\n"
                "Time,Sample,Shield\n"
                "2026-10-27T12:34:56,2,3\n"
                "2026-10-27T12:34:57.123456,4,5\n",
                encoding="utf-8",
            )
            frame = parse_single_cryo(path)
        assert frame.columns.to_list() == ["Sample", "Shield"]
        assert frame.index.to_list() == [
            datetime.datetime(2026, 10, 27, 12, 34, 56),
            datetime.datetime(2026, 10, 27, 12, 34, 57, 123456),
        ]

    def test_legacy_cryocooler_log(self):
        value = datetime.datetime(2026, 10, 27, 12, 34, 56)
        labview_time = value.timestamp() + 2082844800.0
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "261027.csv"
            path.write_text(
                "Running Time (s),LabVIEW time,Date&Time,Sample,Clear\n"
                f"0,{labview_time},2026-10-27,2,0\n",
                encoding="utf-8",
            )
            frame = parse_single_cryo(path)
        assert frame.index[0] == value
        assert frame.columns.to_list() == ["Sample"]
        assert frame.iloc[0, 0] == 2

    def test_date_range_keeps_exact_boundaries_across_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "261026.csv").write_text(
                "2026-10-26T23:59:59.123456,1,2\n", encoding="utf-8"
            )
            (root / "261027.csv").write_text(
                "2026-10-27T00:00:00.123456,3,4\n2026-10-27T00:00:01.123456,5,6\n",
                encoding="utf-8",
            )
            start = datetime.datetime(2026, 10, 26, 23, 59, 59, 123456)
            end = datetime.datetime(2026, 10, 27, 0, 0, 0, 123456)
            frame = get_log(start, end, directory, parse_single_mg15)
        assert frame.index.to_list() == [start, end]
        assert datetime_to_filename(start) == "261026.csv"


if __name__ == "__main__":
    unittest.main()
