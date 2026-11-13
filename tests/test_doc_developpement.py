"""Le manuel du développeur (docs/developpement.md) reste à jour : chaque module du cœur et de l'interface y figure, et ses liens existent."""
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOC = RACINE / "docs" / "developpement.md"


def _modules(dossier: str) -> list:
    return sorted(p.stem for p in (RACINE / "src" / "scrinium" / dossier).glob("*.py") if p.stem != "__init__")


def test_chaque_module_du_coeur_et_de_l_interface_est_dans_la_carte():
    texte = DOC.read_text(encoding="utf-8")
    manque = [f"{d}/{m}.py" for d in ("core", "ui") for m in _modules(d) if f"`{m}.py`" not in texte]
    assert not manque, f"à ajouter dans la carte du code de docs/developpement.md : {manque}"


def test_la_carte_ne_cite_pas_de_module_disparu():
    texte = DOC.read_text(encoding="utf-8")
    existants = set(_modules("core")) | set(_modules("ui")) | {"cli", "i18n", "i18n_po"}
    cites = set(re.findall(r"`([a-z_]+)\.py`", texte)) - {"logique", "conftest", "setup", "test_emballage", "__init__"}
    inconnus = sorted(c for c in cites if c not in existants and not c.startswith("test_"))
    assert not inconnus, f"modules cités mais absents : {inconnus}"


def test_les_liens_relatifs_existent():
    for doc in (DOC, RACINE / "CONTRIBUTING.md"):
        for cible in re.findall(r"\]\((?!https?:)([^)#]+)\)", doc.read_text(encoding="utf-8")):
            assert (doc.parent / cible).exists(), f"{doc.name} : lien cassé {cible}"


def test_les_deux_langues_ont_les_memes_titres_de_section():
    texte = DOC.read_text(encoding="utf-8")
    fr, en = texte.split("## English")
    assert len(re.findall(r"^### \d+\.", fr, re.M)) == len(re.findall(r"^### \d+\.", en, re.M)) == 9
