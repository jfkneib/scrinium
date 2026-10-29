# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Instance unique : un second lancement réveille la fenêtre déjà ouverte (souvent cachée dans la zone de notification).

Canal : socket locale réservée à l'utilisateur. Messages :
  `show\t<thème>\t<0|1>`          afficher la fenêtre (sans réponse) ;
  `lien\t<url>`                    ouvrir un lien `scrinium://…` (sans réponse) ;
  `capture`                        ouvrir la fenêtre de capture rapide (sans réponse) ;
  `add <n>\n` + n octets de JSON   ajouter du texte à une fiche (réponse `ok` ou `err\t<message>`).
Une instance dont le dossier de données est différent (SCRINIUM_HOME) a son propre canal.
"""
import getpass
import hashlib
import json
import os

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

MAX_MESSAGE = 2 * 1024 * 1024
DELAI_CONNEXION_MS = 15000        # une connexion jamais terminée est fermée au bout de ce délai


def nom() -> str:
    """Nom du canal : SCRINIUM_INSTANCE s'il est défini, sinon propre à l'utilisateur et au dossier de données."""
    if os.environ.get("SCRINIUM_INSTANCE"):
        return os.environ["SCRINIUM_INSTANCE"]
    base = f"scrinium-{getpass.getuser()}"
    home = os.environ.get("SCRINIUM_HOME")
    return base + (f"-{hashlib.sha1(home.encode()).hexdigest()[:8]}" if home else "")


def reveiller_existante(theme: str | None = None, nouvelle: bool = False) -> bool:
    """Si une instance tourne déjà, lui demande de s'afficher et retourne True."""
    s = QLocalSocket()
    s.connectToServer(nom())
    if not s.waitForConnected(300):
        return False
    s.write(f"show\t{theme or ''}\t{int(nouvelle)}".encode("utf-8"))
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


def envoyer_lien(url: str) -> bool:
    """Si une instance tourne, lui passe un lien `scrinium://…` et retourne True."""
    s = QLocalSocket()
    s.connectToServer(nom())
    if not s.waitForConnected(300):
        return False
    s.write(f"lien\t{url}".encode("utf-8"))
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


def demander_capture() -> bool:
    """Si une instance tourne, lui demande d'ouvrir la capture rapide et retourne True."""
    s = QLocalSocket()
    s.connectToServer(nom())
    if not s.waitForConnected(300):
        return False
    s.write(b"capture")
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


def envoyer_ajout(payload: dict, delai_ms: int = 8000):
    """Demande à l'instance en cours d'ajouter du texte à une fiche. None s'il n'y a pas d'instance ; sinon (ok, message)."""
    s = QLocalSocket()
    s.connectToServer(nom())
    if not s.waitForConnected(300):
        return None
    donnees = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    s.write(f"add {len(donnees)}\n".encode("ascii") + donnees)
    s.waitForBytesWritten(delai_ms)
    if not s.waitForReadyRead(delai_ms):
        return False, "Scrinium n'a pas répondu"
    rep = bytes(s.readAll()).decode("utf-8", "replace")
    s.disconnectFromServer()
    return (True, "") if rep == "ok" else (False, rep.partition("\t")[2] or rep)


class Serveur(QObject):
    reveil = pyqtSignal(str, bool)   # thème demandé, nouvelle fiche
    capture = pyqtSignal()           # ouvrir la capture rapide
    lien = pyqtSignal(str)           # lien scrinium:// à ouvrir

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ajout = None            # fonction(dict) -> str : message d'erreur, ou "" si l'ajout a réussi
        n = nom()
        QLocalServer.removeServer(n)   # reste d'un plantage éventuel
        self.srv = QLocalServer(self)
        self.srv.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)   # jamais accessible aux autres utilisateurs
        self.srv.listen(n)
        self.srv.newConnection.connect(self._connexion)

    def _connexion(self):
        c = self.srv.nextPendingConnection()
        if c is None:
            return
        tampon = bytearray()

        def lire():
            tampon.extend(bytes(c.readAll()))
            self._traiter(c, tampon)

        c.readyRead.connect(lire)
        c.disconnected.connect(c.deleteLater)
        # Connexion jamais terminée : on la ferme au bout du délai. Le minuteur est un ENFANT du socket : il disparaît avec lui.
        # (Avec QTimer.singleShot(délai, c.disconnectFromServer), le socket, supprimé entre-temps par deleteLater(), était
        # appelé après coup : « wrapped C/C++ object has been deleted », et avec PyQt6 récent le programme entier s'arrêtait.)
        minuteur = QTimer(c)
        minuteur.setSingleShot(True)
        minuteur.timeout.connect(c.disconnectFromServer)
        minuteur.start(DELAI_CONNEXION_MS)
        if c.bytesAvailable():
            lire()

    def _repondre(self, c, texte: str):
        c.write(texte.encode("utf-8"))
        c.flush()
        c.disconnectFromServer()

    def _traiter(self, c, tampon: bytearray):
        if tampon.startswith(b"capture"):
            c.disconnectFromServer()
            self.capture.emit()
        elif tampon.startswith(b"lien\t"):
            url = bytes(tampon[5:]).decode("utf-8", "replace").strip()
            c.disconnectFromServer()
            self.lien.emit(url)
        elif tampon.startswith(b"show"):
            morceaux = bytes(tampon).decode("utf-8", "replace").split("\t")
            c.disconnectFromServer()
            self.reveil.emit(morceaux[1] if len(morceaux) > 1 else "", len(morceaux) > 2 and morceaux[2] == "1")
        elif tampon.startswith(b"add "):
            fin = tampon.find(b"\n")
            if fin < 0:
                return
            try:
                n = int(bytes(tampon[4:fin]))
            except ValueError:
                return self._repondre(c, "err\tmessage invalide")
            if n > MAX_MESSAGE:
                return self._repondre(c, "err\ttexte trop volumineux")
            if len(tampon) < fin + 1 + n:
                return                                          # la suite n'est pas encore arrivée
            try:
                payload = json.loads(bytes(tampon[fin + 1:fin + 1 + n]).decode("utf-8"))
                erreur = self.ajout(payload) if self.ajout else "ajout non pris en charge"
            except Exception as ex:                              # jamais de plantage de la fenêtre à cause d'un client
                erreur = f"{type(ex).__name__}: {ex}"
            self._repondre(c, "ok" if not erreur else f"err\t{erreur}")
