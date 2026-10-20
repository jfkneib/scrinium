# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Traduction » : logique, faux llama-server, téléchargement du modèle, fonctionnement dans la fenêtre."""
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


# ---------- dans la fenêtre ----------
def _creer_fenetre(app, tmp_path, monkeypatch, choix="4b"):
    """Fenêtre avec l'extension activée. HOME factice : jamais les vrais llama.cpp ni modèles de la machine."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(lg.shutil, "which", lambda n: None)
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True, **({"plugins": {"traduction": {"modele_choix": choix}}} if choix else {}))
    shutil.copytree(RACINE, s.paths.base / "plugins" / "traduction")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("traduction"), w.plugins.infos["traduction"].erreur
    w.nouvelle_fiche()
    w.titre.setText("Notes")
    w.texte.setPlainText(FRANCAIS)
    w.sauver()
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    return w


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    w = _creer_fenetre(app, tmp_path, monkeypatch)
    yield w
    w.quitter_vraiment = True
    w.close()


@pytest.fixture
def fen_neuf(app, tmp_path, monkeypatch):
    """Première activation : aucun modèle choisi."""
    w = _creer_fenetre(app, tmp_path, monkeypatch, choix=None)
    yield w
    w.quitter_vraiment = True
    w.close()


def poser_modele(fen, choix="4b"):
    """Fichier de modèle factice à l'endroit où l'extension le cherche."""
    d = fen.plugins.actifs["traduction"][1].dossier_donnees / "modeles"
    d.mkdir(parents=True, exist_ok=True)
    (d / lg.MODELES[choix]["nom"]).write_bytes(b"GGUF")
    return d / lg.MODELES[choix]["nom"]


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
    monkeypatch.setattr(plugin(fen), "preparer", lambda moteur, src, dst, vue, choix=None: (lambda m, annule: f"[{src}>{dst}] {m.upper()}"))


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
    monkeypatch.setattr(plugin(fen), "telecharger_modele", lambda choix=None: appels.append(("telecharger", choix)))
    assert plugin(fen)._preparer_llama("fr", "en", None) is None and appels == ["aide", ("telecharger", "4b")]    # le modèle CHOISI, pas un autre
    assert plugin(fen)._preparer_llama("fr", "en", None, "12b") is None and appels[-1] == ("telecharger", "12b")


def test_telechargement_du_modele_demande_l_accord_avec_taille_et_source(fen, monkeypatch, tmp_path):
    textes, lances = [], []
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: textes.append(a[2]) or mod().QMessageBox.StandardButton.No)
    monkeypatch.setattr(mod(), "en_arriere_plan", lambda *a, **k: lances.append(1) or (None, ""))
    assert plugin(fen).telecharger_modele("12b") is None and not lances                            # refusé : rien n'est téléchargé
    assert "Meilleur (12B)" in textes[0] and "7.30 Go" in textes[0] and lg.MODELES["12b"]["url"] in textes[0] and "SHA-256" in textes[0]
    assert plugin(fen).telecharger_modele("4b") is None and "2.49 Go" in textes[1] and "Rapide (4B)" in textes[1]
    appel = {}
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: mod().QMessageBox.StandardButton.Yes)
    cible = tmp_path / "m.gguf"

    def fausse(titre, msg, fn, annulable=False, parent=None):
        appel["fn"] = fn
        return cible, ""
    monkeypatch.setattr(mod(), "en_arriere_plan", fausse)
    monkeypatch.setattr(mod().logique, "telecharger_modele", lambda dossier, url, nom, sha, taille, **k: appel.update(url=url, nom=nom, sha=sha, taille=taille) or cible)
    assert plugin(fen).telecharger_modele("12b") == str(cible)
    appel["fn"](threading.Event(), lambda *a: None)
    assert appel["nom"] == lg.MODELES["12b"]["nom"] and appel["taille"] == lg.MODELES["12b"]["taille"] and appel["sha"] == lg.MODELES["12b"]["sha256"]
    assert fen.plugins.actifs["traduction"][1].reglages.get("modele", "") == ""                     # le chemin n'est retenu que pour « fichier personnel »
    QMessageBox_info = []
    monkeypatch.setattr(mod().QMessageBox, "information", lambda *a, **k: QMessageBox_info.append(a[2]))
    assert plugin(fen).telecharger_modele("perso") is None and QMessageBox_info                     # rien à télécharger pour un fichier personnel


def test_traduction_complete_avec_le_faux_llama_server(fen, app, faux, monkeypatch):
    r = fen.plugins.actifs["traduction"][1].reglages
    r.set("exe", faux.exe)
    poser_modele(fen, "4b")
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


# ---------- réglages ----------
def test_dialogue_reglages_enregistre_et_n_exige_pas_ollama(fen, monkeypatch):
    d = mod().DialogueReglages(plugin(fen))
    assert d.choix.currentData() == "4b" and [d.choix.itemData(i) for i in range(d.choix.count())] == ["4b", "12b", "perso"]
    d.choix.setCurrentIndex(d.choix.findData("12b"))
    d.exe.setText("/opt/llama/llama-server")
    d.modele.setText("/m/t.gguf")
    d.gpu.setText("0")
    d.inactif.setValue(3)
    d._valider()
    r = fen.plugins.actifs["traduction"][1].reglages
    assert (r.get("modele_choix"), r.get("exe"), r.get("modele"), r.get("gpu"), r.get("inactivite")) == ("12b", "/opt/llama/llama-server", "/m/t.gguf", "0", 3)
    assert r.get("distant_ok") is False and r.get("url") == ""                                      # serveur distant jamais accepté par défaut
    assert "ollama" not in (RACINE / "__init__.py").read_text().lower().replace("sans ollama", "")


# ---------- Argos retiré (il exige PyTorch) ----------
def test_argos_n_est_plus_propose(fen, app, monkeypatch):
    assert list(mod().MOTEURS) == ["llama"]
    d = dialogue(fen)
    d.show()
    app.processEvents()
    assert d.moteur.count() == 1 and not d.moteur.isVisible()                                       # un seul moteur : pas de liste à montrer
    reglages = mod().DialogueReglages(plugin(fen))
    textes = [w.text() for w in reglages.findChildren((mod().QLabel, mod().QPushButton)) if hasattr(w, "text")]
    assert not any("argos" in x.lower() for x in textes)                                            # ni libellé ni bouton d'installation
    code = (RACINE / "__init__.py").read_text() + (RACINE / "logique.py").read_text()
    assert "QProcess" not in code and '"pip"' not in code and "argostranslate" not in code.lower().replace("(argos translate a été retiré", "")   # plus aucune installation de paquet


def test_ancien_reglage_argos_retombe_sur_llama(fen, app, faux):
    r = fen.plugins.actifs["traduction"][1].reglages
    r.set("moteur", "argos")                                                                        # réglage laissé par une ancienne version
    r.set("exe", faux.exe)
    poser_modele(fen, "4b")
    d = dialogue(fen)
    assert d.moteur.currentData() == "llama"
    d._lancer()
    assert attendre(app, lambda: not d.travail, 30) and d.resultat.toPlainText().startswith("[TRAD]")


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


# ---------- deux modèles : 4B rapide, 12B meilleur ----------
GO = 1024 ** 3


def test_modeles_epingles_et_telechargements_verifiables():
    assert list(lg.MODELES) == ["4b", "12b"]
    for cle, m in lg.MODELES.items():
        assert m["url"] == f"https://huggingface.co/mradermacher/translategemma-{cle}-it-GGUF/resolve/main/translategemma-{cle}-it.Q4_K_M.gguf"
        assert m["nom"] == f"translategemma-{cle}-it.Q4_K_M.gguf" and len(m["sha256"]) == 64 and m["taille"] > 1_000_000_000
    assert lg.MODELES["4b"]["taille"] == 2_489_909_760 and lg.MODELES["12b"]["taille"] == 7_300_794_112
    assert lg.MODELES["12b"]["sha256"].startswith("b7aac4b4be7ab0c4")


def test_trouver_modele_par_choix(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "vide"))
    donnees = tmp_path / "d"
    (donnees / "modeles").mkdir(parents=True)
    perso = tmp_path / "mon.gguf"
    perso.write_bytes(b"x")
    assert lg.trouver_modele("", donnees, "4b") is None and lg.trouver_modele(str(perso), donnees, "perso") == str(perso)
    (donnees / "modeles" / lg.MODELES["12b"]["nom"]).write_bytes(b"x")
    assert lg.trouver_modele("", donnees, "12b").endswith("12b-it.Q4_K_M.gguf") and lg.trouver_modele("", donnees, "4b") is None
    assert lg.trouver_modele(str(perso), donnees, "12b").endswith("12b-it.Q4_K_M.gguf")               # un chemin ne remplace pas un modèle choisi
    assert lg.trouver_modele("/inexistant", donnees, "perso") is None and lg.trouver_modele("", donnees, "inconnu") is None


def test_choix_automatique_seulement_quand_c_est_evident():
    carte = lambda go: {"memoire": 32 * GO, "coeurs": 8, "gpus": [{"nom": "X", "total": go * GO, "libre": go * GO}], "apple": False}
    assert lg.choix_automatique(carte(24)) == "12b" and lg.choix_automatique(carte(12)) == "12b"
    assert lg.choix_automatique(carte(8)) is None and lg.choix_automatique(carte(6)) is None            # 8 Go : le 12B n'y tient pas, on demande
    assert lg.choix_automatique({"memoire": 125 * GO, "coeurs": 16, "gpus": [], "apple": False}) is None   # beaucoup de mémoire mais pas de carte
    assert lg.choix_automatique({"memoire": 16 * GO, "coeurs": 8, "gpus": [], "apple": True}) == "12b"      # Apple Silicon : mémoire partagée
    assert lg.choix_automatique({"memoire": 8 * GO, "coeurs": 8, "gpus": [], "apple": True}) is None
    assert lg.recommandation(carte(24)) == "12b" and lg.recommandation(carte(8)) == "4b"


def test_description_du_materiel():
    m = {"memoire": 125 * GO, "coeurs": 16, "gpus": [{"nom": "NVIDIA GeForce RTX 3070", "total": 8 * GO, "libre": 7 * GO}], "apple": False}
    assert lg.description_materiel(m) == "mémoire 125 Go, 16 cœurs, NVIDIA GeForce RTX 3070 (8 Go)"
    assert "pas de carte NVIDIA détectée" in lg.description_materiel({"memoire": None, "coeurs": None, "gpus": [], "apple": False})
    assert "Apple Silicon" in lg.description_materiel({"memoire": 16 * GO, "coeurs": 8, "gpus": [], "apple": True})


def test_detection_des_cartes_nvidia(tmp_path, monkeypatch):
    smi = tmp_path / "nvidia-smi"
    smi.write_text('#!/bin/sh\necho "NVIDIA GeForce RTX 3070, 8192, 6785"\necho "NVIDIA Tesla T4, 15360, 15000"\necho "ligne illisible"\n')
    smi.chmod(smi.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(lg.shutil, "which", lambda n: str(smi))
    cartes = lg.gpus_nvidia()
    assert [(c["nom"], c["total"] // 1024 ** 2, c["libre"] // 1024 ** 2) for c in cartes] == [("NVIDIA GeForce RTX 3070", 8192, 6785), ("NVIDIA Tesla T4", 15360, 15000)]
    smi.write_text("#!/bin/sh\nexit 1\n")
    assert lg.gpus_nvidia() == []
    monkeypatch.setattr(lg.shutil, "which", lambda n: None)
    assert lg.gpus_nvidia() == [] and (lg.memoire_totale() or 1) > 0


# ---------- l'assistant de choix ----------
def fausse_machine(monkeypatch, go_carte=None, apple=False, ram=32):
    gpus = [{"nom": "NVIDIA Test", "total": go_carte * GO, "libre": go_carte * GO}] if go_carte else []
    monkeypatch.setattr(mod().logique, "materiel", lambda: {"memoire": ram * GO, "coeurs": 8, "gpus": gpus, "apple": apple})


def test_premiere_activation_propose_le_choix_du_modele(fen_neuf, app, monkeypatch):
    vus = []
    monkeypatch.setattr(mod().DialogueChoixModele, "exec", lambda self: vus.append(self) or 0)
    assert plugin(fen_neuf).modele_choisi() is None
    assert attendre(app, lambda: bool(vus), 3)                                                       # une demi-seconde après l'activation
    assert len(vus) == 1 and plugin(fen_neuf).modele_choisi() is None                               # « Plus tard » : rien n'est enregistré


def test_pas_de_question_si_un_choix_existe_deja(fen, app, monkeypatch):
    vus = []
    monkeypatch.setattr(mod().DialogueChoixModele, "exec", lambda self: vus.append(1) or 0)
    time.sleep(0.7)
    app.processEvents()
    assert vus == [] and plugin(fen).modele_choisi() == "4b"


def test_dialogue_de_choix_montre_avantages_inconvenients_et_conseil(fen, monkeypatch):
    fausse_machine(monkeypatch, go_carte=8)
    poser_modele(fen, "4b")
    d = mod().DialogueChoixModele(plugin(fen))
    assert list(d.radios) == ["4b", "12b", "perso"] and d.choix() == "4b"
    assert "déjà téléchargé" in d.radios["4b"].text() and "conseillé ici" in d.radios["4b"].text()    # 8 Go de carte : conseil = rapide
    assert "7.30 Go" in d.radios["12b"].text() and "à télécharger" in d.radios["12b"].text() and "conseillé" not in d.radios["12b"].text()
    textes = " ".join(x.text() for x in d.findChildren(mod().QLabel))
    for attendu in ("RTX", "NVIDIA Test", "Conseil : Rapide (4B)", "Nettement plus fidèle", "Beaucoup plus lent", "se trompe sur les nuances",
                    "Déconseillé sur une machine modeste", "rien n'est envoyé sur Internet"):
        assert attendu in textes or attendu == "RTX"
    assert textes.count("✔") >= 4 and textes.count("✘") >= 4                                          # avantages ET inconvénients, pour chaque choix


def test_dialogue_conseille_le_12b_sur_une_grosse_carte(fen_neuf, monkeypatch):
    fausse_machine(monkeypatch, go_carte=24)
    d = mod().DialogueChoixModele(plugin(fen_neuf))                                                 # aucun choix encore : le conseil est présélectionné
    assert d.choix() == "12b" and "conseillé ici" in d.radios["12b"].text()
    assert "Conseil : Meilleur (12B)" in " ".join(x.text() for x in d.findChildren(mod().QLabel))


def test_dialogue_garde_le_choix_existant_meme_si_le_conseil_differe(fen, monkeypatch):
    fausse_machine(monkeypatch, go_carte=24)
    d = mod().DialogueChoixModele(plugin(fen))                                                      # un choix existe (4B) : on le garde présélectionné
    assert d.choix() == "4b" and "conseillé ici" in d.radios["12b"].text()


def test_fichier_personnel_demande_le_fichier(fen, monkeypatch, tmp_path):
    fausse_machine(monkeypatch)
    d = mod().DialogueChoixModele(plugin(fen))
    d.radios["perso"].setChecked(True)
    monkeypatch.setattr(mod().QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    d._valider()
    assert d.result() == 0 and d.chemin == ""                                                       # pas de fichier : on ne valide pas
    perso = tmp_path / "p.gguf"
    monkeypatch.setattr(mod().QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(perso), "")))
    d._valider()
    assert d.chemin == str(perso) and d.result() == 1


def test_assistant_enregistre_le_choix_et_propose_le_telechargement(fen, monkeypatch):
    fausse_machine(monkeypatch, go_carte=8)
    appels = []

    class Faux:
        def __init__(self, plugin, parent=None):
            pass

        def exec(self):
            return 1

        def choix(self):
            return "12b"
        chemin = ""
    monkeypatch.setattr(mod(), "DialogueChoixModele", Faux)
    monkeypatch.setattr(plugin(fen), "telecharger_modele", lambda choix=None: appels.append(choix) or None)
    assert plugin(fen).assistant_modele(force=True) is False and appels == ["12b"]                  # le modèle manque : téléchargement proposé (et refusé ici)
    r = fen.plugins.actifs["traduction"][1].reglages
    assert r.get("modele_choix") == "12b" and plugin(fen).modele_choisi() == "12b"
    poser_modele(fen, "12b")
    assert plugin(fen).assistant_modele(force=True) and appels == ["12b"]                           # déjà là : aucun téléchargement


def test_choix_evident_sur_une_grosse_carte_pas_de_question(fen_neuf, monkeypatch):
    fausse_machine(monkeypatch, go_carte=24)
    appels = []
    monkeypatch.setattr(plugin(fen_neuf), "telecharger_modele", lambda choix=None: appels.append(choix) or None)
    monkeypatch.setattr(mod().DialogueChoixModele, "exec", lambda self: pytest.fail("la question ne doit pas être posée"))
    plugin(fen_neuf).assistant_modele()
    assert plugin(fen_neuf).modele_choisi() == "12b" and appels == ["12b"]                          # choisi tout seul, téléchargement avec accord
    assert "choisi pour cette machine" in fen_neuf.statusBar().currentMessage() and "Meilleur (12B)" in fen_neuf.statusBar().currentMessage()
    monkeypatch.setattr(mod().DialogueChoixModele, "exec", lambda self: 0)
    assert plugin(fen_neuf).assistant_modele(force=True) is False                                   # « Choisir » depuis les réglages : la question est posée


def test_preparer_sans_choix_pose_la_question(fen_neuf, monkeypatch):
    fausse_machine(monkeypatch, go_carte=8)
    fen_neuf.plugins.actifs["traduction"][1].reglages.set("exe", "/x/llama-server")
    monkeypatch.setattr(mod().logique, "trouver_llama", lambda *a, **k: "/x/llama-server")
    vus = []
    monkeypatch.setattr(mod().DialogueChoixModele, "exec", lambda self: vus.append(1) or 0)
    assert plugin(fen_neuf)._preparer_llama("fr", "en", None) is None and len(vus) == 1             # pas de choix : on demande, « plus tard » : rien ne part


def test_ancienne_configuration_avec_un_chemin_devient_fichier_personnel(fen_neuf, tmp_path):
    gguf = tmp_path / "ancien.gguf"
    gguf.write_bytes(b"x")
    r = fen_neuf.plugins.actifs["traduction"][1].reglages
    r.set("modele", str(gguf))
    assert plugin(fen_neuf).modele_choisi() == "perso" and r.get("modele_choix") == "perso"
    r.set("modele_choix", "")
    r.set("modele", "/n'existe/pas.gguf")
    assert plugin(fen_neuf).modele_choisi() is None


def test_choix_rapide_du_modele_dans_la_fenetre_de_traduction(fen, app, faux):
    r = fen.plugins.actifs["traduction"][1].reglages
    r.set("exe", faux.exe)
    poser_modele(fen, "4b")
    poser_modele(fen, "12b")
    d = dialogue(fen)
    assert [d.qualite.itemData(i) for i in range(d.qualite.count())] == ["4b", "12b"] and d.qualite.currentData() == "4b"
    traduire(app, d)
    argv = [json.loads(p.read_text())["argv"] for p in sorted(faux.dir.glob("argv-*.json"), key=lambda p: p.stat().st_mtime)]
    assert argv[-1][argv[-1].index("-m") + 1].endswith("translategemma-4b-it.Q4_K_M.gguf")
    d.qualite.setCurrentIndex(d.qualite.findData("12b"))                                             # même fenêtre : on passe au meilleur modèle
    traduire(app, d)
    argv = [json.loads(p.read_text())["argv"] for p in sorted(faux.dir.glob("argv-*.json"), key=lambda p: p.stat().st_mtime)]
    assert argv[-1][argv[-1].index("-m") + 1].endswith("translategemma-12b-it.Q4_K_M.gguf") and len(argv) == 2    # le serveur a redémarré avec l'autre fichier
    assert d.resultat.toPlainText().startswith("[TRAD]")
    r.set("modele_choix", "12b")
    assert dialogue(fen).qualite.currentData() == "12b"                                              # le choix par défaut vient des réglages


def test_choix_perso_apparait_dans_la_fenetre(fen, tmp_path):
    gguf = tmp_path / "p.gguf"
    gguf.write_bytes(b"x")
    r = fen.plugins.actifs["traduction"][1].reglages
    r.set("modele_choix", "perso")
    r.set("modele", str(gguf))
    d = dialogue(fen)
    assert [d.qualite.itemData(i) for i in range(d.qualite.count())] == ["4b", "12b", "perso"] and d.qualite.currentData() == "perso"


# ---------- machines modestes : mises en garde ----------
def test_avertissements_selon_la_memoire():
    machine = lambda go, carte=0: {"memoire": go * GO, "coeurs": 4, "apple": False,
                                   "gpus": [{"nom": "X", "total": carte * GO, "libre": carte * GO}] if carte else []}
    assert "7 Go" in lg.avertissement_modele(machine(7), "12b") and "saturer" in lg.avertissement_modele(machine(7), "12b")
    assert lg.avertissement_modele(machine(7), "4b") == "" and lg.avertissement_modele(machine(15), "12b") == ""       # le 4B passe sur 7 Go (mesuré), le 12B passe sur 15 Go
    assert "même le modèle rapide" in lg.avertissement_modele(machine(4), "4b")
    assert lg.avertissement_modele(machine(7, carte=12), "12b") == "" and lg.avertissement_modele(machine(7, carte=8), "12b") == ""   # une carte de 8 Go compense
    assert lg.avertissement_modele({"memoire": None, "coeurs": 4, "gpus": [], "apple": False}, "12b") == ""             # mémoire inconnue : pas d'alarme


def test_dialogue_signale_une_machine_trop_juste_et_demande_confirmation(fen, monkeypatch):
    monkeypatch.setattr(mod().logique, "materiel", lambda: {"memoire": 7 * GO, "coeurs": 4, "gpus": [], "apple": False})   # type OptiPlex
    d = mod().DialogueChoixModele(plugin(fen))
    assert "⚠" in d.radios["12b"].text() and "⚠" not in d.radios["4b"].text()
    assert "saturer" in d.alertes["12b"] and d.alertes["4b"] == ""
    textes = " ".join(x.text() for x in d.findChildren(mod().QLabel))
    assert "n'a que 7 Go de mémoire" in textes and "i5 de 2012" in textes                           # mise en garde visible + mesure sur vieille machine
    d.radios["12b"].setChecked(True)
    questions = []
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: questions.append(a[2]) or mod().QMessageBox.StandardButton.No)
    d._valider()
    assert d.result() == 0 and "Choisir quand même ?" in questions[0]                                # refusé : la fenêtre reste ouverte
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: mod().QMessageBox.StandardButton.Yes)
    d._valider()
    assert d.result() == 1 and d.choix() == "12b"                                                    # choisi en connaissance de cause
    d4 = mod().DialogueChoixModele(plugin(fen))
    d4.radios["4b"].setChecked(True)
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: pytest.fail("pas de question pour le 4B sur 7 Go"))
    d4._valider()
    assert d4.result() == 1
