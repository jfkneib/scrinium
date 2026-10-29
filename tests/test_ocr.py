# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension OCR : logique (avec le vrai Tesseract s'il est installé) et fonctionnement dans la fenêtre."""
import importlib.util
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "ocr"
_spec = importlib.util.spec_from_file_location("ocr_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)
TESSERACT = lg.trouver()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def png_texte(lignes):
    img = QImage(900, 60 + 60 * len(lignes), QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QColor("black"))
    p.setFont(QFont("DejaVu Sans", 22))
    for i, ligne in enumerate(lignes):
        p.drawText(20, 60 + 60 * i, ligne)
    p.end()
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(b, "PNG")
    return bytes(ba.data())


# ---------- logique ----------
def test_nettoyer():
    assert lg.nettoyer("  a  \n\n\n\n b \x0c\n") == "a\n\n b"
    assert lg.nettoyer("x\n\n\n\n\ny") == "x\n\ny"
    assert len(lg.nettoyer("z" * (lg.TEXTE_MAX + 50))) == lg.TEXTE_MAX


def test_trouver(tmp_path, monkeypatch):
    faux = tmp_path / "tesseract"
    faux.write_text("#!/bin/sh\n")
    assert lg.trouver(str(faux)) == str(faux)                        # le réglage prime
    monkeypatch.setattr(lg.shutil, "which", lambda _n: None)
    monkeypatch.setattr(lg, "CHEMINS_USUELS", ())
    assert lg.trouver("") is None and lg.trouver("/inexistant") is None


def test_aide_installation_selon_le_systeme(monkeypatch):
    for plateforme, mot in (("linux", "apt install"), ("darwin", "brew"), ("win32", "Windows")):
        monkeypatch.setattr(lg.sys, "platform", plateforme)
        assert mot in lg.aide_installation()


@pytest.mark.skipif(not TESSERACT, reason="tesseract non installé")
def test_tesseract_lit_du_francais(app):
    png = png_texte(["Facture n° 2026-0148 — Électricité", "Réglée le 3 octobre à l'agence d'Évry."])
    if "fra" not in lg.langues(TESSERACT):
        pytest.skip("langue fra non installée")
    texte = lg.reconnaitre(TESSERACT, png, "fra")
    assert "Électricité" in texte and "Évry" in texte and "2026-0148" in texte
    assert lg.langues_manquantes(TESSERACT, "fra+zzz") == ["zzz"]
    with pytest.raises(RuntimeError):
        lg.reconnaitre(TESSERACT, png, "zzz")


# ---------- dans la fenêtre ----------
@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "ocr")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("ocr"), w.plugins.infos["ocr"].erreur
    w.nouvelle_fiche()
    w.titre.setText("Facture")
    w.sauver()
    monkeypatch.setattr(QApplication.instance(), "activeWindow", lambda: None)
    yield w
    w.quitter_vraiment = True
    w.close()


def attendre(app, condition, delai=8.0):
    fin = time.time() + delai
    while time.time() < fin and not condition():
        app.processEvents()
        time.sleep(0.01)
    return condition()


@pytest.fixture
def faux_moteur(monkeypatch):
    mod = sys.modules["scrinium_plugin_ocr.logique"]
    monkeypatch.setattr(mod, "trouver", lambda chemin="": "/faux/tesseract")
    monkeypatch.setattr(mod, "langues_manquantes", lambda exe, langue: [])
    monkeypatch.setattr(mod, "reconnaitre", lambda exe, donnees, langue="fra": f"texte lu ({langue}, {len(donnees)} octets)")
    return mod


