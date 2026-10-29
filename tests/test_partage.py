# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Partage, partie sans interface : liens d'invitation, certificat épinglé, et le vrai serveur PHP (`serveur/`) de bout en
bout avec le transport HTTP (ces tests-là sont ignorés si PHP avec pdo_sqlite est absent)."""
import hashlib
import http.server
import importlib.util
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from scrinium.core import synchro
from scrinium.core.conflits import ContenuDistant
from scrinium.core.paths import Paths
from scrinium.core.store import Store
from scrinium.core.synchroniser import partager, publier, synchroniser
from scrinium.core.transport import ConflitDeVersion, Introuvable, NonAuthentifie, Refuse

RACINE = Path(__file__).resolve().parent.parent


def _charger(nom):
    spec = importlib.util.spec_from_file_location(f"partage_{nom}", RACINE / "plugins" / "partage" / f"{nom}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


lg = _charger("logique")
ht = _charger("http")
JETON = "ab" * 32


# ---------- liens d'invitation ----------
def test_analyser_invitation():
    assert lg.analyser_invitation(f"https://s.exemple.org:8443/inviter/{JETON}") == ("https://s.exemple.org:8443", JETON)
    assert lg.analyser_invitation(f"  https://s.exemple.org/sous/dossier/inviter/{JETON}/ \n") == ("https://s.exemple.org/sous/dossier", JETON)
    lien = lg.lien_application("https://s.exemple.org:8443", JETON)
    assert lien.startswith("scrinium://rejoindre?serveur=https%3A%2F%2Fs.exemple.org%3A8443&jeton=")
    assert lg.analyser_invitation(lien) == ("https://s.exemple.org:8443", JETON)
    for mauvais in ("", "bonjour", f"https://s.org/autre/{JETON}", "https://s.org/inviter/court", f"ftp://s.org/inviter/{JETON}",
                    "scrinium://rejoindre?serveur=&jeton=" + JETON, "scrinium://rejoindre?serveur=https://s.org&jeton=zz"):
        with pytest.raises(ValueError):
            lg.analyser_invitation(mauvais)


def test_nom_depot_et_texte():
    assert lg.nom_depot("https://exemple.org:8443") == "exemple.org-8443"
    assert lg.nom_depot("https://a.fr", ["a.fr", "a.fr-2"]) == "a.fr-3"
    objet, msg = lg.texte_invitation("Courses", "ecriture", "https://s/inviter/x", "31/10/2026 10:00")
    assert "Courses" in msg and "https://s/inviter/x" in msg and "31/10/2026" in msg and objet


# ---------- certificat épinglé ----------
@pytest.fixture
def serveur_tls(tmp_path):
    if not shutil.which("openssl"):
        pytest.skip("openssl absent")
    cle, crt = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(cle), "-out", str(crt),
                    "-subj", "/CN=autre-nom", "-days", "2"], check=True, capture_output=True)

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            corps = b'{"api": 1, "serveur": "test"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def log_message(self, *a):
            pass

    class Serveur(http.server.HTTPServer):
        def handle_error(self, request, client_address):       # poignées de main TLS refusées par le client : normal ici
            pass

    srv = Serveur(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, cle)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    der = ssl.PEM_cert_to_DER_cert(crt.read_text())
    yield f"https://127.0.0.1:{srv.server_address[1]}", hashlib.sha256(der).hexdigest()
    srv.shutdown()


def test_certificat_epingle(serveur_tls):
    url, empreinte = serveur_tls
    with pytest.raises(ht.CertificatInconnu):                                   # auto-signé, rien d'épinglé : refusé
        ht.TransportHttp(url, "jfk").decouverte()
    assert ht.empreinte_serveur(url) == empreinte
    assert ht.TransportHttp(url, "jfk", empreinte=ht.formater_empreinte(empreinte).upper()).decouverte()["api"] == 1
    with pytest.raises(ht.CertificatInconnu):                                   # un autre certificat : refusé
        ht.TransportHttp(url, "jfk", empreinte="00" * 32).decouverte()


def test_serveur_injoignable():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    from scrinium.core.transport import Injoignable
    with pytest.raises(Injoignable):
        ht.TransportHttp(f"http://127.0.0.1:{port}", "jfk", delai=2).decouverte()


# ---------- le vrai serveur PHP ----------
def _php_sqlite():
    php = shutil.which("php")
    if not php:
        return None
    ok = subprocess.run([php, "-r", "exit(extension_loaded('pdo_sqlite') && extension_loaded('mbstring') ? 0 : 1);"]).returncode == 0
    return php if ok else None


MDP = {"jfk": "motdepasse-jfk", "dede": "motdepasse-dede", "alphonse": "motdepasse-alphonse"}


@pytest.fixture(scope="module")
def php(tmp_path_factory):
    php = _php_sqlite()
    if not php:
        pytest.skip("PHP avec pdo_sqlite absent")
    d = tmp_path_factory.mktemp("serveur")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    url = f"http://127.0.0.1:{port}"
    (d / "config.php").write_text(f"""<?php return ['base_url' => '{url}', 'donnees' => '{d}/donnees',
        'db' => ['type' => 'sqlite', 'chemin' => '{d}/s.sqlite'], 'cout_hash' => 4];""")
    env = dict(os.environ, SCRINIUM_CONFIG=str(d / "config.php"))
    cli = str(RACINE / "serveur" / "bin" / "scrinium-serveur")
    subprocess.run([php, cli, "initialiser"], env=env, check=True, capture_output=True)
    for nom, mdp in MDP.items():
        subprocess.run([php, cli, "creer-compte", nom], env=env, input=mdp + "\n", text=True, check=True, capture_output=True)
    pub = RACINE / "serveur" / "public"
    proc = subprocess.Popen([php, "-S", f"127.0.0.1:{port}", "-t", str(pub), str(pub / "index.php")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(5)


class Poste:
    def __init__(self, tmp_path, url, compte, mdp=None):
        self.store = Store(Paths(tmp_path / compte))
        self.store.charger()
        self.etat = synchro.EtatSynchro(synchro.chemin_etat(self.store, "srv")).charger()
        self.tr = ht.TransportHttp(url, compte, mdp or MDP.get(compte))

    def fiche(self, titre="Courses", texte="lait"):
        th = self.store.theme("Travail") or self.store.nouveau_theme("Travail")
        f = self.store.nouvelle_fiche(th)
        self.store.enregistrer(th, f, titre, texte)
        return th, f

    def sync(self):
        return synchroniser(self.store, self.etat, self.tr, maintenant="2026-10-29 10:00")

    def recue(self, titre):
        """(thème, fiche) reçue dans « Partagées » (le serveur d'essai est commun aux tests : plusieurs fiches peuvent s'y trouver)."""
        th = self.store.theme("Partagées")
        return th, next(f for f in th.fiches if f.titre == titre)


def test_serveur_connexion(php):
    assert ht.TransportHttp(php, "jfk", MDP["jfk"]).decouverte()["inscription"] == "invitation"
    with pytest.raises(NonAuthentifie):
        ht.TransportHttp(php, "jfk", "mauvais").lister()
    t = ht.TransportHttp(php, "jfk", MDP["jfk"])
    assert t.lister() is not None and t.jeton
    t.deconnecter()
    assert t.jeton is None


def test_serveur_partage_de_bout_en_bout(php, tmp_path):
    jfk, dede, alphonse = (Poste(tmp_path, php, c) for c in ("jfk", "dede", "alphonse"))
    th, f = jfk.fiche("Courses", "lait é")
    png = b"\x89PNG\r\n\x1a\n" + b"IMG" * 40
    jfk.store.ajouter_piece(f, "a.png", "image/png", png)
    partager(jfk.store, jfk.etat, jfk.tr, th, f, "dede", "ecriture")
    partager(jfk.store, jfk.etat, jfk.tr, th, f, "alphonse", "lecture")
    assert jfk.tr.droits(jfk.store.id_fiche(f)) == {"alphonse": "lecture", "dede": "ecriture", "jfk": "proprietaire"}

    assert dede.sync().nouvelles == ["Courses"] and alphonse.sync().nouvelles == ["Courses"]
    thd, fd = dede.recue("Courses")
    assert fd.texte.strip().endswith("lait é") and [p.nom for p in dede.store.lister_pieces(fd)] == ["a.png"]
    assert dede.store.lire_piece(fd, dede.store.lister_pieces(fd)[0]) == png

    dede.store.enregistrer(thd, fd, "Courses", "lait é, pain")                                 # dede écrit
    assert dede.sync().envoyees == ["Courses"]
    assert jfk.sync().recues == ["Courses"]
    assert "pain" in f.texte

    assert alphonse.sync().recues == ["Courses"]
    tha, fa = alphonse.recue("Courses")                                                        # alphonse (lecture) modifie : copie locale
    alphonse.store.enregistrer(tha, fa, "Courses", "gribouillage")
    b = alphonse.sync()
    assert len(b.ecartees) == 1 and b.envoyees == []
    assert "pain" in alphonse.recue("Courses")[1].texte
    assert any("gribouillage" in x.texte for t in alphonse.store.themes for x in t.fiches if "copie locale" in x.titre)
    jfk.sync()
    assert "gribouillage" not in f.texte


def test_serveur_conflit_et_invisibilite(php, tmp_path):
    jfk, dede, alphonse = (Poste(tmp_path, php, c) for c in ("jfk", "dede", "alphonse"))
    th, f = jfk.fiche("Projet", "v1")
    partager(jfk.store, jfk.etat, jfk.tr, th, f, "dede", "ecriture")
    ident = jfk.store.id_fiche(f)
    dede.sync()
    with pytest.raises(Introuvable):                                                           # alphonse ne voit rien
        alphonse.tr.lire(ident)
    assert [r.id for r in alphonse.tr.lister()] == [] or ident not in [r.id for r in alphonse.tr.lister()]
    with pytest.raises(ConflitDeVersion) as e:
        jfk.tr.ecrire(ident, ContenuDistant(0, "x", "y"), 0)
    assert e.value.version_serveur == 1
    with pytest.raises(Refuse):
        dede.tr.supprimer(ident)
    jfk.store.enregistrer(th, f, "Projet", "v2 de jfk")
    thd, fd = dede.recue("Projet")
    dede.store.enregistrer(thd, fd, "Projet", "v2 de dede")
    assert jfk.sync().envoyees == ["Projet"]
    b = dede.sync()
    assert len(b.conflits) == 1
    textes = [x.texte for t in dede.store.themes for x in t.fiches if x.titre.startswith("Projet")]
    assert any("v2 de jfk" in t for t in textes) and any("v2 de dede" in t for t in textes)    # rien de perdu


def test_serveur_invitation(php, tmp_path):
    jfk = Poste(tmp_path, php, "jfk")
    th, f = jfk.fiche("Invitée", "bonjour")
    inv = None
    from scrinium.core.synchroniser import publier
    publier(jfk.store, jfk.etat, jfk.tr, th, f)
    ident = jfk.store.id_fiche(f)
    inv = jfk.tr.inviter(ident, "nouveau@example.org", "lecture")
    serveur, jeton = lg.analyser_invitation(inv["url"])
    assert serveur == php
    assert jfk.tr.invitations(ident)[0]["etat"] == "en_attente"

    anonyme = ht.TransportHttp(php, "?", None)
    assert anonyme.decrire_invitation(jeton)["invite_par"] == "jfk"
    anonyme.rejoindre(jeton, "nouveau", "un-mot-de-passe-solide")
    assert anonyme.compte == "nouveau"
    with pytest.raises(Introuvable):                                                           # usage unique
        ht.TransportHttp(php, "?", None).rejoindre(jeton, "autre", "un-mot-de-passe-solide")

    nouveau = Poste(tmp_path, php, "nouveau", "un-mot-de-passe-solide")
    assert nouveau.sync().nouvelles == ["Invitée"]
    assert jfk.tr.invitations(ident)[0]["etat"] == "acceptee"

    inv2 = jfk.tr.inviter(ident, "autre@example.org", "ecriture")
    jfk.tr.annuler(inv2["id"])
    with pytest.raises(Introuvable):
        ht.TransportHttp(php, "?", None).decrire_invitation(lg.analyser_invitation(inv2["url"])[1])

    dede = Poste(tmp_path, php, "dede")                                                        # compte existant : se connecte
    inv3 = jfk.tr.inviter(ident, "dede@example.org", "lecture")
    dede.tr.rejoindre(lg.analyser_invitation(inv3["url"])[1])
    assert "Invitée" in dede.sync().nouvelles
