# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Lecture à voix haute » : texte lu, voix, processus (faux moteurs, aucun son réel), téléchargement vérifié, file de lecture."""
import hashlib
import importlib.util
import io
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "lecture"
_spec = importlib.util.spec_from_file_location("lecture_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)


# ---------- texte ----------
def test_nettoyer_markdown():
    t = "<!-- scrinium: {\"a\": 1} -->\n# Titre\n\n- un **gras** et *italique*\n1. `code` et [lien](https://x.fr)\n> citation\n" \
        "```\nrm -rf /\n```\nvoir https://exemple.fr/a?b=1 et <https://y.fr> fin\n![schéma](a.png)"
    r = lg.nettoyer(t)
    assert "scrinium" not in r and "rm -rf" not in r and "http" not in r and "#" not in r and "**" not in r and "`" not in r
    assert "Titre" in r and "un gras et italique" in r and "code et lien" in r and "citation" in r and "schéma" in r


def test_phrases_decoupe_et_filtre():
    assert lg.phrases("Bonjour. Comment allez-vous ? Très bien !") == ["Bonjour.", "Comment allez-vous ?", "Très bien !"]
    assert lg.phrases("\n\n---\n***\n") == []                              # rien de prononçable
    longue = ", ".join(["un mot de plus"] * 80)
    morceaux = lg.phrases(longue)
    assert len(morceaux) > 1 and all(len(m) <= lg.LIGNE_MAX for m in morceaux) and " ".join(morceaux).count("un mot de plus") == 80
    assert lg.phrases("a" * 1000) and all(len(m) <= lg.LIGNE_MAX for m in lg.phrases("a" * 1000))


def test_detecter_langue():
    fr = "Le chat est dans la maison et il dort sur le canapé avec les enfants qui ne sont pas là."
    en = "The cat is in the house and it sleeps on the couch with the children who are not there."
    assert lg.detecter_langue(fr) == "fr" and lg.detecter_langue(en) == "en"
    assert lg.detecter_langue("ls -la") is None and lg.detecter_langue("") is None
    assert lg.langue_de_lecture(en, "fr") == "fr" and lg.langue_de_lecture(en, "auto") == "en"
    assert lg.langue_de_lecture("ls", "auto") in ("fr", "en")


def test_catalogue_de_voix_coherent():
    for cle, v in lg.VOIX.items():
        assert cle.startswith(v["langue"] + "_") and len(v["sha256"]) == 64 and len(v["sha256_json"]) == 64
        assert v["taille"] > 1_000_000 and v["taille_json"] > 0 and v["dossier"].endswith("/medium")
    assert all(lg.VOIX[c]["langue"] == lang for lang, c in lg.VOIX_DEFAUT.items())
    assert lg.vitesse_valide(99) == lg.VITESSE_MAX and lg.vitesse_valide("x") == 1.0 and lg.vitesse_valide(0) == lg.VITESSE_MIN


def test_commandes(tmp_path):
    argv, env = lg.commande_piper(tmp_path / "deps", tmp_path / "m", "fr_FR-siwis-medium", 1.25)
    assert argv[1:3] == ["-m", "piper"] and "--output-raw" in argv and argv[argv.index("--length-scale") + 1] == "0.800"
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "deps") and "PYTHONHOME" not in env
    e = lg.commande_espeak("/usr/bin/espeak-ng", "en", 1.0)
    assert e == ["/usr/bin/espeak-ng", "-v", "en-gb", "-s", "165", "--stdin"]


# ---------- faux moteurs ----------
@pytest.fixture
def faux(tmp_path, monkeypatch):
    """Dossier PATH avec de faux « espeak-ng » et « paplay » ; ils écrivent ce qu'ils reçoivent dans le dossier."""
    d = tmp_path / "faux"
    bin_ = d / "bin"
    bin_.mkdir(parents=True)
    (bin_ / "espeak-ng").write_text('#!/bin/sh\necho "$@" > "$FAUX/args"\ncat > "$FAUX/dit"\n[ -f "$FAUX/long" ] && sleep 30\nexit 0\n')
    (bin_ / "paplay").write_text('#!/bin/sh\ncat > "$FAUX/audio"\n')
    for f in bin_.iterdir():
        f.chmod(0o755)
    monkeypatch.setenv("FAUX", str(d))
    monkeypatch.setenv("PATH", str(bin_) + os.pathsep + os.environ["PATH"])
    return d


