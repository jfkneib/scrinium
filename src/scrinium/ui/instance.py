"""Instance unique : un second lancement réveille la fenêtre déjà ouverte (souvent cachée dans la zone de notification)."""
import getpass

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

NOM = f"scrinium-{getpass.getuser()}"


def reveiller_existante(theme: str | None = None, nouvelle: bool = False) -> bool:
    """Si une instance tourne déjà, lui demande de s'afficher et retourne True."""
    s = QLocalSocket()
    s.connectToServer(NOM)
    if not s.waitForConnected(300):
        return False
    s.write(f"show\t{theme or ''}\t{int(nouvelle)}".encode("utf-8"))
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


class Serveur(QObject):
    reveil = pyqtSignal(str, bool)   # thème demandé, nouvelle fiche

    def __init__(self, parent=None):
        super().__init__(parent)
        QLocalServer.removeServer(NOM)   # reste d'un plantage éventuel
        self.srv = QLocalServer(self)
        self.srv.listen(NOM)
        self.srv.newConnection.connect(self._connexion)

    def _connexion(self):
        c = self.srv.nextPendingConnection()
        if c is None:
            return
        c.waitForReadyRead(300)
        morceaux = bytes(c.readAll()).decode("utf-8", "replace").split("\t")
        c.disconnectFromServer()
        if morceaux and morceaux[0] == "show":
            self.reveil.emit(morceaux[1] if len(morceaux) > 1 else "", len(morceaux) > 2 and morceaux[2] == "1")
