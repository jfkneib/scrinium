# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Garde-fou : les tests tournent hors écran, même si la session définit une vraie plateforme graphique."""
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402


def test_qt_est_hors_ecran_et_sans_zone_de_notification():
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen" and "DISPLAY" not in os.environ
    app = QApplication.instance() or QApplication([])
    assert QGuiApplication.platformName() == "offscreen"
    assert not QSystemTrayIcon.isSystemTrayAvailable()                  # aucune icône ne peut apparaître dans la vraie zone de notification
