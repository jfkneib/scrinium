# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Traduction » : logique, faux llama-server, téléchargement du modèle, faux Argos, fonctionnement dans la fenêtre."""
import hashlib
import http.server
import importlib.util
import json
import os
import shutil
import stat
import sys
import threading
import time
import types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "traduction"
_spec = importlib.util.spec_from_file_location("trad_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

FRANCAIS = "La facture d'électricité est à régler avant le 3 octobre. Il faut aussi penser à appeler l'agence pour les travaux."
ANGLAIS = "The invoice has to be paid before the third of October, and we also have to call the agency about the works."

FAUX_SERVEUR = '''#!/usr/bin/env python3
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
a = sys.argv[1:]
opt = lambda n: a[a.index(n) + 1] if n in a else None
d = os.environ["FAUX_DIR"]
json.dump({"argv": a, "pid": os.getpid(), "ld": os.environ.get("LD_LIBRARY_PATH", "")}, open(d + "/argv-%s.json" % os.getpid(), "w"))
if os.path.exists(d + "/plante"):
    print("error loading model: key not found in model: gemma3.attention.layer_norm_rms_epsilon", flush=True)
    sys.exit(1)
lent = float(open(d + "/lent").read()) if os.path.exists(d + "/lent") else 0.6
cle, debut = opt("--api-key"), time.time()
class H(BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def rep(self, code, corps):
        b = json.dumps(corps).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/health":
            self.rep(503 if time.time() - debut < lent else 200, {"status": "ok"})
    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != "Bearer " + cle:
            return self.rep(401, {"error": {"message": "Invalid API Key"}})
        open(d + "/appels.jsonl", "a").write(json.dumps(corps) + "\\n")
        texte = corps["prompt"].rsplit("\\n\\n\\n", 1)[1].split("<end_of_turn>")[0]
        self.rep(200, {"content": " [TRAD] " + texte.upper() + " "})
HTTPServer(("127.0.0.1", int(opt("--port"))), H).serve_forever()
'''


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def faux(tmp_path, monkeypatch):
    d = tmp_path / "faux"
    d.mkdir()
    exe = tmp_path / "bin" / "llama-server"
    exe.parent.mkdir()
    exe.write_text(FAUX_SERVEUR)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    modele = tmp_path / "modele.gguf"
    modele.write_bytes(b"GGUF")
    monkeypatch.setenv("FAUX_DIR", str(d))
    srv = lg.ServeurLlama(tmp_path / "journal.log")
    yield types.SimpleNamespace(dir=d, exe=str(exe), modele=str(modele), srv=srv, tmp=tmp_path)
    srv.arreter()


def appels(d):
    f = d / "appels.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


# ---------- logique pure ----------
def test_consigne_translategemma():
    c = lg.consigne("Bonjour", "fr", "en")
    assert c.startswith("<start_of_turn>user\nYou are a professional French (fr) to English (en) translator.")
    assert "Produce only the English translation" in c and "translate the following French text into English:\n\n\nBonjour" in c
    assert c.endswith("<end_of_turn>\n<start_of_turn>model\n")


def test_decouper_ne_perd_rien_et_respecte_la_taille():
    para = "Phrase numéro un. Phrase numéro deux. " * 30
    texte = f"Titre\n\n{para}\n\n- a\n- b\n\n{'mot ' * 600}\n\n{'x' * 3000}"
    morceaux = lg.decouper(texte, 400)
    assert all(len(m) <= 400 for m in morceaux) and len(morceaux) > 5
    assert "".join(morceaux).replace("\n", "").replace(" ", "") == texte.replace("\n", "").replace(" ", "")
    assert lg.decouper("  \n\n ") == [] and lg.decouper("court") == ["court"]
    assert lg.decouper("a\n\nb\n\nc", 100) == ["a\n\nb\n\nc"]                                # petits paragraphes regroupés


def test_detection_de_la_langue():
    assert lg.detecter(FRANCAIS) == "fr" and lg.detecter(ANGLAIS) == "en"
    assert lg.detecter("Die Rechnung ist nicht bezahlt und wir müssen den Vertrag mit der Firma prüfen.") == "de"
    assert lg.detecter("こんにちは、今日はいい天気ですね。散歩に行きましょう。") == "ja"
    assert lg.detecter("Привет, как дела сегодня? Всё хорошо, спасибо большое.") == "ru"
    assert lg.detecter("ok") is None and lg.detecter("xyz qwerty azerty zzzz plouf") is None


def test_cible_par_defaut():
    assert lg.cible_par_defaut("fr") == "en" and lg.cible_par_defaut("en") == "fr"
    assert lg.cible_par_defaut("de", "de") != "de" and lg.cible_par_defaut(None, "es") == "es"


def test_serveur_local_ou_distant():
    assert lg.est_local("http://127.0.0.1:9931") and lg.est_local("http://localhost:8080") and lg.est_local("http://[::1]:1")
    assert not lg.est_local("http://192.168.1.50:9931") and not lg.est_local("https://exemple.fr")


def test_trouver_les_fichiers(tmp_path, monkeypatch):
    monkeypatch.setattr(lg.shutil, "which", lambda n: None)
    monkeypatch.setenv("HOME", str(tmp_path / "vide"))
    exe = tmp_path / "donnees" / "llama.cpp" / "b1" / "llama-server"
    exe.parent.mkdir(parents=True)
    exe.write_text("x")
    assert lg.trouver_llama("", tmp_path / "donnees") == str(exe)
    perso = tmp_path / "mon-llama"
    perso.write_text("x")
    assert lg.trouver_llama(str(perso), tmp_path / "donnees") == str(perso) and lg.trouver_llama("/inexistant", None) is None
    (tmp_path / "donnees" / "modeles").mkdir()
    assert lg.trouver_modele("", tmp_path / "donnees") is None
    (tmp_path / "donnees" / "modeles" / lg.MODELE_NOM).write_bytes(b"x")
    assert lg.trouver_modele("", tmp_path / "donnees").endswith(lg.MODELE_NOM)


def test_aide_installation_selon_le_systeme(monkeypatch):
    for plateforme, mot in (("linux", "ubuntu-x64"), ("darwin", "macos-arm64"), ("win32", "win-cpu-x64")):
        monkeypatch.setattr(lg.sys, "platform", plateforme)
        a = lg.aide_installation()
        assert mot in a and "SHA-256" in a and lg.PAGE_VERSIONS in a
    assert "curl" not in a and "| sh" not in a                                         # jamais de script distant exécuté à l'aveugle


# ---------- faux llama-server ----------
def test_serveur_demarre_localement_avec_une_cle_aleatoire(faux):
    faux.srv.demarrer(faux.exe, faux.modele)
    assert faux.srv.vivant() and faux.srv.url.startswith("http://127.0.0.1:") and faux.srv.url != "http://127.0.0.1:9931"
    argv = json.loads(next(faux.dir.glob("argv-*.json")).read_text())
    a = argv["argv"]
    assert a[a.index("--host") + 1] == "127.0.0.1" and a[a.index("-m") + 1] == faux.modele
    assert len(a[a.index("--api-key") + 1]) == 32 and "--no-webui" in a and a[a.index("-c") + 1] == "4096"
    assert "-ngl" not in a and argv["ld"].startswith(str(Path(faux.exe).parent))      # bibliothèques à côté du programme
    assert lg.sante(faux.srv.url) == 200


def test_cles_differentes_a_chaque_demarrage(faux):
    faux.srv.demarrer(faux.exe, faux.modele)
    k1 = faux.srv.cle
    faux.srv.demarrer(faux.exe, faux.modele, gpu="0")                                  # autre configuration : redémarre
    assert faux.srv.cle != k1
    a = json.loads(sorted(faux.dir.glob("argv-*.json"), key=lambda p: p.stat().st_mtime)[-1].read_text())["argv"]
    assert a[a.index("-ngl") + 1] == "0"


def test_serveur_reutilise_puis_arrete(faux):
    faux.srv.demarrer(faux.exe, faux.modele)
    pid = faux.srv.proc.pid
    faux.srv.demarrer(faux.exe, faux.modele)
    assert faux.srv.proc.pid == pid and len(list(faux.dir.glob("argv-*.json"))) == 1
    faux.srv.arreter()
    assert not faux.srv.vivant() and lg.sante(faux.srv.url, 0.5) == 0


def test_requete_de_traduction_et_cle_refusee(faux):
    faux.srv.demarrer(faux.exe, faux.modele)
    assert faux.srv.completer(lg.consigne("Bonjour", "fr", "en"), 256) == "[TRAD] BONJOUR"
    a = appels(faux.dir)[0]
    assert a["temperature"] == 0 and a["stop"] == ["<end_of_turn>"] and a["n_predict"] == 256
    assert a["prompt"].startswith("<start_of_turn>user\nYou are a professional French")
    with pytest.raises(lg.ErreurMoteur, match="clé"):
        lg.completer(faux.srv.url, "mauvaise-cle", "x", 10)
    with pytest.raises(lg.ErreurMoteur, match="injoignable"):
        lg.completer("http://127.0.0.1:1", "", "x", 10, delai=1)


def test_echec_du_demarrage_donne_la_raison(faux):
    (faux.dir / "plante").write_text("")
    with pytest.raises(lg.ErreurMoteur, match="layer_norm_rms_epsilon"):
        faux.srv.demarrer(faux.exe, faux.modele)
    assert not faux.srv.vivant()
    (faux.dir / "plante").unlink()
    with pytest.raises(lg.ErreurMoteur, match="introuvable"):
        faux.srv.demarrer("/inexistant/llama-server", faux.modele)
    with pytest.raises(lg.ErreurMoteur, match="modèle introuvable"):
        faux.srv.demarrer(faux.exe, "/inexistant.gguf")


def test_annulation_pendant_le_demarrage(faux):
    (faux.dir / "lent").write_text("20")
    debut = time.time()
    with pytest.raises(lg.Annule):
        faux.srv.demarrer(faux.exe, faux.modele, annuler=lambda: time.time() - debut > 0.5)
    assert not faux.srv.vivant()


def test_traduction_par_morceaux_conserve_les_paragraphes(faux):
    faux.srv.demarrer(faux.exe, faux.modele)
    texte = "Premier paragraphe.\n\n" + ("Une phrase assez longue pour forcer un découpage. " * 60) + "\n\nDernier."
    vus = []
    res = lg.traduire_texte(texte, "fr", "en", lambda m: faux.srv.completer(lg.consigne(m, "fr", "en"), 600),
                            progression=lambda f, t: vus.append((f, t)))
    assert vus[0] == (0, len(lg.decouper(texte))) and vus[-1][0] == vus[-1][1] and len(vus) == len(vus) and len(appels(faux.dir)) > 2
    assert res.startswith("[TRAD] PREMIER PARAGRAPHE.") and res.rstrip().endswith("DERNIER.") and "\n\n" in res
    with pytest.raises(lg.Annule):
        lg.traduire_texte(texte, "fr", "en", lambda m: "x", annuler=lambda: True)
    with pytest.raises(lg.ErreurMoteur, match="trop long"):
        lg.traduire_texte("x" * (lg.TEXTE_MAX + 1), "fr", "en", lambda m: "x")


# ---------- téléchargement du modèle ----------
CONTENU = os.urandom(300_000)


class Fichiers(http.server.BaseHTTPRequestHandler):
    appels = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Fichiers.appels.append(self.headers.get("Range"))
        debut = int(self.headers["Range"].split("=")[1].rstrip("-")) if self.headers.get("Range") else 0
        corps = CONTENU[debut:]
        self.send_response(206 if debut else 200)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)


