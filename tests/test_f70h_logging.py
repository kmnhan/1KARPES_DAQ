import csv
import datetime
import importlib
import logging
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class F70HLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger = logging.getLogger("F70H")
        handlers, level = logger.handlers[:], logger.level
        original_hook = sys.excepthook
        try:
            cls.module = importlib.import_module("f70h.__main__")
        finally:
            sys.excepthook = original_hook
            for handler in logger.handlers[:]:
                if handler not in handlers:
                    logger.removeHandler(handler)
                    handler.close()
            logger.setLevel(level)

    def run_writer(self, timestamp, values, previous_values, *, gap=False):
        messages = queue.Queue()
        messages.put((timestamp, values))
        with tempfile.TemporaryDirectory() as directory:
            process = SimpleNamespace(
                _stopped=Mock(),
                queue=messages,
                log_dir=directory,
                _last_logged=timestamp - datetime.timedelta(seconds=10 if gap else 1),
                _content_old=previous_values,
            )
            process._stopped.is_set.side_effect = (False, True)
            with patch.object(self.module.time, "sleep"):
                self.module.LoggingProc.run(process)
            path = Path(directory) / (timestamp.strftime("%y%m%d") + ".csv")
            if not path.exists():
                return []
            with path.open(newline="") as stream:
                return list(csv.reader(stream))

    def test_pressure_only_changes_are_logged(self):
        timestamp = datetime.datetime(2026, 10, 27, 12, 34, 56)
        rows = self.run_writer(timestamp, (30, 20, 19, 161), (30, 20, 19, 160))
        assert len(rows) == 1
        assert datetime.datetime.fromisoformat(rows[0][0]) == timestamp
        assert rows[0][1:] == ["30", "20", "19", "161"]

    def test_unchanged_measurements_are_skipped(self):
        timestamp = datetime.datetime(2026, 10, 27, 12, 34, 56)
        assert self.run_writer(timestamp, (30, 20, 19, 160), (30, 20, 19, 160)) == []

    def test_gap_rows_preserve_previous_pressure(self):
        timestamp = datetime.datetime(2026, 10, 27, 12, 34, 56)
        rows = self.run_writer(
            timestamp, (30, 20, 19, 161), (30, 20, 19, 160), gap=True
        )
        assert len(rows) == 2
        assert datetime.datetime.fromisoformat(rows[0][0]) == (
            timestamp - datetime.timedelta(seconds=1)
        )
        assert rows[0][1:] == ["30", "20", "19", "160"]
        assert datetime.datetime.fromisoformat(rows[1][0]) == timestamp
        assert rows[1][1:] == ["30", "20", "19", "161"]

    def test_status_queues_temperature_and_pressure(self):
        timestamp = datetime.datetime(2026, 10, 27, 12, 34, 56)
        window = SimpleNamespace(
            log_writer=Mock(),
            statusBar=Mock(),
            alarm_status_labels=[Mock() for _ in self.module.F70H_ALARM_BITS],
            alarms_notified=set(),
            OFF_LABEL="off",
            labels=[Mock() for _ in range(4)],
            stop_if_hot=Mock(),
        )
        with patch.object(self.module, "datetime") as clock:
            clock.datetime.now.return_value = timestamp
            self.module.MainWindow.update_status(window, "0" * 16, (30, 20, 19), 160)

        window.log_writer.append.assert_called_once_with(timestamp, (30, 20, 19, 160))


if __name__ == "__main__":
    unittest.main()
