# Contribuer / Contributing

**Français.** Merci de votre aide ! Le **[manuel du développeur](docs/developpement.md)** (français et anglais) explique comment démarrer,
la carte du code, les règles à ne pas casser (sécurité, rien de personnel dans le dépôt), les conventions, comment ajouter une extension et
comment traduire. En résumé :

- travaillez sur la branche `dev` ; ouvrez une *pull request* vers `dev` (`main` ne reçoit que les versions publiées) ;
- `pip install -e ".[test]"` puis `python3 -m pytest -q` : la suite doit passer, et `python3 outils/i18n.py verifier` aussi ;
- un changement = un commit, avec ses tests, sa traduction anglaise et sa documentation ;
- une idée, un défaut : ouvrez une *issue*. Pour une faille de sécurité, n'écrivez pas les détails dans une issue publique : contactez le mainteneur.

**English.** Thanks for helping! The **[developer guide](docs/developpement.md)** (French and English) covers getting started, the code map,
the rules not to break (security, nothing personal in the repository), conventions, how to add an extension and how to translate. In short:

- work on the `dev` branch; open a pull request against `dev` (`main` only receives published releases);
- `pip install -e ".[test]"` then `python3 -m pytest -q`: the suite must pass, and so must `python3 outils/i18n.py verifier`;
- one change = one commit, with its tests, its English translation and its documentation;
- an idea, a bug: open an issue. For a security flaw, do not put details in a public issue: contact the maintainer.