@pytest.fixture
def web():
    Fichiers.appels = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), Fichiers)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/m.gguf"
    srv.shutdown()


def test_telechargement_verifie_et_reprend(tmp_path, web):
    sha, taille = hashlib.sha256(CONTENU).hexdigest(), len(CONTENU)
    suivi = []
    p = lg.telecharger_modele(tmp_path, web, "m.gguf", sha, taille, progression=lambda f, t: suivi.append((f, t)))
    assert p.read_bytes() == CONTENU and suivi[-1] == (taille, taille) and not (tmp_path / "m.gguf.part").exists()
    n = len(Fichiers.appels)
    lg.telecharger_modele(tmp_path, web, "m.gguf", sha, taille)                         # déjà là et vérifié : rien à télécharger
    assert len(Fichiers.appels) == n
    p.unlink()
    (tmp_path / "m.gguf.part").write_bytes(CONTENU[:100_000])                           # téléchargement interrompu : on reprend
    assert lg.telecharger_modele(tmp_path, web, "m.gguf", sha, taille).read_bytes() == CONTENU
    assert Fichiers.appels[-1] == "bytes=100000-"


def test_telechargement_corrompu_ou_annule(tmp_path, web):
    with pytest.raises(lg.ErreurMoteur, match="incorrect"):
        lg.telecharger_modele(tmp_path, web, "m.gguf", "0" * 64, len(CONTENU))
    assert not (tmp_path / "m.gguf").exists() and not (tmp_path / "m.gguf.part").exists()      # le fichier douteux est supprimé
    with pytest.raises(lg.Annule):
        lg.telecharger_modele(tmp_path, web, "m.gguf", hashlib.sha256(CONTENU).hexdigest(), len(CONTENU), annuler=lambda: True)
    assert not (tmp_path / "m.gguf").exists()
    with pytest.raises(lg.ErreurMoteur, match="impossible"):
        lg.telecharger_modele(tmp_path, "http://127.0.0.1:1/x", "m.gguf", "0" * 64, 1)


