from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


def _format(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    value = QTextCharFormat()
    value.setForeground(QColor(color))
    if bold:
        value.setFontWeight(QFont.Weight.DemiBold)
    value.setFontItalic(italic)
    return value


class GCodeSyntaxHighlighter(QSyntaxHighlighter):
    """Incremental, per-block CNC highlighting handled by Qt's text engine."""

    def __init__(self, document) -> None:
        super().__init__(document)
        insensitive = QRegularExpression.PatternOption.CaseInsensitiveOption
        self._rules = [
            (QRegularExpression(r"\bN\d+\b", insensitive), _format("#71A7FF")),
            (QRegularExpression(r"\bG\d+(?:\.\d+)?\b", insensitive), _format("#45D7F0", bold=True)),
            (QRegularExpression(r"\bM\d+(?:\.\d+)?\b", insensitive), _format("#FF78B7", bold=True)),
            (QRegularExpression(r"\b[XYZABCUVWIJKR][+-]?(?:\d+(?:\.\d*)?|\.\d+)\b", insensitive), _format("#63DBA5")),
            (QRegularExpression(r"\b[FSTHD][+-]?(?:\d+(?:\.\d*)?|\.\d+)\b", insensitive), _format("#F2C66D")),
            (QRegularExpression(r"%"), _format("#C995FF", bold=True)),
        ]
        # Comments run last so their muted color overrides any code inside them.
        self._comments = [
            (QRegularExpression(r"\([^)]*\)"), _format("#70859E", italic=True)),
            (QRegularExpression(r";.*$"), _format("#70859E", italic=True)),
        ]

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        for expression, style in (*self._rules, *self._comments):
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), style)
