"""Single place that picks the Qt binding.

Designer 14.0 (2024) and later ship PySide6; 13.1 and earlier ship PySide2, where QAction
lives in QtWidgets instead of QtGui. Every other module imports Qt from here.
"""

try:
    from PySide6 import QtCore, QtGui, QtWidgets

    QAction = QtGui.QAction
    QT_BINDING = "PySide6"
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

    QAction = QtWidgets.QAction
    QT_BINDING = "PySide2"

__all__ = ["QAction", "QT_BINDING", "QtCore", "QtGui", "QtWidgets"]