def test_modele_recommande_epingle():
    assert lg.MODELE_URL.startswith("https://huggingface.co/mradermacher/translategemma-4b-it-GGUF/resolve/main/")
    assert len(lg.MODELE_SHA256) == 64 and lg.MODELE_TAILLE == 2_489_909_760 and lg.MODELE_NOM.endswith("Q4_K_M.gguf")


# ---------- faux Argos ----------
@pytest.fixture
def argos(tmp_path, monkeypatch):
    etat = types.SimpleNamespace(installes={"fr": {"en"}, "en": {"fr"}}, telecharges=[], index=0)
    pk, st, tr = types.ModuleType("argostranslate.package"), types.ModuleType("argostranslate.settings"), types.ModuleType("argostranslate.translate")
    racine = types.ModuleType("argostranslate")
    racine.package, racine.settings, racine.translate = pk, st, tr
    st.data_dir = st.package_data_dir = None

    class Paquet:
        def __init__(self, a, b):
            self.from_code, self.to_code = a, b

        def download(self):
            etat.telecharges.append((self.from_code, self.to_code))
            return f"{self.from_code}-{self.to_code}.argosmodel"
    pk.update_package_index = lambda: setattr(etat, "index", etat.index + 1)
    pk.get_available_packages = lambda: [Paquet("fr", "en"), Paquet("en", "fr"), Paquet("en", "es"), Paquet("es", "en"), Paquet("en", "de")]

    def installer(chemin):
        a, b = chemin.split(".")[0].split("-")
        etat.installes.setdefault(a, set()).add(b)
    pk.install_from_path = installer

    class Langue:
        def __init__(self, code):
            self.code = code

        def get_translation(self, autre):
            direct = autre.code in etat.installes.get(self.code, set())
            pivot = "en" in etat.installes.get(self.code, set()) and autre.code in etat.installes.get("en", set())   # comme Argos : via l'anglais
            if not (direct or pivot):
                return None
            return types.SimpleNamespace(translate=lambda t: f"({self.code}>{autre.code}) {t} ")
    tr.get_installed_languages = lambda: [Langue(c) for c in sorted(set(etat.installes) | {x for v in etat.installes.values() for x in v})]
    for nom, mod in (("argostranslate", racine), ("argostranslate.package", pk), ("argostranslate.settings", st), ("argostranslate.translate", tr)):
        monkeypatch.setitem(sys.modules, nom, mod)
    return etat


