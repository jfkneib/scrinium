# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Sécurité » : analyse des sorties de commandes (Linux, Windows, macOS : exemples), nouveau/normal, notifications et vue.
Aucune commande réelle n'est lancée par ces tests, sauf un essai de bon sens sur Linux."""
import base64
import hashlib
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "securite"
_spec = importlib.util.spec_from_file_location("securite_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

WHO = """jfk      :0           2026-11-10 08:00 (:0)
jfk      pts/1        2026-11-10 10:00 (192.0.2.50)
bob      pts/2        2026-11-10 10:05 (tmux(1234).%0)
"""
SS = """tcp   LISTEN 0 128 0.0.0.0:22     0.0.0.0:*   users:(("sshd",pid=900,fd=3))
tcp   LISTEN 0 128 [::]:22        [::]:*      users:(("sshd",pid=900,fd=4))
tcp   LISTEN 0 5   127.0.0.1:631  0.0.0.0:*
udp   UNCONN 0 0   0.0.0.0:5353   0.0.0.0:*   users:(("avahi-daemon",pid=700,fd=12))
udp   UNCONN 0 0   0.0.0.0:40429  0.0.0.0:*   users:(("kdeconnectd",pid=800,fd=9))
"""
PASSWD = """root:x:0:0:root:/root:/bin/bash
daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin
jfk:x:1000:1000:jfk:/home/jfk:/bin/bash
www:x:1001:1001::/var/www:/usr/sbin/nologin
nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin
"""
LAST = """jfk      pts/1        192.0.2.50     Tue Nov 10 10:00   still logged in
jfk      :0           :0               Tue Nov 10 08:00   still logged in
reboot   system boot  0.0.0.0          Tue Nov 10 07:59   still running
"""
CLE = base64.b64encode(b"cle-publique-de-test").decode()
AUTORISEES = f"# commentaire\n\nssh-ed25519 {CLE} support@boite\ncommand=\"ls\" ssh-rsa {CLE} limitee\nssh-rsa pas-du-base64!! x\n"


def test_empreinte_comme_ssh_keygen():
    attendu = "SHA256:" + base64.b64encode(hashlib.sha256(b"cle-publique-de-test").digest()).decode().rstrip("=")
    assert lg.empreinte_cle(CLE) == attendu and lg.empreinte_cle("pas-du-base64!!") == ""
    cles = lg.lire_authorized_keys(AUTORISEES)
    assert cles == [(attendu, "support@boite"), (attendu, "limitee")]                    # une option devant la clé est tolérée


def test_analyseurs_linux():
    assert lg.lire_who(WHO) == [("jfk", ":0", ":0"), ("jfk", "pts/1", "192.0.2.50"), ("bob", "pts/2", "tmux(1234).%0")]
    assert lg.lire_ss(SS)[0] == ("tcp", "0.0.0.0", 22, ["sshd"]) and ("tcp", "127.0.0.1", 631, []) in lg.lire_ss(SS) and len(lg.lire_ss(SS)) == 5
    assert lg.lire_passwd(PASSWD) == ["root", "jfk"]
    assert lg.lire_last(LAST) == [("jfk", "192.0.2.50")]
    assert lg.lire_processus("systemd\nsshd\nsshd\nTeamViewer_Service\nbash\n") == ["sshd", "teamviewer_service"]


def test_analyseurs_windows_et_macos():
    q = (" USERNAME              SESSIONNAME        ID  STATE   IDLE TIME  LOGON TIME\n>jfk                   console             1  Active      none   11/10/2026 8:00 AM\n"
         " admin                 rdp-tcp#0           2  Active          .  11/10/2026 9:00 AM\n jfk2                                      3  Disc            .  11/10/2026 7:00 AM\n")
    assert lg.lire_query_user(q) == [("jfk", "console", ""), ("admin", "rdp-tcp#0", "rdp"), ("jfk2", "", "")]
    net = ("  Proto  Adresse locale         Adresse distante       État           PID\n  TCP    0.0.0.0:135            0.0.0.0:0              ÉCOUTE          1052\n"
           "  TCP    127.0.0.1:5000         0.0.0.0:0              ÉCOUTE          2200\n  TCP    192.0.2.5:50000      52.1.1.1:443           ÉTABLI          3300\n"
           "  TCP    [::]:3389              [::]:0                 ÉCOUTE          1500\n")
    assert lg.lire_netstat_windows(net) == [("tcp", "0.0.0.0", 135, ["1052"]), ("tcp", "127.0.0.1", 5000, ["2200"]), ("tcp", "[::]", 3389, ["1500"])]
    assert lg.lire_tasklist_csv('"svchost.exe","1052","Services","0","10 K"\n"TeamViewer.exe","2200","Console","1","20 K"\n') == {"1052": "svchost.exe", "2200": "TeamViewer.exe"}
    nu = "\\\\PC comptes d'utilisateurs\n\n-------------------------------------------------------------------------------\nAdministrateur           Invité                   jfk\nWDAGUtilityAccount\nLa commande s'est terminée correctement.\n"
    assert lg.lire_net_user(nu) == ["Administrateur", "Invité", "jfk", "WDAGUtilityAccount"]
    lsof = ("COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\nControlCe 500 jfk   8u  IPv4 0x1      0t0  TCP *:7000 (LISTEN)\n"
            "node      600 jfk  20u  IPv6 0x2      0t0  TCP [::1]:3000 (LISTEN)\n")
    assert lg.lire_lsof(lsof) == [("tcp", "*", 7000, ["ControlCe"]), ("tcp", "[::1]", 3000, ["node"])]
    assert lg.lire_dscl("_spotlight 89\nroot 0\njfk 501\ndaemon 1\nguest 201\nbob 502\n") == ["root", "jfk", "bob"]


def faux(sorties, fichiers=None):
    fichiers = fichiers or {}
    return (lambda argv: sorties.get(argv[0], "")), (lambda chemin: fichiers.get(chemin))


def test_scanner_linux_constats_et_statuts():
    exe, lire = faux({"who": WHO, "ss": SS, "last": LAST, "ps": "sshd\nteamviewerd\n", "crontab": "# m\n0 3 * * * /home/jfk/sauvegarde.sh\n"},
                     {"/etc/passwd": PASSWD, "/home/jfk/.ssh/authorized_keys": AUTORISEES})
    cs = lg.scanner("linux", exe, lire, "jfk", "/home/jfk")
    cles = {c.cle for c in cs}
    assert {"session|jfk|local", "session|jfk|192.0.2.50", "ecoute|tcp|22", "ecoute|tcp|631", "ecoute|udp|5353", "connexion|jfk|192.0.2.50",
            "compte|root", "compte|jfk", "acces|sshd", "acces|teamviewerd"} <= cles
    assert "ecoute|udp|40429" not in cles                                               # port UDP éphémère : ignoré
    assert sum(1 for c in cs if c.categorie == "cle") == 1 and sum(1 for c in cs if c.categorie == "planifie") == 1     # deux clés identiques : une seule
    assert len(cles) == len(cs)                                                          # pas de doublon
    par = {c.cle: c for c in cs}
    assert par["ecoute|tcp|22"].expose and not par["ecoute|tcp|631"].expose and par["session|jfk|local"].auto_connu
    assert par["session|bob|local"].auto_connu is False                                  # une autre personne, en local : à connaître
    assert lg.statut(par["session|jfk|local"], set()) == "connu"                         # évident : jamais « nouveau »
    assert lg.statut(par["ecoute|tcp|22"], set()) == "a_verifier" and lg.statut(par["ecoute|tcp|631"], set()) == "nouveau"
    assert lg.statut(par["ecoute|tcp|22"], {"ecoute|tcp|22"}) == "connu"


def test_scanner_windows_et_macos_avec_exemples():
    exe, lire = faux({"query": " USERNAME SESSIONNAME ID STATE\n>jfk console 1 Active\n admin rdp-tcp#0 2 Active\n",
                      "tasklist": '"svchost.exe","1052","S","0","1 K"\n"AnyDesk.exe","2200","S","0","1 K"\n',
                      "netstat": "  TCP    0.0.0.0:135   0.0.0.0:0   ÉCOUTE   1052\n  TCP    0.0.0.0:7070   0.0.0.0:0   ÉCOUTE   2200\n",
                      "net": "---\nAdministrateur  jfk\nLa commande s'est terminée correctement.\n",
                      "reg": "    fDenyTSConnections    REG_DWORD    0x0\n"})
    w = {c.cle: c for c in lg.scanner("windows", exe, lire, "JFK", "C:/Users/jfk")}
    assert w["session|admin|rdp"].expose and w["session|jfk|local"].auto_connu and w["ecoute|tcp|7070"].libelle == "TCP 7070 (AnyDesk.exe)"
    assert "acces|anydesk.exe" in w and "acces|bureau-a-distance" in w and "compte|jfk" in w
    exe, lire = faux({"who": "jfk console 2026-11-10 08:00\n", "lsof": "COMMAND PID USER FD TYPE DEVICE SIZE NODE NAME\nControlCe 5 jfk 8u IPv4 0x1 0t0 TCP *:7000 (LISTEN)\n",
                      "dscl": "root 0\njfk 501\n", "ps": "screensharingd\nFinder\n"})
    m = {c.cle: c for c in lg.scanner("macos", exe, lire, "jfk", "/Users/jfk")}
    assert m["ecoute|tcp|7000"].expose and "acces|screensharingd" in m and "compte|jfk" in m
    assert lg.scanner("plan9", exe, lire, "x", "/") == []


def test_fiche_texte_et_nouveautes():
    t = lg.ecrire({"pc1": {"ecoute|tcp|22", "compte|jfk"}, "pc2": set()})
    assert t.startswith("#scrinium-securite\n\n## pc1\nok: compte|jfk\nok: ecoute|tcp|22\n") and lg.lire(t) == {"pc1": {"ecoute|tcp|22", "compte|jfk"}, "pc2": set()}
    assert lg.lire("") == {} and lg.lire("texte libre") == {} and lg.lire("## pc\nok: sans-separateur\nok: a|b") == {"pc": {"a|b"}}
    cs = [lg.Constat("ecoute", "ecoute|tcp|22", "TCP 22", "", True), lg.Constat("ecoute", "ecoute|tcp|8080", "TCP 8080", "", False),
          lg.Constat("compte", "compte|zed", "Compte zed")]
    assert lg.nouveautes(cs, None) == []                                                 # pas de référence : on ne signale rien
    assert [c.cle for c in lg.nouveautes(cs, {"ecoute|tcp|22"})] == ["compte|zed"]       # le port local 8080 n'est pas signalé
    assert [c.cle for c in lg.nouveautes(cs, set())] == ["ecoute|tcp|22", "compte|zed"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="essai réel sur Linux seulement")
def test_essai_reel_sur_cette_machine():
    cs = lg.analyser_machine()
    assert isinstance(cs, list) and all(isinstance(c, lg.Constat) for c in cs) and len({c.cle for c in cs}) == len(cs)
    assert lg.executer(["commande-qui-n-existe-pas"]) == "" and lg.lire_fichier("/fichier/inexistant") is None


# ---------- dans la vraie fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "securite")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("securite"), w.plugins.infos["securite"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


CONSTATS = [lg.Constat("ecoute", "ecoute|tcp|22", "TCP 22 (sshd)", "Accessible depuis le réseau", True),
            lg.Constat("compte", "compte|jfk", "Compte jfk"), lg.Constat("session", "session|jfk|local", "Session de jfk", "", False, True)]


def test_vue_reference_nouveau_et_menu(fen, monkeypatch):
    vue = fen.vues_types["securite"]
    textes = []
    vue.modifie.connect(textes.append)
    monkeypatch.setattr(lg, "nom_machine", lambda: "pc1")
    monkeypatch.setattr(sys.modules["scrinium_plugin_securite"].logique, "nom_machine", lambda: "pc1")
    vue.charger(lg.texte_neuf())
    vue._arrive(CONSTATS)
    assert "Aucune référence" in vue.l_resume.text() and vue.table.rowCount() == 3
    assert [vue.table.item(i, 0).text() for i in range(3)] == ["À vérifier", "Nouveau", "Normal"]                 # les plus inquiétants d'abord
    vue._tout_accepter()
    assert "## pc1" in textes[-1] and "ok: ecoute|tcp|22" in textes[-1] and "session|jfk|local" not in textes[-1]
    assert "rien de nouveau" in vue.l_resume.text() and all(vue.table.item(i, 0).text() == "Normal" for i in range(3))
    vue._arrive(CONSTATS + [lg.Constat("acces", "acces|anydesk", "Accès à distance : anydesk", "", True)])
    assert "1 nouveau(x)" in vue.l_resume.text() and vue.table.item(0, 0).text() == "À vérifier"
    vue._accepter("acces|anydesk", True)
    assert "ok: acces|anydesk" in textes[-1] and "rien de nouveau" in vue.l_resume.text()
    vue._accepter("acces|anydesk", False)
    assert "anydesk" not in textes[-1]


def test_fiche_non_validee_ne_lit_rien(fen, monkeypatch):
    vue = fen.vues_types["securite"]
    lances = []
    monkeypatch.setattr(sys.modules["scrinium_plugin_securite"].logique, "analyser_machine", lambda: lances.append(1) or [])
    vue.actif = False
    vue.analyser()
    assert lances == [] and "non validée" in vue.l_resume.text() and not vue.b_accepter.isEnabled()


def test_signalement_une_seule_fois_et_seulement_avec_reference(fen, monkeypatch):
    p = fen.plugins.actifs["securite"][0]
    mod = sys.modules["scrinium_plugin_securite"].logique
    monkeypatch.setattr(mod, "nom_machine", lambda: "pc1")
    notes = []
    monkeypatch.setattr(p.ctx.ui, "notifier", lambda t, m: notes.append(m))
    p.ctx.creer_fiche("Sécurité", "Ma machine", lg.texte_neuf())
    th = fen.store.theme("Sécurité")
    assert p.reference() is None                                                          # fiche inerte, ou sans section pour cette machine
    fen.store.enregistrer(th, th.fiches[0], "Ma machine", lg.ecrire({"pc1": {"ecoute|tcp|22"}}))
    assert p.reference() is None                                                          # texte modifié : la validation tombe
    fen.store.valider_fiche(th, th.fiches[0])
    assert p.reference() == {"ecoute|tcp|22"}
    assert p.signaler(CONSTATS) != [] and len(notes) == 1 and "Compte jfk" in notes[0] and "TCP 22" not in notes[0]
    assert p.signaler(CONSTATS) == [] and len(notes) == 1                                  # déjà signalé : rien de plus
    p.regler_fond(True)
    assert p.ctx.reglages.get("fond") is True
