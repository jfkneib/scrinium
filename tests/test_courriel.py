# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
import importlib.util
from pathlib import Path
from unittest import mock

import pytest

_f = Path(__file__).resolve().parent.parent / "plugins" / "courriel" / "logique.py"
_spec = importlib.util.spec_from_file_location("courriel_logique", _f)
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

SMTP = {"hote": "smtp.exemple.fr", "securite": "starttls", "port": 587, "utilisateur": "moi", "expediteur": "moi@exemple.fr",
        "nom": "Jean"}


def test_adresses():
    assert lg.adresse_valide("a.b@exemple.fr") and not lg.adresse_valide("a@b") and not lg.adresse_valide("a b@c.fr")
    ok, ko = lg.analyser_adresses("a@x.fr, B@x.fr; a@X.fr\nzzz  c@x.fr")
    assert ok == ["a@x.fr", "B@x.fr", "c@x.fr"] and ko == ["zzz"]
    assert lg.fusionner(["a@x.fr"], ["A@x.fr", "b@x.fr"]) == ["a@x.fr", "b@x.fr"]


def test_message():
    m = lg.construire(SMTP, ["a@x.fr", "b@x.fr"], "Titre\nInjecté: oui", "Bonjour é")
    assert m["Subject"] == "Titre Injecté: oui" and m["To"] == "a@x.fr, b@x.fr" and "moi@exemple.fr" in m["From"]
    assert m.get_content().strip() == "Bonjour é"
    with pytest.raises(ValueError):
        lg.construire(SMTP, [], "t", "c")
    with pytest.raises(ValueError):
        lg.construire({**SMTP, "expediteur": ""}, ["a@x.fr"], "t", "c")
    with pytest.raises(ValueError):
        lg.construire(SMTP, ["pas une adresse"], "t", "c")


def test_refuse_authentification_sans_chiffrement():
    with pytest.raises(ValueError, match="chiffrement"):
        lg.ouvrir({**SMTP, "securite": "aucune"}, "secret")


@pytest.mark.parametrize("mode,classe", [("starttls", "SMTP"), ("ssl", "SMTP_SSL")])
def test_envoi(mode, classe):
    with mock.patch.object(lg.smtplib, classe) as cls:
        srv = cls.return_value
        srv.__enter__.return_value = srv
        msg = lg.construire({**SMTP, "securite": mode}, ["a@x.fr"], "t", "c")
        lg.envoyer({**SMTP, "securite": mode}, "mdp", msg)
        srv.login.assert_called_once_with("moi", "mdp")
        srv.send_message.assert_called_once_with(msg)
        assert srv.starttls.called == (mode == "starttls")