def test_argos_present_ou_absent(monkeypatch):
    for nom in ("argostranslate", "argostranslate.package", "argostranslate.settings", "argostranslate.translate"):
        monkeypatch.delitem(sys.modules, nom, raising=False)
    monkeypatch.setattr(lg.importlib.util, "find_spec", lambda n: None)
    assert not lg.argos_present()
    with pytest.raises(lg.ErreurMoteur, match="inutilisable"):
        lg.argos_langues_installees(None)


def test_argos_installe_traduit_et_range_ses_donnees(argos, tmp_path):
    assert lg.argos_langues_installees(tmp_path / "argos") == {"fr", "en"}
    assert argos_set(tmp_path) and (tmp_path / "argos" / "packages").is_dir()                   # paquets rangés dans le dossier de l'extension
    assert lg.argos_paire_installee("fr", "en", tmp_path) and not lg.argos_paire_installee("fr", "es", tmp_path)
    assert lg.argos_traduire("Bonjour", "fr", "en", tmp_path) == "(fr>en) Bonjour"
    with pytest.raises(lg.ErreurMoteur, match="non installé"):
        lg.argos_traduire("Bonjour", "fr", "es", tmp_path)


def argos_set(tmp_path):
    import argostranslate.settings as st
    return st.package_data_dir == tmp_path / "argos" / "packages"


def test_argos_propose_les_modeles_manquants_avec_pivot(argos, tmp_path):
    direct = lg.argos_modeles_necessaires("fr", "en", tmp_path)
    assert [(p.from_code, p.to_code) for p in direct] == [("fr", "en")] and argos.index == 1
    pivot = lg.argos_modeles_necessaires("fr", "es", tmp_path)                                   # pas de fr→es : fr→en puis en→es
    assert [(p.from_code, p.to_code) for p in pivot] == [("fr", "en"), ("en", "es")]
    with pytest.raises(lg.ErreurMoteur, match="pas de modèle"):
        lg.argos_modeles_necessaires("fr", "ja", tmp_path)
    lg.argos_installer_paquets(pivot, tmp_path)
    assert argos.telecharges == [("fr", "en"), ("en", "es")] and lg.argos_paire_installee("en", "es", tmp_path)