def attendre(cond, delai=5.0):
    fin = time.time() + delai
    while time.time() < fin:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_lecture_espeak_recoit_le_texte_et_se_termine(faux):
    lec = lg.demarrer_espeak(lg.espeak(), "fr", ["Première phrase.", "Seconde phrase."], 1.0)
    assert attendre(lec.terminee) and lec.erreur() == ""
    assert (faux / "dit").read_text() == "Première phrase.\nSeconde phrase.\n"
    assert "-v fr" in (faux / "args").read_text()


def etat(pid):
    return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[0]


def test_pause_reprise_arret(faux):
    (faux / "long").write_text("")
    lec = lg.demarrer_espeak(lg.espeak(), "fr", ["Longue lecture."], 1.0)
    assert attendre(lambda: (faux / "dit").exists())
    pid = lec.procs[0].pid
    lec.pause()
    assert attendre(lambda: etat(pid) == "T") and lec.en_pause and not lec.terminee()
    lec.reprendre()
    assert attendre(lambda: etat(pid) != "T") and not lec.en_pause
    lec.arreter()
    assert lec.terminee() and lec.procs[0].returncode is not None


def test_pipeline_piper_vers_lecteur_audio(faux, tmp_path):
    deps = tmp_path / "deps"
    (deps / "piper").mkdir(parents=True)
    (deps / "piper" / "__init__.py").write_text("")
    (deps / "piper" / "__main__.py").write_text(
        "import sys\nfor l in sys.stdin:\n    sys.stdout.buffer.write(b'\\x01\\x00' * 50)\n    sys.stdout.buffer.flush()\n")
    assert lg.piper_present(deps)
    lec = lg.demarrer_piper(deps, tmp_path / "m", "fr_FR-siwis-medium", ["Un.", "Deux.", "Trois."], 1.0)
    assert attendre(lec.terminee) and lec.erreur() == ""
    assert (faux / "audio").stat().st_size == 3 * 100                      # une salve de PCM par ligne


def test_erreur_du_moteur_remontee(faux, tmp_path):
    deps = tmp_path / "deps"
    (deps / "piper").mkdir(parents=True)
    (deps / "piper" / "__init__.py").write_text("")
    (deps / "piper" / "__main__.py").write_text("import sys\nsys.stderr.write('voix introuvable\\n')\nsys.exit(3)\n")
    lec = lg.demarrer_piper(deps, tmp_path / "m", "fr_FR-siwis-medium", ["Un."], 1.0)
    assert attendre(lambda: lec.procs[0].poll() is not None and lec.terminee())
    assert attendre(lambda: "voix introuvable" in lec.erreur())


def test_sans_lecteur_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(lg.shutil, "which", lambda n: None)
    with pytest.raises(OSError):
        lg.demarrer_piper(tmp_path, tmp_path, "fr_FR-siwis-medium", ["x"])
    assert lg.espeak() is None


# ---------- téléchargement vérifié ----------
class Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_telechargement_verifie(tmp_path, monkeypatch):
    contenu = b"x" * 3_000_000
    monkeypatch.setattr(lg.urllib.request, "urlopen", lambda url, timeout=0: Reponse(contenu))
    dest = tmp_path / "v" / "voix.onnx"
    vus = []
    lg.telecharger("https://exemple.fr/v.onnx", dest, hashlib.sha256(contenu).hexdigest(), len(contenu), lambda f, t: vus.append(f))
    assert dest.read_bytes() == contenu and vus[-1] == len(contenu) and not dest.with_name("voix.onnx.part").exists()
    mauvais = tmp_path / "v" / "autre.onnx"
    with pytest.raises(ValueError):
        lg.telecharger("https://exemple.fr/v.onnx", mauvais, "0" * 64, len(contenu))
    assert not mauvais.exists() and not mauvais.with_name("autre.onnx.part").exists()           # rien d'incorrect ne reste
    with pytest.raises(ValueError):
        lg.telecharger("http://exemple.fr/v.onnx", mauvais, "0" * 64, 1)                         # jamais en clair
    with pytest.raises(lg.Annule):
        lg.telecharger("https://exemple.fr/v.onnx", mauvais, "0" * 64, len(contenu), annule=lambda: True)
    assert not mauvais.with_name("autre.onnx.part").exists()


