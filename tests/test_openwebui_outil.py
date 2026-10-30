# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Outil Open WebUI « Scrinium · créer une fiche » (exemples/openwebui/) : dépôt, titres, erreurs, empreinte du certificat."""
import http.server
import importlib.util
import json
import sys
import threading
import types
from pathlib import Path

import pytest

from tests.test_partage import MDP, Poste, serveur_tls  # noqa: F401  (serveur PHP et serveur TLS d'essai)

FICHIER = Path(__file__).resolve().parent.parent / "exemples" / "openwebui" / "scrinium_depot.py"


def _outil(monkeypatch, **valves):
    """Charge l'outil (avec un faux « pydantic » minimal s'il n'est pas installé : Open WebUI, lui, a le vrai)."""
    try:
        import pydantic  # noqa: F401
    except ImportError:
        faux = types.ModuleType("pydantic")

        class BaseModel:
            def __init__(self, **kw):
                for k, v in vars(type(self)).items():
                    if not k.startswith("_"):
                        setattr(self, k, v)
                for k, v in kw.items():
                    setattr(self, k, v)
        faux.BaseModel, faux.Field = BaseModel, lambda default=None, **kw: default
        monkeypatch.setitem(sys.modules, "pydantic", faux)
    spec = importlib.util.spec_from_file_location("scrinium_depot_outil", FICHIER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    t = mod.Tools()
    for k, v in valves.items():
        setattr(t.valves, k, v)
    return t


class _Faux(http.server.BaseHTTPRequestHandler):
    reponse, recus = (201, {"id": "a" * 32, "titre": "[IA] x", "version": 1}), []

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        type(self).recus.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(n))))
        statut, corps = type(self).reponse
        brut = json.dumps(corps).encode()
        self.send_response(statut)
        self.send_header("Content-Length", str(len(brut)))
        self.end_headers()
        self.wfile.write(brut)

    def log_message(self, *a):
        pass


@pytest.fixture
def faux_serveur():
    _Faux.recus, _Faux.reponse = [], (201, {"id": "a" * 32, "titre": "[IA] x", "version": 1})
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Faux)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_cree_la_fiche_avec_prefixe_et_jeton(monkeypatch, faux_serveur):
    t = _outil(monkeypatch, serveur=faux_serveur + "/scrinium", jeton="j" * 64)
    rep = t.creer_fiche("Idée", "penser au certificat")
    assert "Fiche créée" in rep and "synchronisation" in rep and "j" * 64 not in rep                  # le jeton n'est jamais renvoyé
    chemin, auth, corps = _Faux.recus[0]
    assert chemin == "/scrinium/api/v1/depot" and auth == "Bearer " + "j" * 64
    assert corps == {"titre": "[IA] Idée", "texte": "penser au certificat"}
    t.creer_fiche("[IA] Déjà préfixé", "x")
    assert _Faux.recus[1][2]["titre"] == "[IA] Déjà préfixé"                                          # pas de double préfixe
    t.valves.prefixe_titre = ""
    t.creer_fiche("Sans préfixe", "x")
    assert _Faux.recus[2][2]["titre"] == "Sans préfixe"


def test_refus_sans_jeton_ni_contenu(monkeypatch, faux_serveur):
    t = _outil(monkeypatch, serveur=faux_serveur)
    assert "jeton" in t.creer_fiche("a", "b").lower() and _Faux.recus == []                          # jeton non renseigné : rien d'envoyé
    t.valves.jeton = "j" * 64
    assert "Rien à enregistrer" in t.creer_fiche("  ", "   ") and _Faux.recus == []


@pytest.mark.parametrize("statut,attendu", [(401, "refuse le jeton"), (429, "Trop de fiches"), (413, "code 413"), (422, "titre requis")])
def test_messages_d_erreur_clairs(monkeypatch, faux_serveur, statut, attendu):
    _Faux.reponse = (statut, {"message": "titre requis"})
    t = _outil(monkeypatch, serveur=faux_serveur, jeton="j" * 64)
    assert attendu in t.creer_fiche("a", "b")


def test_serveur_injoignable_et_adresse_refusee(monkeypatch):
    t = _outil(monkeypatch, serveur="http://127.0.0.1:9", jeton="j" * 64, delai=2)
    assert "injoignable" in t.creer_fiche("a", "b")
    t.valves.serveur = "ftp://exemple.org"
    assert "adresse du serveur invalide" in t.creer_fiche("a", "b")
    t.valves.serveur = "http://exemple.org"                                                           # http hors réseau local : refusé
    assert "https" in t.creer_fiche("a", "b")


def test_empreinte_du_certificat(monkeypatch, serveur_tls):  # noqa: F811
    url, empreinte = serveur_tls                                                                      # serveur TLS auto-signé d'essai
    t = _outil(monkeypatch, serveur=url, jeton="j" * 64, empreinte="00" * 32, delai=3)
    assert "ne correspond pas" in t.creer_fiche("a", "b")                                             # mauvaise empreinte : refusé
    t.valves.empreinte = ":".join(empreinte[i:i + 2] for i in range(0, 64, 2)).upper()
    assert "ne correspond pas" not in t.creer_fiche("a", "b")                                         # bonne empreinte (même écrite avec « : »)
    t.valves.empreinte = ""
    assert "injoignable" in t.creer_fiche("a", "b")                                                   # auto-signé sans empreinte : non fiable


def test_de_bout_en_bout_avec_le_vrai_serveur(monkeypatch, php, tmp_path):
    jfk = Poste(tmp_path, php, "jfk")
    jfk.tr.lister()                                                                                    # ouvre une session : son jeton sert de dépôt
    t = _outil(monkeypatch, serveur=php, jeton=jfk.tr.jeton)
    assert "Fiche créée" in t.creer_fiche("Résumé de test", "ligne 1\nligne 2")
    assert "[IA] Résumé de test" in jfk.sync().nouvelles
    th, f = jfk.recue("[IA] Résumé de test")
    assert f.texte.strip().endswith("ligne 2")