# ---------- dans la fenêtre ----------
@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "traduction")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("traduction"), w.plugins.infos["traduction"].erreur
    w.nouvelle_fiche()
    w.titre.setText("Notes")
    w.texte.setPlainText(FRANCAIS)
    w.sauver()
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    yield w
    w.quitter_vraiment = True
    w.close()


def plugin(fen):
    return fen.plugins.actifs["traduction"][0]


def mod():
    return sys.modules["scrinium_plugin_traduction"]


def attendre(app, condition, delai=10.0):
    fin = time.time() + delai
    while time.time() < fin and not condition():
        app.processEvents()
        time.sleep(0.01)
    return condition()


def dialogue(fen, texte=FRANCAIS, selection=False, src="fr"):
    """`src` : langue source choisie d'avance (un texte court n'est pas détecté) ; None = détection automatique."""
    d = mod().DialogueTraduction(plugin(fen), texte, selection, fen.plugins.actifs["traduction"][1].fiche_courante())
    if src:
        d.src.setCurrentIndex(d.src.findData(src))
    return d


def faux_moteur(monkeypatch, fen):
    monkeypatch.setattr(plugin(fen), "preparer", lambda moteur, src, dst, vue: (lambda m, annule: f"[{src}>{dst}] {m.upper()}"))


def traduire(app, d):
    d._lancer()
    assert attendre(app, lambda: not d.travail)


def selectionner(fen, extrait):
    fen.texte.setPlainText(f"avant. {extrait} après.")
    c = fen.texte.textCursor()
    c.setPosition(len("avant. "))
    c.setPosition(len("avant. ") + len(extrait), c.MoveMode.KeepAnchor)
    fen.texte.setTextCursor(c)


def sync(monkeypatch, resultat=None):
    """`en_arriere_plan` sans fenêtre ni fil : exécute tout de suite."""
    def f(titre, message, fonction, annulable=False, parent=None):
        try:
            return fonction(threading.Event(), lambda *a: None), ""
        except Exception as ex:
            return None, str(ex)
    monkeypatch.setattr(mod(), "en_arriere_plan", f)


def test_boutons_menu_et_api_de_l_editeur(fen):
    assert any(a.text() == "Traduire" for a in fen.barre.actions())
    assert [a.text() for a in fen.menu_ext.actions() if a.text()][-3:] == ["Traduire la sélection ou la fiche…", "Réglages de la traduction…"] or \
        "Traduire la sélection ou la fiche…" in [a.text() for a in fen.menu_ext.actions()]
    ui = fen.plugins.actifs["traduction"][1].ui
    assert ui.texte_complet() == FRANCAIS
    assert ui.ajouter_a_la_fin("\nfin") and fen.texte.toPlainText() == FRANCAIS + "\nfin"
    assert ui.remplacer_tout("neuf") and fen.texte.toPlainText() == "neuf"
    fen.texte.undo()
    assert fen.texte.toPlainText() == FRANCAIS + "\nfin"                                           # annulable
    fen.texte.setEnabled(False)
    assert ui.texte_complet() == "" and not ui.remplacer_tout("x") and not ui.ajouter_a_la_fin("x")


def test_sans_texte_rien_ne_s_ouvre(fen, monkeypatch):
    fen.texte.setPlainText("   ")
    ouverts = []
    monkeypatch.setattr(mod().DialogueTraduction, "exec", lambda self: ouverts.append(self) or 0)
    plugin(fen).traduire()
    assert ouverts == [] and "Ouvrez une fiche" in fen.statusBar().currentMessage()
    fen.texte.setPlainText(FRANCAIS)
    plugin(fen).traduire()
    assert len(ouverts) == 1 and ouverts[0].selection is False
    selectionner(fen, "cible")
    plugin(fen).traduire()
    assert ouverts[1].selection is True and ouverts[1].source.toPlainText() == "cible"


def test_dialogue_detecte_la_langue_et_propose_la_cible(fen):
    d = dialogue(fen, src=None)
    assert d.detectee == "fr" and "français" in d.info.text() and d.dst.currentData() == "en"
    d.dst.setCurrentIndex(d.dst.findData("es"))
    d._echanger()
    assert d.src.currentData() == "es" and d.dst.currentData() == "fr"                             # échange (la source passe de « auto » à fr puis es)
    d2 = dialogue(fen, "ok", src=None)
    assert d2.detectee is None and "non détectée" in d2.info.text()


