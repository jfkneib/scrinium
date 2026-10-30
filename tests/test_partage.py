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
MDP = {"jfk": "motdepasse-jfk", "dede": "motdepasse-dede", "alphonse": "motdepasse-alphonse"}   # comptes créés par la fixture `php`


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
    assert lg.nom_depot("https://scrinium.exemple.org:8443") == "scrinium.exemple.org-8443"
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


# ---------- thème entier ----------
th_mod = _charger("theme")


def test_serveur_theme_entier(php, tmp_path):
    jfk = Poste(tmp_path, php, "jfk")
    th = jfk.store.nouveau_theme("Voyage")
    titres = ["Billets", "Hôtel", "Valise"]
    for t in titres:
        f = jfk.store.nouvelle_fiche(th)
        jfk.store.enregistrer(th, f, t + " Th", "texte " + t)
    secret = jfk.store.nouvelle_fiche(th)
    jfk.store.enregistrer(th, secret, "Passeport Th", "n° 123")
    jfk.store.verrouiller(th, secret, "motdepasse")

    pretes, autres, verrouillees = th_mod.fiches_du_theme(jfk.store, th, jfk.tr)
    assert len(pretes) == 3 and verrouillees == 1 and autres == []

    # invitation d'une personne qui a déjà un compte : un seul lien pour tout le thème
    n, inv = th_mod.inviter_theme(jfk.store, jfk.etat, jfk.tr, th, "dede@example.org", "lecture")
    assert n == len(pretes)
    _serveur, jeton = lg.analyser_invitation(inv["url"])
    assert ht.TransportHttp(php, "?", None).decrire_invitation(jeton)["fiches"] == n
    dede = Poste(tmp_path, php, "dede")
    dede.tr.rejoindre(jeton)
    recues = dede.sync().nouvelles
    assert all(t + " Th" in recues for t in titres)
    assert "Passeport Th" not in recues

    # droits communs, puis nouvelle fiche du thème suivie : mise en ligne avec les mêmes droits
    ids = [jfk.store.id_fiche(f) for f, _i in th_mod.fiches_du_theme(jfk.store, th, jfk.tr)[0]]
    assert th_mod.droits_communs(jfk.tr, ids) == {"dede": "lecture"}
    th_mod.partager_theme(jfk.store, jfk.etat, jfk.tr, th, "alphonse", "ecriture")
    assert th_mod.droits_communs(jfk.tr, ids) == {"dede": "lecture", "alphonse": "ecriture"}
    nouvelle = jfk.store.nouvelle_fiche(th)
    jfk.store.enregistrer(th, nouvelle, "Taxi Th", "gare")
    assert th_mod.propager(jfk.store, jfk.etat, jfk.tr, th) == ["Taxi Th"]
    assert jfk.tr.droits(jfk.store.id_fiche(nouvelle)) == {"jfk": "proprietaire", "dede": "lecture", "alphonse": "ecriture"}
    assert th_mod.propager(jfk.store, jfk.etat, jfk.tr, th) == []
    assert "Taxi Th" in dede.sync().nouvelles

    # retirer un compte de tout le thème
    th_mod.retirer_theme(jfk.store, jfk.tr, th, "alphonse")
    assert th_mod.droits_communs(jfk.tr, ids) == {"dede": "lecture"}
    # une fiche reçue d'un autre compte n'est jamais partagée par moi
    thd = dede.store.theme("Partagées")
    pretes_d, autres_d, _v = th_mod.fiches_du_theme(dede.store, thd, dede.tr)
    assert pretes_d == [] and "Billets Th" in autres_d


# ---------- serveur derrière un proxy : adresse avec préfixe ----------
def test_prefixe_de_chemin_dans_l_adresse_du_serveur():
    vus = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            vus.append(self.path)
            corps = b'{"api": 1, "serveur": "0.2.0", "inscription": "invitation", "limites": {}}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        ht.TransportHttp(f"http://127.0.0.1:{port}/scrinium/", "jfk").decouverte()
        ht.TransportHttp(f"http://127.0.0.1:{port}", "jfk").decouverte()
        assert vus == ["/scrinium/api", "/api"]
    finally:
        srv.shutdown()
    lien = "https://exemple.org:8443/scrinium/inviter/" + JETON
    assert lg.analyser_invitation(lien) == ("https://exemple.org:8443/scrinium", JETON)


# ---------- dépôt : une requête POST crée une fiche qui arrive à la synchronisation ----------
def test_serveur_depot_arrive_a_la_synchronisation(php, tmp_path):
    jfk = Poste(tmp_path, php, "jfk")
    r = jfk.tr._json("POST", "/depot", {"titre": "Dépôt é", "texte": "reçu par POST"})
    assert r["version"] == 1 and len(r["id"]) == 32
    b = jfk.sync()
    assert "Dépôt é" in b.nouvelles
    th, f = jfk.recue("Dépôt é")
    assert f.texte.strip().endswith("reçu par POST")
    assert jfk.store.id_fiche(f) == r["id"]
    with pytest.raises(Refuse):                                           # texte vide : refusé (422)
        jfk.tr._json("POST", "/depot", {"texte": ""})