def ajouter_image(fen):
    img = QImage(120, 80, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    fen.bande.ajouter([img])
    return fen.store.lister_pieces(fen.fiche)[-1]


def test_extraire_fiche_enregistre_le_texte(fen, app, faux_moteur):
    ajouter_image(fen)
    plugin = fen.plugins.actifs["ocr"][0]
    plugin.extraire_fiche()
    assert attendre(app, lambda: fen.store.lister_pieces(fen.fiche)[0].ocr != "")
    p = fen.store.lister_pieces(fen.fiche)[0]
    assert p.ocr.startswith("texte lu (fra") and p.ocr_moteur == "tesseract"
    fen.recherche.setText("texte lu")                                # cherchable
    assert any(f is fen.fiche for _t, f in fen.rows)


def test_option_automatique_a_l_ajout(fen, app, faux_moteur):
    ajouter_image(fen)
    assert fen.store.lister_pieces(fen.fiche)[0].ocr == ""           # désactivée par défaut
    fen.plugins.actifs["ocr"][1].reglages.set("auto", True)
    ajouter_image(fen)
    assert attendre(app, lambda: fen.store.lister_pieces(fen.fiche)[1].ocr != "")
    assert fen.store.lister_pieces(fen.fiche)[0].ocr == ""           # l'ancienne image n'est pas retraitée


def test_fiche_verrouillee_ouverte_texte_chiffre(fen, app, faux_moteur):
    fen.store.verrouiller(fen.fiche_theme, fen.fiche, "mdp", sans_secours=True)
    fen._afficher(fen.fiche_theme, fen.fiche)
    ajouter_image(fen)
    fen.plugins.actifs["ocr"][0].extraire_fiche()
    assert attendre(app, lambda: fen.store.lister_pieces(fen.fiche)[0].ocr != "")
    brut = b"".join(x.read_bytes() for x in fen.store.dossier_pj(fen.fiche).iterdir())
    assert b"texte lu" not in brut and b"tesseract" not in brut


def test_fiche_refermee_pendant_le_travail_n_ecrit_rien(fen, app, faux_moteur):
    fen.store.verrouiller(fen.fiche_theme, fen.fiche, "mdp", sans_secours=True)
    fen._afficher(fen.fiche_theme, fen.fiche)
    ajouter_image(fen)
    plugin = fen.plugins.actifs["ocr"][0]
    vue = fen.plugins.actifs["ocr"][1].fiche_courante()
    f = fen.fiche
    plugin.en_cours.add((vue.id, 1))
    f.texte = f.cle = f.salt = None                                  # refermée avant l'arrivée du résultat
    plugin._resultat(vue, 1, "ne doit pas être écrit", "")
    fen.store.deverrouiller(f, "mdp")
    assert fen.store.lister_pieces(f)[0].ocr == ""


def test_sans_tesseract_message_et_rien_ne_part(fen, app, monkeypatch):
    ajouter_image(fen)
    mod = sys.modules["scrinium_plugin_ocr.logique"]
    monkeypatch.setattr(mod, "trouver", lambda chemin="": None)
    avertis = []
    ocr = sys.modules["scrinium_plugin_ocr"]
    monkeypatch.setattr(ocr.QMessageBox, "warning", lambda *a, **k: avertis.append(a[2:]))
    fen.plugins.actifs["ocr"][0].extraire_fiche()
    assert avertis and any(m in avertis[0][0] for m in ("apt install", "brew", "Windows"))
    assert fen.store.lister_pieces(fen.fiche)[0].ocr == ""


def test_dialogue_correction_marque_manuel(fen, app, faux_moteur):
    p = ajouter_image(fen)
    ctx = fen.plugins.actifs["ocr"][1]
    plugin = fen.plugins.actifs["ocr"][0]
    ctx.maj_piece(ctx.fiche_courante(), p.id, ocr="Facture 12", ocr_moteur="tesseract")
    ocr = sys.modules["scrinium_plugin_ocr"]
    d = ocr.DialogueTextes(plugin, ctx.fiche_courante())
    assert d.texte.toPlainText() == "Facture 12"
    d.texte.setPlainText("Facture 123")
    d._enregistrer()
    q = fen.store.lister_pieces(fen.fiche)[0]
    assert q.ocr == "Facture 123" and q.ocr_moteur == "tesseract+manuel"


def test_clic_droit_sur_une_image_lance_l_ocr(fen, app, faux_moteur, monkeypatch):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu
    ajouter_image(fen)
    ajouter_image(fen)
    assert [e[1] for e in fen.actions_image] == ["Extraire le texte de l'image (OCR)"]
    fen.bande.liste.setCurrentRow(1)
    actions = {}
    monkeypatch.setattr(fen.bande.liste, "itemAt", lambda pos: fen.bande.liste.item(1))
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: actions.update({x.text(): x for x in self.actions() if x.text()}))
    fen.bande._menu(QPoint(1, 1))
    assert "Extraire le texte de l'image (OCR)" in actions
    actions["Extraire le texte de l'image (OCR)"].trigger()
    pieces = fen.store.lister_pieces(fen.fiche)
    assert attendre(app, lambda: fen.store.lister_pieces(fen.fiche)[1].ocr != "")
    pieces = fen.store.lister_pieces(fen.fiche)
    assert pieces[0].ocr == "" and pieces[1].ocr.startswith("texte lu")           # seulement l'image visée


def test_entree_retiree_a_la_desactivation(fen, app):
    assert fen.actions_image
    fen.plugins.desactiver("ocr")
    assert fen.actions_image == []