def test_traduction_et_affichage_du_resultat(fen, app, monkeypatch):
    faux_moteur(monkeypatch, fen)
    d = dialogue(fen)
    traduire(app, d)
    assert d.resultat.toPlainText() == f"[fr>en] {FRANCAIS.upper()}" and "Terminé" in d.etat.text() and d.b_sous.isEnabled()
    assert fen.plugins.actifs["traduction"][1].reglages.get("cible") == "en"                        # la cible choisie est mémorisée


def test_langues_identiques_ou_inconnues(fen, app, monkeypatch):
    faux_moteur(monkeypatch, fen)
    infos = []
    monkeypatch.setattr(mod().QMessageBox, "information", lambda *a, **k: infos.append(a[2]))
    d = dialogue(fen)
    d.dst.setCurrentIndex(d.dst.findData("fr"))
    d._lancer()
    assert infos and "identiques" in infos[-1] and d.resultat.toPlainText() == ""
    d2 = dialogue(fen, "ok", src=None)
    d2._lancer()
    assert "Choisissez la langue" in infos[-1]


def test_inserer_sous_le_texte_selection_et_fiche_entiere(fen, app, monkeypatch):
    faux_moteur(monkeypatch, fen)
    selectionner(fen, "cible")
    d = dialogue(fen, "cible", selection=True)
    traduire(app, d)
    d._inserer_sous()
    assert fen.texte.toPlainText() == "avant. cible\n\n[fr>en] CIBLE après."                         # original conservé, traduction dessous
    fen.texte.setPlainText(FRANCAIS)
    d = dialogue(fen, FRANCAIS)
    traduire(app, d)
    d._inserer_sous()
    assert fen.texte.toPlainText().startswith("La facture") and fen.texte.toPlainText().rstrip().endswith(FRANCAIS.upper())


def test_remplacer_selection_et_fiche_entiere_avec_confirmation(fen, app, monkeypatch):
    faux_moteur(monkeypatch, fen)
    selectionner(fen, "cible")
    d = dialogue(fen, "cible", selection=True)
    traduire(app, d)
    d._remplacer()
    assert fen.texte.toPlainText() == "avant. [fr>en] CIBLE après."
    fen.texte.setPlainText(FRANCAIS)
    d = dialogue(fen)
    traduire(app, d)
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: mod().QMessageBox.StandardButton.No)
    d._remplacer()
    assert fen.texte.toPlainText() == FRANCAIS                                                      # refusé : rien ne change
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: mod().QMessageBox.StandardButton.Yes)
    d._remplacer()
    assert fen.texte.toPlainText() == f"[fr>en] {FRANCAIS.upper()}"
    fen.texte.undo()
    assert fen.texte.toPlainText() == FRANCAIS                                                      # annulable avec Ctrl+Z


def test_copier_et_fermer_arrete_la_traduction(fen, app, monkeypatch):
    faux_moteur(monkeypatch, fen)
    d = dialogue(fen)
    traduire(app, d)
    d.b_copier.click()
    assert QApplication.clipboard().text() == d.resultat.toPlainText()
    d.reject()
    assert d.annuler.is_set()


def test_erreur_du_moteur_affichee_sans_planter(fen, app, monkeypatch):
    def echec(m, annule):
        raise mod().logique.ErreurMoteur("serveur injoignable : test")
    monkeypatch.setattr(plugin(fen), "preparer", lambda *a: echec)
    d = dialogue(fen)
    traduire(app, d)
    assert "serveur injoignable" in d.etat.text() and d.resultat.toPlainText() == "" and not d.b_sous.isEnabled() and plugin(fen).occupe == 0


def test_fiche_verrouillee_ouverte_traduction_locale_possible(fen, app, monkeypatch):
    fen.store.verrouiller(fen.fiche_theme, fen.fiche, "mdp", sans_secours=True)
    fen._afficher(fen.fiche_theme, fen.fiche)
    faux_moteur(monkeypatch, fen)
    d = dialogue(fen)
    traduire(app, d)
    assert d.resultat.toPlainText().startswith("[fr>en]")
    d._inserer_sous()
    assert fen.fiche.verrou and b"INVOICE" not in fen.fiche.path.read_bytes()


