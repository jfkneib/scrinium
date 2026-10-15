"""Lancement automatique à l'ouverture de session (Linux : XDG autostart ; Windows : clé Run ; macOS : LaunchAgent)."""
import os
import shutil
import sys
from pathlib import Path

NOM = "scrinium"


def commande() -> list[str]:
    """Commande lancée à l'ouverture de session : démarre caché dans la zone de notification."""
    exe = shutil.which(NOM)
    base = [exe] if exe else [sys.executable, "-m", "scrinium.cli"]
    return base + ["--minimise"]


def _linux_fichier() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / f"{NOM}.desktop"


def _mac_fichier() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "org.scrinium.plist"


def _echapper_desktop(arg: str) -> str:
    if any(c in arg for c in ' \t"\'\\<>~|&;$*?#()`'):
        return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'
    return arg


def actif() -> bool:
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, NOM)
                return True
        except OSError:
            return False
    return (_mac_fichier() if sys.platform == "darwin" else _linux_fichier()).exists()


def activer(on: bool) -> None:
    cmd = commande()
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, NOM, 0, winreg.REG_SZ, " ".join(f'"{c}"' for c in cmd))
            else:
                try:
                    winreg.DeleteValue(k, NOM)
                except OSError:
                    pass
        return
    if sys.platform == "darwin":
        f = _mac_fichier()
        if not on:
            f.unlink(missing_ok=True)
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        args = "".join(f"<string>{c}</string>" for c in cmd)
        f.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
                     f"<key>Label</key><string>org.scrinium</string><key>ProgramArguments</key><array>{args}</array>"
                     "<key>RunAtLoad</key><true/></dict></plist>\n", encoding="utf-8")
        return
    f = _linux_fichier()
    if not on:
        f.unlink(missing_ok=True)
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("[Desktop Entry]\nType=Application\nName=Scrinium\n"
                 "Comment=Fiches rangées par thème, verrouillables par mot de passe\n"
                 f"Exec={' '.join(_echapper_desktop(c) for c in cmd)}\nIcon=scrinium\nTerminal=false\n"
                 "X-GNOME-Autostart-enabled=true\n", encoding="utf-8")
