import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qt_extensions.dialogs import MessageDialog, _format_traceback
from qtpy import QtCore, QtGui, QtWidgets


def _raise_value_error(message: str) -> None:
    raise ValueError(message)


class MessageDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.dialogs = []

        def fake_exec(dialog):
            self.dialogs.append(dialog)
            return QtWidgets.QDialog.DialogCode.Accepted

        self.exec_patch = patch.object(MessageDialog, "exec", fake_exec)
        self.exec_patch.start()
        self.addCleanup(self.exec_patch.stop)

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        self.app.processEvents()

    def test_critical_includes_full_chained_traceback_and_html_characters(self):
        try:
            try:
                _raise_value_error("Invalid <timestamp> & data")
            except ValueError as cause:
                raise RuntimeError("Could not load <file.csv>") from cause
        except RuntimeError:
            result = MessageDialog.critical(
                None, "Load failed", "The log could not be loaded.", "Check the file."
            )
        dialog = self.dialogs[-1]
        details = dialog._details.toPlainText()
        assert result == QtWidgets.QDialog.DialogCode.Accepted
        assert dialog.windowTitle() == "Load failed"
        assert dialog.text() == "The log could not be loaded."
        assert dialog.informativeText() == "Check the file."
        assert "Traceback (most recent call last):" in details
        assert "test_critical_includes_full_chained_traceback" in details
        assert "ValueError: Invalid <timestamp> & data" in details
        assert "The above exception was the direct cause" in details
        assert "RuntimeError: Could not load <file.csv>" in details
        assert "&lt;timestamp&gt;" in dialog.detailedText()
        assert dialog._details.isReadOnly()
        dialog._details.selectAll()
        assert "RuntimeError: Could not load <file.csv>" in (
            dialog._details.textCursor().selectedText()
        )

    def test_details_toggle_and_replacement(self):
        dialog = MessageDialog(detailed_text="<pre>First details</pre>")
        self.dialogs.append(dialog)
        assert dialog._details_container.isHidden()
        assert not dialog._details_toggle.isChecked()
        assert dialog.isSizeGripEnabled()
        dialog._details_toggle.click()
        assert not dialog._details_container.isHidden()
        assert dialog._details_toggle.text() == "Hide Details"
        assert dialog._details_toggle.arrowType() == QtCore.Qt.ArrowType.DownArrow
        dialog.resize(900, 600)
        assert dialog.width() == 900
        assert dialog.height() == 600
        dialog._details_toggle.click()
        assert dialog._details_container.isHidden()
        assert dialog._details_toggle.text() == "Show Details…"
        dialog.setDetailedText("<pre>Replacement details</pre>")
        assert dialog._details.toPlainText() == "Replacement details"
        assert dialog._details_container.isHidden()
        assert not dialog._details_toggle.isChecked()
        dialog.setDetailedText("")
        assert dialog._details_toggle.isHidden()
        assert not dialog.isSizeGripEnabled()

    def test_explicit_details_override_active_exception(self):
        try:
            _raise_value_error("Should not appear in details")
        except ValueError:
            MessageDialog.critical(
                None,
                "Custom details",
                "Main <text>",
                detailed_text="<pre>Custom &lt;details&gt; &amp; data</pre>",
            )
        dialog = self.dialogs[-1]
        assert dialog._details.toPlainText() == "Custom <details> & data"
        assert dialog._text_label.textFormat() == QtCore.Qt.TextFormat.PlainText
        assert dialog.text() == "Main <text>"

    def test_no_exception_and_explicit_empty_details(self):
        MessageDialog.critical(None, "No exception", "Nothing to include")
        dialog = self.dialogs[-1]
        assert dialog.detailedText() == ""
        assert dialog._details_toggle.isHidden()
        try:
            _raise_value_error("Should not appear in details")
        except ValueError:
            MessageDialog.critical(None, "No details", "Failure", detailed_text="")
        assert self.dialogs[-1].detailedText() == ""

    def test_critical_releases_dialog_owned_by_parent(self):
        parent = QtWidgets.QWidget()
        try:
            MessageDialog.critical(parent, "Load failed", "Could not load log")
            dialog = self.dialogs.pop()
            assert dialog in parent.findChildren(MessageDialog)
            assert dialog.text() == "Could not load log"
            QtCore.QCoreApplication.sendPostedEvents(
                None, QtCore.QEvent.Type.DeferredDelete
            )
            assert parent.findChildren(MessageDialog) == []
        finally:
            parent.deleteLater()
            QtCore.QCoreApplication.sendPostedEvents(
                None, QtCore.QEvent.Type.DeferredDelete
            )

    def test_missing_pygments_uses_escaped_plain_traceback(self):
        with patch.dict(sys.modules, {"pygments": None}):
            try:
                _raise_value_error("Invalid <timestamp> & data")
            except ValueError:
                MessageDialog.critical(None, "Load failed", "Could not load log")
        dialog = self.dialogs[-1]
        assert dialog.detailedText().startswith("<pre>")
        assert "&lt;timestamp&gt; &amp; data" in dialog.detailedText()
        assert "ValueError: Invalid <timestamp> & data" in dialog._details.toPlainText()

    def test_traceback_formatting_uses_palette_for_dark_and_light_styles(self):
        try:
            from pygments.formatters import HtmlFormatter
        except ImportError:
            self.skipTest("Pygments is not installed")
        for color, expected_style in (
            ("#ffffff", "default"),
            ("#101010", "github-dark"),
        ):
            with self.subTest(color=color):
                palette = QtGui.QPalette(self.app.palette())
                palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(color))
                with patch(
                    "pygments.formatters.HtmlFormatter", wraps=HtmlFormatter
                ) as fmt:
                    result = _format_traceback("ValueError: <timestamp>\n", palette)
                assert fmt.call_args.kwargs["style"] == expected_style
                assert "&lt;timestamp&gt;" in result


if __name__ == "__main__":
    unittest.main()