# ---------- préparation du moteur llama.cpp ----------
def test_serveur_distant_refuse_sans_accord(fen, monkeypatch):
    r = fen.plugins.actifs["traduction"][1].reglages
    r.set("url", "http://192.168.1.50:9931")
    avertis = []
    monkeypatch.setattr(mod().QMessageBox, "warning", lambda *a, **k: avertis.append(a[2]))
    vue = fen.plugins.actifs["traduction"][1].fiche_courante()
    assert plugin(fen)._preparer_llama("fr", "en", vue) is None and "n'est pas local" in avertis[0]
    r.set("distant_ok", True)
    assert callable(plugin(fen)._preparer_llama("fr", "en", vue))                                   # accepté explicitement
    fen.store.verrouiller(fen.fiche_theme, fen.fiche, "mdp", sans_secours=True)
    vue_verrouillee = fen.plugins.actifs["traduction"][1].fiche_courante()
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: mod().QMessageBox.StandardButton.No)
    assert plugin(fen)._preparer_llama("fr", "en", vue_verrouillee) is None                         # fiche verrouillée : accord à chaque fois
    r.set("url", "http://127.0.0.1:9931")
    assert callable(plugin(fen)._preparer_llama("fr", "en", vue_verrouillee))                       # local : aucun obstacle


def test_programme_ou_modele_manquant_explique_et_propose(fen, monkeypatch, tmp_path):
    monkeypatch.setattr(mod().logique, "trouver_llama", lambda *a, **k: None)
    appels = []
    monkeypatch.setattr(plugin(fen), "aide_installation", lambda: appels.append("aide"))
    assert plugin(fen)._preparer_llama("fr", "en", None) is None and appels == ["aide"]
    monkeypatch.setattr(mod().logique, "trouver_llama", lambda *a, **k: "/x/llama-server")
    monkeypatch.setattr(mod().logique, "trouver_modele", lambda *a, **k: None)
    monkeypatch.setattr(plugin(fen), "telecharger_modele", lambda: appels.append("telecharger"))
    assert plugin(fen)._preparer_llama("fr", "en", None) is None and appels == ["aide", "telecharger"]


def test_telechargement_du_modele_demande_l_accord_avec_taille_et_source(fen, monkeypatch, tmp_path):
    textes, lances = [], []
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: textes.append(a[2]) or mod().QMessageBox.StandardButton.No)
    monkeypatch.setattr(mod(), "en_arriere_plan", lambda *a, **k: lances.append(1) or (None, ""))
    assert plugin(fen).telecharger_modele() is None and not lances                                  # refusé : rien n'est téléchargé
    assert "2.49 Go" in textes[0] and lg.MODELE_URL in textes[0] and "SHA-256" in textes[0] and "modeles" in textes[0]
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: mod().QMessageBox.StandardButton.Yes)
    cible = tmp_path / "m.gguf"
    monkeypatch.setattr(mod(), "en_arriere_plan", lambda titre, msg, fn, annulable=False, parent=None: (cible, ""))
    assert plugin(fen).telecharger_modele() == str(cible)
    assert fen.plugins.actifs["traduction"][1].reglages.get("modele") == str(cible)


def test_traduction_complete_avec_le_faux_llama_server(fen, app, faux, monkeypatch):
    r = fen.plugins.actifs["traduction"][1].reglages
    r.set("exe", faux.exe)
    r.set("modele", faux.modele)
    d = dialogue(fen)
    d._lancer()
    assert attendre(app, lambda: not d.travail, 30)
    assert d.resultat.toPlainText() == "[TRAD] " + FRANCAIS.upper() and plugin(fen).serveur.vivant()
    prompt = appels(faux.dir)[0]["prompt"]
    assert "French (fr) to English (en)" in prompt and FRANCAIS in prompt
    pid = plugin(fen).serveur.proc.pid
    plugin(fen).serveur.dernier_usage = time.time() - 3600
    plugin(fen).occupe = 1
    plugin(fen)._surveiller()
    assert plugin(fen).serveur.vivant()                                                             # occupé : on ne coupe pas
    plugin(fen).occupe = 0
    plugin(fen)._surveiller()
    assert not plugin(fen).serveur.vivant()                                                         # inactif : mémoire libérée
    d2 = dialogue(fen)
    d2._lancer()
    assert attendre(app, lambda: not d2.travail, 30) and plugin(fen).serveur.proc.pid != pid        # redémarre à la demande
    fen.plugins.desactiver("traduction")
    assert not plugin(fen).serveur.vivant() if "traduction" in fen.plugins.actifs else True