def test_voix_presente_exige_la_bonne_taille(tmp_path):
    cle = "fr_FR-siwis-medium"
    onnx, cfg = lg.fichiers_voix(tmp_path, cle)
    assert not lg.voix_presente(tmp_path, cle)
    onnx.write_bytes(b"court")
    cfg.write_text("{}")
    assert not lg.voix_presente(tmp_path, cle)                              # fichier tronqué : pas « présente »


# ---------- dans la fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FausseLecture:
    def __init__(self, texte):
        self.texte, self.fini, self.en_pause, self.arretee = texte, False, False, False

    def terminee(self):
        return self.fini

    def erreur(self):
        return ""

    def pause(self):
        self.en_pause = True

    def reprendre(self):
        self.en_pause = False

    def arreter(self):
        self.arretee = True


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "lecture")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("lecture"), w.plugins.infos["lecture"].erreur
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    yield w
    w.quitter_vraiment = True
    w.close()


def plugin(fen):
    return fen.plugins.actifs["lecture"][0]


@pytest.fixture
def moteur(fen, monkeypatch):
    """Faux espeak-ng : enregistre les lectures démarrées ; Piper jamais proposé."""
    m = sys.modules["scrinium_plugin_lecture"].logique
    demarrees = []
    monkeypatch.setattr(m, "espeak", lambda: "/usr/bin/espeak-ng")
    monkeypatch.setattr(m, "demarrer_espeak", lambda exe, lang, lignes, vitesse=1.0: demarrees.append((lang, lignes)) or
                        FausseLecture(" ".join(lignes)))
    plugin(fen).ctx.reglages.set("moteur", "espeak")
    notes = []
    plugin(fen).ctx.ui.notifier = lambda t, msg: notes.append(msg)
    return demarrees, notes


def nouvelle(fen, titre, texte):
    fen.nouvelle_fiche()
    fen.titre.setText(titre)
    fen.texte.setPlainText(texte)
    fen.sauver()


FR = "Le chat est dans la maison et il dort sur le canapé avec les enfants qui ne sont pas là."


def test_lire_la_fiche_affichee(fen, moteur):
    demarrees, _n = moteur
    nouvelle(fen, "Chat", FR)
    p = plugin(fen)
    p.lire_fiche()
    assert demarrees and demarrees[0][0] == "fr" and p.fenetre is not None and "Chat" in p.fenetre.titre.text()
    p.lecture.fini = True
    p._tic()                                     # fin de la seule fiche : tout se ferme
    assert p.fenetre is None and p.lecture is None


def test_langue_detectee_ou_imposee(fen, moteur):
    demarrees, _n = moteur
    p = plugin(fen)
    en = "The cat is in the house and it sleeps on the couch with the children who are not there."
    p.lire([("A", en)])
    assert demarrees[-1][0] == "en"
    p.ctx.reglages.set("langue", "fr")
    p.lire([("A", en)])
    assert demarrees[-1][0] == "fr"


def test_fiche_verrouillee_jamais_lue(fen, moteur):
    demarrees, notes = moteur
    demo = next(f for t in fen.store.themes for f in t.fiches if f.verrou)
    th = next(t for t in fen.store.themes if demo in t.fiches)
    fen.store.deverrouiller(demo, "scrinium")
    fen._afficher(th, demo)                       # verrouillée mais OUVERTE : toujours refusée
    p = plugin(fen)
    p.lire_fiche()
    fen.texte.selectAll()
    p.lire_selection()
    assert demarrees == [] and p.fenetre is None and all("verrouillée" in n for n in notes) and len(notes) == 2


