import html
import sys
import traceback

from qtpy import QtCore, QtGui, QtWidgets


def _format_traceback(exc_text: str, palette: QtGui.QPalette) -> str:
    """Format a traceback as highlighted HTML, falling back to escaped plain text."""
    try:
        import pygments
        from pygments.formatters import HtmlFormatter
        from pygments.lexers.python import PythonTracebackLexer

        dark = palette.color(QtGui.QPalette.ColorRole.Base).lightness() < 128
        formatter = HtmlFormatter(
            style="github-dark" if dark else "default", noclasses=True
        )
        return pygments.highlight(exc_text, PythonTracebackLexer(), formatter)
    except (ImportError, ValueError):
        return f"<pre>{html.escape(exc_text)}</pre>"


class MessageDialog(QtWidgets.QDialog):
    """A message dialog with expandable, selectable rich-text details."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        title: str = "",
        text: str = "",
        informative_text: str = "",
        detailed_text: str = "",
        buttons: QtWidgets.QDialogButtonBox.StandardButton | None = None,
        default_button: QtWidgets.QDialogButtonBox.StandardButton | None = None,
        icon_pixmap: QtWidgets.QStyle.StandardPixmap | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        if buttons is None:
            buttons = QtWidgets.QDialogButtonBox.StandardButton.Ok
        if icon_pixmap is None:
            icon_pixmap = QtWidgets.QStyle.StandardPixmap.SP_MessageBoxCritical

        style = self.style()
        icon_size = (
            style.pixelMetric(QtWidgets.QStyle.PixelMetric.PM_MessageBoxIconSize) or 48
        )
        icon_label = QtWidgets.QLabel(self)
        icon_label.setPixmap(
            style.standardIcon(icon_pixmap).pixmap(icon_size, icon_size)
        )
        icon_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignHCenter
        )

        self._text_label = QtWidgets.QLabel(self)
        self._info_label = QtWidgets.QLabel(self)
        for label in (self._text_label, self._info_label):
            label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(
                QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
                | QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            label.setWordWrap(True)
        font = self._text_label.font()
        font.setBold(True)
        self._text_label.setFont(font)
        self._info_label.setMinimumWidth(360)

        self._button_box = QtWidgets.QDialogButtonBox(buttons, parent=self)
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        if default_button is not None:
            default_btn = self._button_box.button(default_button)
            if default_btn is not None:
                default_btn.setDefault(True)
                default_btn.setAutoDefault(True)

        self._details_toggle = QtWidgets.QToolButton(self)
        self._details_toggle.setObjectName("messageDialogDetailsToggle")
        self._details_toggle.setCheckable(True)
        self._details_toggle.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._details_toggle.setAutoRaise(True)
        self._details_toggle.toggled.connect(self._toggle_details)

        self._details = QtWidgets.QTextEdit(self)
        self._details.setObjectName("messageDialogDetails")
        self._details.setReadOnly(True)
        self._details.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.NoWrap)
        self._details.setFont(
            QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        )
        self._details.setMinimumSize(640, 240)

        separator = QtWidgets.QFrame(self)
        separator.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self._details_container = QtWidgets.QWidget(self)
        details_layout = QtWidgets.QVBoxLayout(self._details_container)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addWidget(separator)
        details_layout.addWidget(self._details)

        text_layout = QtWidgets.QVBoxLayout()
        text_layout.addWidget(self._text_label)
        text_layout.addWidget(self._info_label)
        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(icon_label)
        top_row.addLayout(text_layout, 1)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self._button_box)
        layout.addWidget(self._details_toggle)
        layout.addWidget(self._details_container)

        self.setText(text)
        self.setInformativeText(informative_text)
        self.setDetailedText(detailed_text)

    @QtCore.Slot(bool)
    def _toggle_details(self, checked: bool) -> None:
        self._details_container.setVisible(checked and bool(self._detailed_text))
        self._details_toggle.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if checked else QtCore.Qt.ArrowType.RightArrow
        )
        self._details_toggle.setText("Hide Details" if checked else "Show Details…")
        self.adjustSize()

    def setDetailedText(self, text: str) -> None:
        """Set the details as HTML and collapse the details panel."""
        self._detailed_text = text
        self._details.setHtml(text)
        self._details_toggle.setChecked(False)
        self._details_toggle.setVisible(bool(text))
        self.setSizeGripEnabled(bool(text))
        self._toggle_details(False)

    def detailedText(self) -> str:
        return self._detailed_text

    def setInformativeText(self, text: str) -> None:
        self._info_label.setText(text)
        self._info_label.setVisible(bool(text))

    def informativeText(self) -> str:
        return self._info_label.text()

    def setText(self, text: str) -> None:
        self._text_label.setText(text)

    def text(self) -> str:
        return self._text_label.text()

    @staticmethod
    def critical(
        parent: QtWidgets.QWidget | None,
        title: str,
        text: str,
        informative_text: str = "",
        detailed_text: str | None = None,
        buttons: QtWidgets.QDialogButtonBox.StandardButton | None = None,
    ) -> int:
        """Show an error with the active exception's full traceback in its details.

        Pass ``detailed_text`` to supply custom HTML details, or an empty string to
        omit details even while handling an exception.
        """
        dialog = MessageDialog(
            parent=parent,
            title=title,
            text=text,
            informative_text=informative_text,
            buttons=buttons,
        )
        if detailed_text is None:
            exception = sys.exception()
            detailed_text = (
                _format_traceback(
                    "".join(traceback.format_exception(exception)), dialog.palette()
                )
                if exception is not None
                else ""
            )
        dialog.setDetailedText(detailed_text)
        try:
            return dialog.exec()
        finally:
            dialog.deleteLater()