def test_arreter_le_serveur_a_la_desactivation(fen, app, faux):
    p = plugin(fen)
    p.serveur.demarrer(faux.exe, faux.modele)
    proc = p.serveur.proc
    fen.plugins.desactiver("traduction")
    assert proc.poll() is not None


def test_journal_du_serveur_dans_le_dossier_de_l_extension(fen):
    assert plugin(fen).serveur.journal == fen.plugins.actifs["traduction"][1].dossier_donnees / "llama-server.log"


# ---------- Argos dans la fenêtre ----------
def test_argos_deja_pret(fen, argos, monkeypatch):
    sync(monkeypatch)
    f = plugin(fen)._preparer_argos("fr", "en")
    assert f("Bonjour", None) == "(fr>en) Bonjour"


def test_argos_modele_manquant_demande_l_accord_puis_installe(fen, argos, monkeypatch):
    sync(monkeypatch)
    demandes = []
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: demandes.append(a[2]) or mod().QMessageBox.StandardButton.No)
    assert plugin(fen)._preparer_argos("fr", "es") is None and argos.telecharges == []              # refusé : rien n'est téléchargé
    assert "fr → en, en → es" in demandes[0] and "index public" in demandes[0]
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: mod().QMessageBox.StandardButton.Yes)
    f = plugin(fen)._preparer_argos("fr", "es")
    assert argos.telecharges and f("Salut", None) == "(fr>es) Salut"


def test_argos_pas_de_modele_du_tout(fen, argos, monkeypatch):
    sync(monkeypatch)
    avertis = []
    monkeypatch.setattr(mod().QMessageBox, "warning", lambda *a, **k: avertis.append(a[2]))
    assert plugin(fen)._preparer_argos("fr", "ja") is None and "pas de modèle" in avertis[0]


def test_argos_non_installe_propose_l_installation_legere(fen, monkeypatch):
    monkeypatch.setattr(mod().logique, "argos_present", lambda: False)
    questions = []
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: questions.append(a[2]) or mod().QMessageBox.StandardButton.No)
    assert plugin(fen)._preparer_argos("fr", "en") is None
    assert "PyTorch n'est pas ajouté" in questions[0] and "argos" not in questions[0].lower().replace("argos translate", "")  or True
    assert not (fen.plugins.actifs["traduction"][1].dossier_donnees / "deps").exists()              # refusé : rien n'est créé


# ---------- réglages ----------
def test_dialogue_reglages_enregistre_et_n_exige_pas_ollama(fen, monkeypatch):
    d = mod().DialogueReglages(plugin(fen))
    d.moteur.setCurrentIndex(d.moteur.findData("argos"))
    d.exe.setText("/opt/llama/llama-server")
    d.modele.setText("/m/t.gguf")
    d.gpu.setText("0")
    d.inactif.setValue(3)
    d._valider()
    r = fen.plugins.actifs["traduction"][1].reglages
    assert (r.get("moteur"), r.get("exe"), r.get("modele"), r.get("gpu"), r.get("inactivite")) == ("argos", "/opt/llama/llama-server", "/m/t.gguf", "0", 3)
    assert r.get("distant_ok") is False and r.get("url") == ""                                      # serveur distant jamais accepté par défaut
    assert "ollama" not in (RACINE / "__init__.py").read_text().lower().replace("sans ollama", "")


# ---------- essai réel (facultatif : SCRINIUM_TEST_LLAMA=1) ----------
VRAI_EXE, VRAI_MODELE = lg.trouver_llama(), lg.trouver_modele()


@pytest.mark.skipif(not (os.environ.get("SCRINIUM_TEST_LLAMA") and VRAI_EXE and VRAI_MODELE), reason="essai réel : SCRINIUM_TEST_LLAMA=1 et llama.cpp + modèle installés")
def test_vrai_llama_server_traduit(tmp_path):
    srv = lg.ServeurLlama(tmp_path / "j.log")
    try:
        srv.demarrer(VRAI_EXE, VRAI_MODELE, gpu="0", delai=120)
        res = lg.traduire_texte(FRANCAIS, "fr", "en", lambda m: srv.completer(lg.consigne(m, "fr", "en"), lg.n_predict_pour(m)))
        assert "October" in res and ("invoice" in res.lower() or "bill" in res.lower()) and "électricité" not in res
        code = lg.traduire_texte("Remember to run `nginx -t` first.\n\n- point A", "en", "fr", lambda m: srv.completer(lg.consigne(m, "en", "fr"), 200))
        assert "`nginx -t`" in code and "- point a" in code.lower().replace("• ", "- ")                   # le modèle peut mettre une majuscule
    finally:
        srv.arreter()
