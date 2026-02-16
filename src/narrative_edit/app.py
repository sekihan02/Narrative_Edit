from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Narrative_Edit")
    app.setOrganizationName("Narrative_Edit")

    win = MainWindow()
    win.show()
    return app.exec()
