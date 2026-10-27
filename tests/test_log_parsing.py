import datetime
import io
import os
import pathlib
import tempfile
import time
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from logviewer import _parsing


class LogParsingTests(unittest.TestCase):
    def test_modern_pressure_uses_batch_timestamp_parsing(self):
        source = io.StringIO(
            "2026-10-27T12:34:56,1e-8,nan\n"
            "2026-10-27 12:34:57.1,nan,2e-8\n"
            "2026-10-27T12:34:58.123456,3e-8,4e-8\n"
        )
        with mock.patch.object(
            _parsing, "parse_mg15_time", side_effect=AssertionError("Scalar conversion")
        ):
            frame = _parsing.parse_single_mg15(source)
        assert frame.index.name == "time"
        assert frame.index.to_list() == [
            datetime.datetime(2026, 10, 27, 12, 34, 56),
            datetime.datetime(2026, 10, 27, 12, 34, 57, 100000),
            datetime.datetime(2026, 10, 27, 12, 34, 58, 123456),
        ]
        np.testing.assert_allclose(
            frame.to_numpy(), [[1e-8, np.nan], [np.nan, 2e-8], [3e-8, 4e-8]]
        )

    def test_legacy_pressure_rewinds_file_like_input(self):
        source = io.StringIO("unused prefix\n261027123456\t1e-8\t2e-8\n")
        source.seek(len("unused prefix\n"))
        frame = _parsing.parse_single_mg15(source)
        assert frame.index.to_list() == [datetime.datetime(2026, 10, 27, 12, 34, 56)]
        np.testing.assert_allclose(frame.to_numpy(), [[1e-8, 2e-8]])

    def test_modern_cryo_reads_once_and_retains_last_header(self):
        source = io.StringIO(
            "Time,Old sensor\n2026-10-27T12:34:55,99\n"
            "Time,Sample,Shield\n"
            "2026-10-27T12:34:56,2,nan\n"
            "2026-10-27 12:34:57.123456,3,4\n"
        )
        with (
            mock.patch("builtins.open", return_value=source) as open_file,
            mock.patch.object(
                source, "readlines", wraps=source.readlines
            ) as read_lines,
            mock.patch.object(
                _parsing,
                "parse_cryo_time",
                side_effect=AssertionError("Scalar conversion"),
            ),
        ):
            frame = _parsing.parse_single_cryo("log.csv")
        assert open_file.call_count == 1
        assert read_lines.call_count == 1
        assert frame.index.name == "time"
        assert frame.columns.to_list() == ["Sample", "Shield"]
        assert frame.index.to_list() == [
            datetime.datetime(2026, 10, 27, 12, 34, 56),
            datetime.datetime(2026, 10, 27, 12, 34, 57, 123456),
        ]
        np.testing.assert_allclose(frame.to_numpy(), [[2, np.nan], [3, 4]])

    def test_legacy_cryo_preserves_numeric_time_and_excluded_columns(self):
        values = [3896858096.0, 3896858097.125]
        source = io.StringIO(
            "Running Time (s),LabVIEW time,Date&Time,Sample,Clear\n"
            f"0,{values[0]},ignored,2,0\n1,{values[1]},ignored,nan,0\n"
        )
        frame = _parsing.parse_single_cryo(source)
        expected = [
            datetime.datetime.fromtimestamp(value - 2082844800.0) for value in values
        ]
        assert frame.index.to_list() == expected
        assert frame.columns.to_list() == ["Sample"]
        np.testing.assert_allclose(frame.Sample.to_numpy(), [2, np.nan])

    @unittest.skipUnless(hasattr(time, "tzset"), "The platform has no time.tzset")
    def test_legacy_cryo_keeps_system_local_time_including_dst(self):
        previous = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "EST5EDT,M3.2.0,M11.1.0"
            time.tzset()
            winter = datetime.datetime(2026, 1, 15, 12, 0)
            summer = datetime.datetime(2026, 7, 15, 12, 0)
            source = io.StringIO(
                "Running Time (s),LabVIEW time,Date&Time,Sample,Clear\n"
                f"0,{winter.timestamp() + 2082844800.0},ignored,2,0\n"
                f"1,{summer.timestamp() + 2082844800.0},ignored,3,0\n"
            )
            frame = _parsing.parse_single_cryo(source)
            assert frame.index.to_list() == [winter, summer]
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

    def test_modern_cryo_header_still_accepts_legacy_numeric_times(self):
        value = 3896858096.125
        source = io.StringIO(f"Time,Sample\n{value},2\n")
        frame = _parsing.parse_single_cryo(source)
        assert frame.index.to_list() == [
            datetime.datetime.fromtimestamp(value - 2082844800.0)
        ]

    def test_invalid_or_missing_timestamps_are_rejected(self):
        for value in ("not a time", "", "NaT", "2026-13-27T12:34:56"):
            for parser, text in (
                (_parsing.parse_single_mg15, f"{value},1,2\n"),
                (_parsing.parse_single_cryo, f"Time,Sample\n{value},1\n"),
            ):
                with (
                    self.subTest(parser=parser.__name__, value=value),
                    self.assertRaises(ValueError),  # noqa: PT027 - unittest suite
                ):
                    parser(io.StringIO(text))

    def test_scalar_parsers_keep_their_existing_semantics(self):
        value = datetime.datetime(2026, 10, 27, 12, 34, 56, 123456)
        assert _parsing.parse_mg15_time("2026-10-27 12:34:56.123456") == value
        assert _parsing.parse_mg15_time_old(261027123456.75) == value.replace(
            microsecond=0
        )
        assert _parsing.parse_cryo_time(value.isoformat()) == value
        labview_time = value.timestamp() + 2082844800.0
        assert _parsing.parse_cryo_time(
            labview_time
        ) == datetime.datetime.fromtimestamp(labview_time - 2082844800.0)

    def test_pressure_path_and_header_only_cryo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            path = root / "pressure.csv"
            path.write_text("2026-10-27T12:34:56.000000,1,2\n", encoding="utf-8")
            assert len(_parsing.parse_single_mg15(path)) == 1
        frame = _parsing.parse_single_cryo(io.StringIO("Time,Sample,Shield\n"))
        assert frame.empty
        assert frame.index.name == "time"
        assert frame.columns.to_list() == ["Sample", "Shield"]


if __name__ == "__main__":
    unittest.main()
