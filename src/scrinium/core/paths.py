"""Emplacements des données selon le système (aucune dépendance externe)."""
import os
import sys
from pathlib import Path

APP = "scrinium"


def base_dir() -> Path:
    """Dossier de l'application (variable SCRINIUM_HOME pour le forcer)."""
    env = os.environ.get("SCRINIUM_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP


class Paths:
    def __init__(self, base: Path | None = None):
        self.base = base or base_dir()
        self.fiches = self.base / "fiches"
        self.corbeille = self.base / "corbeille"
        self.recovery_pub = self.base / "recovery.pub"
        self.settings = self.base / "settings.json"
        self.hooks = self.base / "hooks"