def test_theme_entier_saute_les_verrouillees(fen, moteur):
    demarrees, notes = moteur
    th = next(t for t in fen.store.themes if any(f.verrou for f in t.fiches))
    fen.theme = th.nom
    for i in range(2):
        nouvelle(fen, f"Lisible {i}", FR + f" Numéro {i}.")
    p = plugin(fen)
    elements, verrouillees = p.elements_theme(th.nom)
    titres = [t for t, _x in elements]
    assert verrouillees >= 1 and "Lisible 0" in titres and "Lisible 1" in titres
    assert all(not f.verrou for f in th.fiches if f.titre in titres)
    p.lire_un_theme(th.nom)
    assert len(demarrees) == 1 and p.fenetre is not None
    suite = 1
    while p.lecture is not None:                  # on enchaîne toutes les fiches de la file
        p.lecture.fini = True
        p._tic()
        suite += 1
        assert suite < 50
    assert len(demarrees) == len(elements) and p.fenetre is None
    verrouillees_titres = {f.titre for f in th.fiches if f.verrou}
    assert verrouillees_titres and not verrouillees_titres & set(titres)       # aucune fiche verrouillée dans la file


def test_suivante_pause_arret(fen, moteur):
    demarrees, _n = moteur
    p = plugin(fen)
    p.lire([("A", FR), ("B", FR + " Autre."), ("C", FR + " Encore.")])
    premiere = p.lecture
    p.basculer_pause()
    assert premiere.en_pause and p.fenetre.b_pause.text() == "Reprendre"
    p.basculer_pause()
    assert not premiere.en_pause
    p.suivante()
    assert premiere.arretee and len(demarrees) == 2 and "Fiche 2 sur 3" in p.fenetre.etat.text()
    fenetre = p.fenetre
    fenetre.close()                                # fermer la fenêtre = arrêter
    assert p.lecture is None and p.fenetre is None


def test_rien_a_lire_et_sans_moteur(fen, monkeypatch):
    m = sys.modules["scrinium_plugin_lecture"].logique
    p = plugin(fen)
    notes = []
    p.ctx.ui.notifier = lambda t, msg: notes.append(msg)
    p.lire([("Vide", "\n---\n")])
    assert p.fenetre is None and notes[-1]
    monkeypatch.setattr(m, "espeak", lambda: None)
    p.ctx.reglages.set("moteur", "espeak")
    p.lire([("A", FR)])
    assert p.fenetre is None and "espeak-ng" in notes[-1]


def test_piper_refuse_une_fois_puis_repli_espeak(fen, moteur, monkeypatch):
    demarrees, _n = moteur
    p = plugin(fen)
    p.ctx.reglages.set("moteur", "auto")
    questions = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: questions.append(a) or QMessageBox.StandardButton.No))
    p.lire([("A", FR)])
    assert len(questions) == 1 and "piper-tts" in questions[0][2] and demarrees                  # refus -> espeak-ng
    assert p.ctx.reglages.get("piper_refuse") is True
    p.lire([("A", FR)])
    assert len(questions) == 1                                                                   # pas de nouvelle question


def test_piper_pret_est_prefere(fen, moteur, monkeypatch, tmp_path):
    m = sys.modules["scrinium_plugin_lecture"].logique
    p = plugin(fen)
    p.ctx.reglages.set("moteur", "auto")
    monkeypatch.setattr(m, "piper_present", lambda deps: True)
    monkeypatch.setattr(m, "voix_presente", lambda modeles, cle: True)
    lances = []
    monkeypatch.setattr(m, "demarrer_piper", lambda deps, modeles, cle, lignes, vitesse=1.0: lances.append(cle) or FausseLecture(""))
    p.lire([("A", FR)])
    assert lances == ["fr_FR-siwis-medium"]


def test_reglages_se_construisent_et_s_enregistrent(fen):
    m = sys.modules["scrinium_plugin_lecture"]
    p = plugin(fen)
    d = m.DialogueReglages(p)
    d.moteur.setCurrentIndex(d.moteur.findData("espeak"))
    d.langue.setCurrentIndex(d.langue.findData("en"))
    d.vitesse.setValue(12)
    d._valider()
    r = p.ctx.reglages
    assert r.get("moteur") == "espeak" and r.get("langue") == "en" and r.get("vitesse") == 1.2 and r.get("piper_refuse") is False
