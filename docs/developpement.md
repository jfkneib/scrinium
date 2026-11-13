# Manuel du développeur / Developer guide

*Français d'abord, English below.* Pour écrire une extension, voir aussi [`plugins.md`](plugins.md) ; pour les règles du projet,
[`principes.md`](principes.md).

---

## Français

### 1. Démarrer

```bash
git clone https://github.com/jfkneib/scrinium && cd scrinium
git switch dev                                   # on travaille sur dev ; main ne reçoit que les versions publiées
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"                         # cryptography, PyQt6, pytest
python3 -m pytest -q                             # toute la suite : environ 2 minutes, aucun écran réel
```

- Les tests forcent `QT_QPA_PLATFORM=offscreen` (voir `tests/conftest.py`) : ils n'ouvrent **jamais** de vraie fenêtre ni ne touchent
  au presse-papiers ou à la zone de notification.
- Lancer le programme depuis les sources : `PYTHONPATH=src python3 -c "from scrinium.cli import main; main()"`. Un script qui importe
  `scrinium` doit être lancé avec `PYTHONPATH=src` : sinon Python peut prendre un `scrinium` **installé** sur la machine, plus ancien
  (c'est la cause de la plupart des erreurs « argument inattendu » incompréhensibles ; `pytest` n'a pas ce défaut, `pyproject.toml`
  fixe son `pythonpath`).
- Les extensions officielles (`plugins/`) ne sont copiées dans le paquet qu'à la construction (`setup.py`). En développement, copiez
  le dossier d'une extension dans `<dossier de données>/plugins/` pour l'essayer, puis activez-la dans *Extensions → Gérer*.
- Ne chaînez pas `pytest | tail && git commit` : `tail` renvoie 0 même si les tests échouent, et le commit part quand même.
- Un test (`tests/test_traduction.py`, fenêtre de progression, Python 3.13) échoue parfois sans rapport avec votre changement ;
  relancez-le seul avant de chercher une cause.

### 2. Carte du code

```
src/scrinium/
  cli.py            ligne de commande (fenêtre, récupération avec la clé de secours, ajout)
  i18n.py           traduction (gettext) ; i18n_po.py lit les .po et écrit les .mo sans dépendance
  core/             LE CŒUR : aucune dépendance graphique (PyQt) ; testable sans écran
  ui/               l'interface PyQt6
plugins/<nom>/      les extensions officielles (plugin.json, __init__.py, souvent logique.py)
serveur/            serveur de partage en PHP (contrat : docs/api-partage.md)
navigateur/         extension Firefox / Chrome / Edge « Envoyer à Scrinium » ; outils/xpi.sh fabrique le .xpi
outils/i18n.py      extraction, vérification et fusion des traductions
packaging/          lanceur .desktop, installeur Windows ; debian/ : paquet .deb
po/                 en.po et scrinium.pot
tests/              une suite pytest (plus de 800 tests)
docs/               documentation du projet
```

**Cœur (`src/scrinium/core/`)**

| Module | Rôle |
|---|---|
| `store.py` | Stockage : un dossier par thème, un fichier par fiche (`.md`, ou `.lock` si verrouillée), pièces jointes dans `<fiche>.pj/`, corbeille, favoris, ordre, lecture seule, validation des fiches exécutables. Tout ce qui écrit passe par là. |
| `crypto.py` | Chiffrement des fiches : AES-256-GCM, clé dérivée du mot de passe (scrypt) ; formats `AMLOCK1/2/3`. |
| `recovery.py` | Clé de secours : paire RSA propre à chaque utilisateur, créée à la demande. |
| `paths.py` | Emplacements des données selon le système. |
| `types_fiche.py` | Fiches typées (« tout est fiche ») : marque `#scrinium-<type>`, registre des types, `executable`, `a_faire`, empreinte. |
| `table_fiche.py` | Moteur commun des fiches « liste » (Inventaire, Collection, Mots de passe…) : un tableau Markdown lisible. |
| `liste_fiches.py` | Une liste (applications, actions CLI…) tenue par des fiches exécutables validées. |
| `repertoire.py` | Le répertoire : un tableau CSV rangé par lettre ; import de contacts. |
| `plugins.py` | Les extensions, API v1 : découverte, activation, `ctx`, événements, robustesse. |
| `flux.py` | Lecture de flux RSS / Atom (http et https seulement, bornée), partagée par Veille et Emploi. |
| `liens_fiches.py` | Liens `[[fiche]]` entre fiches et rétroliens. |
| `lien.py` | Liens `scrinium://…` reçus du système : analyse et validation, jamais d'écriture. |
| `capture.py` | Ajouter du texte à une fiche (sortie de commande, capture rapide). |
| `echange_md.py` | Export et import d'une fiche en Markdown avec ses images. |
| `images_texte.py` | Images dans le texte : références « pj:N » vers les pièces jointes. |
| `echange_theme.py` | Export et import d'un thème entier en archive zip. |
| `exemples.py`, `guide.py`, `doc_extensions.py`, `invitation.py` | Textes livrés : premiers thèmes, thème « Guide », thème « Doc », invitation à installer. |
| `autostart.py` | Lancement à l'ouverture de session (Linux, Windows, macOS). |
| `depots.py`, `synchro.py`, `synchroniser.py`, `transport.py`, `conflits.py` | Partage : dépôts, état de synchronisation, synchronisation, interface du transport, conflits (on ne perd ni n'écrase jamais en silence). |

**Interface (`src/scrinium/ui/`)**

| Module | Rôle |
|---|---|
| `fenetre.py` | La fenêtre principale : listes de thèmes et de fiches, éditeur, menus, raccourcis, export / import, lecture seule. Le plus gros fichier : on y ajoute un geste. |
| `extensions.py` | Ce qu'une extension peut ajouter à la fenêtre (`ctx.ui`), et la boîte « Gérer les extensions ». |
| `entrees_menu.py` | Entrées de clic droit fournies par la fenêtre et les extensions. |
| `markdown.py` | Boutons de mise en forme et aperçu rendu. |
| `chercher_remplacer.py` | La barre « Chercher / Remplacer » (Ctrl+H). |
| `images.py` | Pièces jointes : import avec réencodage, éditeur qui capte le collage, bande de vignettes, visionneuse. |
| `table_fiche.py`, `repertoire.py` | Vues des fiches « liste » et « répertoire ». |
| `export_pdf.py` | Export PDF d'une fiche. |
| `export_theme_doc.py` | Export d'un thème en site HTML ou en un seul PDF. |
| `assistant.py`, `lien_ajout.py`, `capture_rapide.py`, `choix_icone.py`, `icons.py`, `instance.py` | Fenêtres et utilitaires : fichier de secours, validation d'un lien `scrinium://ajouter`, note rapide, choix d'icône, icônes, instance unique. |

**Règle de séparation.** La *logique* d'une fonction va dans le cœur (ou dans `logique.py` d'une extension), **sans PyQt**, avec ses
tests ; l'*interface* ne fait que l'appeler. C'est ce qui permet de tester sans écran, et ce que tous les modules ci-dessus respectent.

### 3. Les idées à connaître

- **Fiche, thème.** Une fiche est un fichier Markdown (`# Titre`, puis le texte), un thème est un dossier. Pas de base de données.
  Le titre est dans le fichier ; le nom de fichier en est dérivé (`Store.libre` évite les collisions).
- **Fiche typée.** Son texte commence par `#scrinium-<type>`. Un type se déclare avec `TypeFiche(...)` et une *vue* (un widget
  `charger(texte)` / signal `modifie` / `actif`). Une fiche **exécutable** (qui lance des commandes) est **inerte** tant que
  l'utilisateur ne l'a pas validée ; la validation est liée à l'**empreinte du texte** (modifier la fiche hors de l'application
  l'invalide). Voir [`plugins.md`](plugins.md).
- **Extension.** Un dossier `plugins/<nom>/` : `plugin.json`, `__init__.py` (classe `Plugin`, `activer(ctx)`), et le plus souvent
  `logique.py` sans Qt (analyse, calculs, formats) que les tests appellent directement. Les extensions sont **désactivées par défaut**.
- **Résultats d'un thread.** Un travail en arrière-plan (réseau, OCR) ne touche jamais l'interface : il renvoie son résultat par un
  signal Qt (`pyqtSignal`), reçu dans le thread de l'interface.
- **Fiches d'exemple.** `ctx.ajouter_exemple(...)` : créées **une seule fois**, quand l'utilisateur active l'extension ; l'exemple
  d'un type exécutable est alors validé d'emblée (l'utilisateur vient de demander l'extension).

### 4. Les règles à ne pas casser

1. **Rien d'exécutable n'est validé en silence.** Une fiche exécutable reçue (partage, lien, archive, fichier déposé, import) reste
   inerte. Une extension ne peut pas valider ses propres fiches.
2. **Rien venu de l'extérieur n'est écrit sans un clic visible** (lien, programme, modèle de langage), et rien d'existant n'est écrasé.
   Un import crée une **nouvelle** fiche ou un **nouveau** thème ; il ne fusionne pas.
3. **Les données externes sont des entrées non fiables** : bornées en taille, nettoyées, jamais interprétées comme du code ou du
   HTML. Flux : http et https seulement, 2 Mo, entités refusées ; archives : chemins `..` refusés, limites de nombre et de taille ;
   images : réencodées, sans métadonnées.
4. **Aucun secret en clair** dans les fichiers de réglages ; une fiche verrouillée n'est jamais écrite en clair ni envoyée sans accord.
   Une extension ne reçoit jamais la clé de chiffrement d'une fiche.
5. **Rien ne se perd sans retour possible** : corbeille, copies de conflit plutôt qu'écrasement, écritures atomiques.
6. **Rien de personnel dans le dépôt** : ni nom de domaine, adresse, machine, chemin ou compte réels (utiliser `exemple.org`,
   `192.0.2.x`, `utilisateur`). Les intégrations avec un produit précis vont dans `exemples/` ou dans une extension désactivée par
   défaut ; jamais une dépendance du cœur ni des tests. Détails dans [`principes.md`](principes.md).
7. **Plusieurs systèmes** : Linux d'abord, mais Windows et macOS ne doivent pas être cassés ; une extension qui dépend d'outils
   Linux le déclare (`"plateformes"` dans `plugin.json`).

### 5. Conventions

- **Textes sources en français**, dans `_("…")` (traduction immédiate) ou `N_("…")` (traduit plus tard). Pas de `_(variable)`.
  Les messages ne sont jamais construits par concaténation : un seul texte avec `%s` / `%d`.
- **Un changement = un commit**, message en français qui dit quoi et pourquoi ; tests, traduction et documentation avec le changement.
- **Tests** : chaque fonction a ses tests (`tests/test_<sujet>.py`) ; la logique sans Qt, l'interface par la vraie fenêtre hors écran.
  Un test d'une règle de sécurité (point 4) est obligatoire quand on la touche.
- **Docstrings** : en tête de module, une phrase qui dit à quoi il sert, puis les choix et leurs raisons ; c'est ce que la carte ci-dessus résume.

### 6. Ajouter une extension (liste de contrôle)

1. Copier `plugins/hello`, renommer, remplir `plugin.json` (`titre`, `description`, `classe`, `api: 1`, `plateformes` si besoin).
2. Mettre la logique dans `logique.py` (sans Qt) ; l'interface dans `__init__.py`.
3. Un type de fiche : `ctx.ui.enregistrer_type(TYPE, vue)` ; si elle lance des commandes ou contacte le réseau : `executable=True`.
4. `ctx.ajouter_doc(...)` (la fiche d'aide) et `ctx.ajouter_exemple(...)` (l'exemple de départ).
5. Tests : la logique, puis l'extension dans la fenêtre (voir `tests/test_nouvelles_fiches.py`, fixture `fen`).
6. L'ajouter à la liste `OFFICIELLES` de `tests/test_emballage.py`, au nombre d'extensions des `README`, au guide (`core/guide.py`).
7. Traductions (section 7), puis `python3 -m pytest -q`.

### 7. Traductions

Le français est la langue source ; l'anglais est dans `po/en.po` (complet, vérifié par la CI).

```bash
python3 outils/i18n.py manquantes /tmp/m.json    # écrit {texte français: ""} pour chaque chaîne sans traduction
# remplir les valeurs en anglais dans /tmp/m.json, puis :
python3 outils/i18n.py fusionner /tmp/m.json     # réécrit po/en.po et po/scrinium.pot
python3 outils/i18n.py verifier                  # code 1 s'il manque une traduction ou si un marqueur (%s, %d) diffère
```

Si vous modifiez un texte déjà traduit, son ancienne traduction n'est plus reliée : redonnez l'anglais du nouveau texte.

### 8. Publier une version (mainteneur)

1. Sur `dev`, tout est fusionné et la suite passe. Changelog `debian/changelog` (entrée `UNRELEASED` pendant le développement).
2. « Version X.Y.Z » : `src/scrinium/__init__.py`, `debian/scrinium.1`, les liens des `README`, et `UNRELEASED` → `unstable` dans le changelog.
3. Fusionner `dev` dans `main`, étiqueter `vX.Y.Z` (étiquette annotée), pousser `main` et l'étiquette.
4. Les workflows construisent le `.deb` et l'installeur Windows et les déposent dans une release **brouillon** ; le module Firefox
   **signé** (`navigateur/signe/*.xpi`), s'il existe, y est joint aussi. Rien n'est public à ce stade.
5. Vérifier les fichiers, puis publier. Une **pré-version** (case « pre-release ») laisse la version précédente en « dernière » :
   pratique pour que les personnes concernées testent avant la version normale.

### 9. Références

- **Qt 6** (l'interface) : [documentation Qt](https://doc.qt.io/qt-6/) : widgets, signaux et slots, `QTextDocument`, `QImage`.
- **PyQt6** (le lien Python) : [documentation de PyQt6](https://www.riverbankcomputing.com/static/Docs/PyQt6/) (Riverbank Computing). Les noms
  suivent Qt, avec quelques écarts (énumérations qualifiées : `Qt.AlignmentFlag.AlignCenter`, signal = `pyqtSignal`). **Licence :** PyQt6
  est sous **GPL-3.0-only** (version gratuite de PyPI) ou sous une licence commerciale payante de Riverbank, **sans option LGPL** (à ne pas
  confondre avec Qt, qui propose aussi la LGPL v3). Scrinium, en GPL-3.0-or-later, est compatible ; mais tant qu'il utilise PyQt6 sous GPL,
  il doit rester sous GPL quand il est distribué. Passer à une licence plus permissive ou fermée demanderait la licence commerciale de
  PyQt6 ou un passage à PySide6 (LGPL v3, API très proche).
- **cryptography** (le chiffrement) : [cryptography.io](https://cryptography.io/) : AES-GCM, scrypt, RSA.
- **Icônes** : thème Breeze de KDE (LGPL-3.0-or-later), voir `src/scrinium/icons/NOTICE`.
- Le reste de la documentation du projet : [`plugins.md`](plugins.md), [`principes.md`](principes.md), [`api-partage.md`](api-partage.md),
  [`format-pieces-jointes.md`](format-pieces-jointes.md), [`partage-coeur.md`](partage-coeur.md).

---

## English

### 1. Getting started

```bash
git clone https://github.com/jfkneib/scrinium && cd scrinium
git switch dev                                   # work on dev; main only receives published releases
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"                         # cryptography, PyQt6, pytest
python3 -m pytest -q                             # the whole suite: about 2 minutes, no real display
```

- Tests force `QT_QPA_PLATFORM=offscreen` (see `tests/conftest.py`): they **never** open a real window or touch the clipboard or the
  tray.
- Run the program from the sources: `PYTHONPATH=src python3 -c "from scrinium.cli import main; main()"`. Any script that imports
  `scrinium` must run with `PYTHONPATH=src`, otherwise Python may pick an older **installed** `scrinium` (the cause of most puzzling
  "unexpected argument" errors; `pytest` is immune, `pyproject.toml` sets its `pythonpath`).
- Official extensions (`plugins/`) are only copied into the package at build time (`setup.py`). While developing, copy an extension
  folder into `<data folder>/plugins/` to try it, then enable it in *Extensions → Manage*.
- Do not chain `pytest | tail && git commit`: `tail` returns 0 even if the tests fail, and the commit goes through anyway.
- One test (`tests/test_traduction.py`, progress window, Python 3.13) sometimes fails unrelated to your change; re-run it alone first.

### 2. Code map

```
src/scrinium/
  cli.py            command line (window, recovery with the recovery key, add)
  i18n.py           translation (gettext); i18n_po.py reads .po and writes .mo without dependencies
  core/             THE CORE: no GUI dependency (PyQt); testable without a display
  ui/               the PyQt6 interface
plugins/<name>/     the official extensions (plugin.json, __init__.py, often logique.py)
serveur/            sharing server in PHP (contract: docs/api-partage.md)
navigateur/         Firefox / Chrome / Edge "Send to Scrinium" extension; outils/xpi.sh builds the .xpi
outils/i18n.py      extraction, check and merge of translations
packaging/          .desktop launcher, Windows installer; debian/: the .deb package
po/                 en.po and scrinium.pot
tests/              one pytest suite (more than 800 tests)
docs/               project documentation
```

**Core (`src/scrinium/core/`)**

| Module | Role |
|---|---|
| `store.py` | Storage: one folder per topic, one file per note (`.md`, or `.lock` when locked), attachments in `<note>.pj/`, trash, favourites, order, read-only, validation of executable notes. Everything that writes goes through it. |
| `crypto.py` | Note encryption: AES-256-GCM, key derived from the password (scrypt); `AMLOCK1/2/3` formats. |
| `recovery.py` | Recovery key: an RSA pair per user, created on demand. |
| `paths.py` | Data locations per operating system. |
| `types_fiche.py` | Typed notes ("everything is a note"): `#scrinium-<type>` mark, type registry, `executable`, `a_faire`, hash. |
| `table_fiche.py` | Common engine of "list" notes (Inventory, Collection, Passwords…): a readable Markdown table. |
| `liste_fiches.py` | A list (applications, CLI actions…) kept in validated executable notes. |
| `repertoire.py` | The directory: a CSV table sorted by letter; contacts import. |
| `plugins.py` | Extensions, API v1: discovery, activation, `ctx`, events, robustness. |
| `flux.py` | RSS / Atom reader (http and https only, bounded), shared by Watch and Job search. |
| `liens_fiches.py` | `[[note]]` links between notes and backlinks. |
| `lien.py` | `scrinium://…` links received from the system: parsing and validation, never any write. |
| `capture.py` | Append text to a note (command output, quick capture). |
| `echange_md.py` | Export and import of ONE note as Markdown with its images. |
| `images_texte.py` | Images inside the text: “pj:N” references to attached pieces. |
| `echange_theme.py` | Export and import of a whole topic as a zip archive. |
| `exemples.py`, `guide.py`, `doc_extensions.py`, `invitation.py` | Shipped texts: first topics, the "Guide" topic, the "Doc" topic, the invitation to install. |
| `autostart.py` | Start at session login (Linux, Windows, macOS). |
| `depots.py`, `synchro.py`, `synchroniser.py`, `transport.py`, `conflits.py` | Sharing: repositories, sync state, synchronisation, transport interface, conflicts (nothing is ever lost or overwritten silently). |

**Interface (`src/scrinium/ui/`)**

| Module | Role |
|---|---|
| `fenetre.py` | The main window: topic and note lists, editor, menus, shortcuts, export / import, read-only. The biggest file: a new gesture is added here. |
| `extensions.py` | What an extension can add to the window (`ctx.ui`), and the "Manage extensions" dialog. |
| `entrees_menu.py` | Right-click entries provided by the window and the extensions. |
| `markdown.py` | Formatting buttons and rendered preview. |
| `chercher_remplacer.py` | The "Find / Replace" bar (Ctrl+H). |
| `images.py` | Attachments: import with re-encoding, an editor that catches pasting, thumbnail strip, viewer. |
| `table_fiche.py`, `repertoire.py` | Views of "list" and "directory" notes. |
| `export_pdf.py` | PDF export of a note. |
| `export_theme_doc.py` | Export of a topic as an HTML site or a single PDF. |
| `assistant.py`, `lien_ajout.py`, `capture_rapide.py`, `choix_icone.py`, `icons.py`, `instance.py` | Windows and utilities: recovery file, validation of a `scrinium://ajouter` link, quick note, icon picker, icons, single instance. |

**Separation rule.** A feature's *logic* goes in the core (or in an extension's `logique.py`), **without PyQt**, with its tests; the
*interface* only calls it. This is what makes testing without a display possible, and every module above follows it.

### 3. Ideas to know

- **Note, topic.** A note is a Markdown file (`# Title`, then the text), a topic is a folder. No database. The title is in the file;
  the file name is derived from it (`Store.libre` avoids collisions).
- **Typed note.** Its text starts with `#scrinium-<type>`. A type is declared with `TypeFiche(...)` and a *view* (a widget with
  `charger(texte)` / `modifie` signal / `actif`). An **executable** note (one that runs commands) is **inert** until the user validates
  it; validation is tied to the **hash of the text** (editing the file outside the application invalidates it). See [`plugins.md`](plugins.md).
- **Extension.** A folder `plugins/<name>/`: `plugin.json`, `__init__.py` (a `Plugin` class, `activer(ctx)`), and usually a Qt-free
  `logique.py` (parsing, computing, formats) that the tests call directly. Extensions are **disabled by default**.
- **Results from a thread.** Background work (network, OCR) never touches the interface: it returns its result through a Qt signal
  (`pyqtSignal`), received in the interface thread.
- **Example notes.** `ctx.ajouter_exemple(...)`: created **only once**, when the user enables the extension; the example of an executable
  type is then validated right away (the user just asked for the extension).

### 4. Rules not to break

1. **Nothing executable is validated silently.** An executable note received (share, link, archive, dropped file, import) stays
   inert. An extension cannot validate its own notes.
2. **Nothing from outside is written without a visible click** (link, program, language model), and nothing existing is overwritten.
   An import creates a **new** note or a **new** topic; it never merges.
3. **External data is untrusted input**: bounded in size, cleaned, never interpreted as code or HTML. Feeds: http and https only,
   2 MB, entities refused; archives: `..` paths refused, limits on count and size; images: re-encoded, metadata removed.
4. **No secret in clear** in settings files; a locked note is never written in clear or sent without consent. An extension never
   receives a note's encryption key.
5. **Nothing is lost without a way back**: trash, conflict copies rather than overwriting, atomic writes.
6. **Nothing personal in the repository**: no real domain name, address, machine, path or account (use `exemple.org`, `192.0.2.x`,
   `utilisateur`). Integrations with a specific product go in `exemples/` or in an extension disabled by default; never a dependency
   of the core or of the tests. Details in [`principes.md`](principes.md).
7. **Several systems**: Linux first, but Windows and macOS must not break; an extension depending on Linux tools declares it
   (`"plateformes"` in `plugin.json`).

### 5. Conventions

- **Source texts in French**, in `_("…")` (immediate translation) or `N_("…")` (translated later). No `_(variable)`. Messages are never
  built by concatenation: one text with `%s` / `%d`.
- **One change = one commit**, a French message saying what and why; tests, translation and documentation go with the change.
- **Tests**: every function has tests (`tests/test_<subject>.py`); logic without Qt, the interface through the real window offscreen.
  A test of a security rule (point 4) is mandatory when you touch it.
- **Docstrings**: at the top of a module, one sentence saying what it is for, then the choices and their reasons; the map above summarises them.

### 6. Adding an extension (checklist)

1. Copy `plugins/hello`, rename, fill in `plugin.json` (`titre`, `description`, `classe`, `api: 1`, `plateformes` if needed).
2. Put the logic in `logique.py` (no Qt); the interface in `__init__.py`.
3. For a note type: `ctx.ui.enregistrer_type(TYPE, vue)`; if it runs commands or reaches the network: `executable=True`.
4. `ctx.ajouter_doc(...)` (the help note) and `ctx.ajouter_exemple(...)` (the starting example).
5. Tests: the logic, then the extension inside the window (see `tests/test_nouvelles_fiches.py`, fixture `fen`).
6. Add it to the `OFFICIELLES` list in `tests/test_emballage.py`, to the extension count in the `README`s, and to the guide (`core/guide.py`).
7. Translations (section 7), then `python3 -m pytest -q`.

### 7. Translations

French is the source language; English is in `po/en.po` (complete, checked by CI).

```bash
python3 outils/i18n.py manquantes /tmp/m.json    # writes {French text: ""} for each untranslated string
# fill in the English values in /tmp/m.json, then:
python3 outils/i18n.py fusionner /tmp/m.json     # rewrites po/en.po and po/scrinium.pot
python3 outils/i18n.py verifier                  # exit 1 if a translation is missing or a marker (%s, %d) differs
```

If you edit an already translated text, its old translation is no longer linked: give the English for the new text again.

### 8. Releasing a version (maintainer)

1. On `dev`, everything is merged and the suite passes. `debian/changelog` (an `UNRELEASED` entry during development).
2. "Version X.Y.Z": `src/scrinium/__init__.py`, `debian/scrinium.1`, the `README` links, and `UNRELEASED` → `unstable` in the changelog.
3. Merge `dev` into `main`, tag `vX.Y.Z` (annotated tag), push `main` and the tag.
4. The workflows build the `.deb` and the Windows installer and put them in a **draft** release; the **signed** Firefox module
   (`navigateur/signe/*.xpi`), if present, is attached too. Nothing is public at this stage.
5. Check the files, then publish. A **pre-release** ("pre-release" box) keeps the previous version as "latest": handy to let the people
   concerned test before the normal release.

### 9. References

- **Qt 6** (the interface): [Qt documentation](https://doc.qt.io/qt-6/): widgets, signals and slots, `QTextDocument`, `QImage`.
- **PyQt6** (the Python binding): [PyQt6 documentation](https://www.riverbankcomputing.com/static/Docs/PyQt6/) (Riverbank Computing). Names
  follow Qt, with a few differences (scoped enums: `Qt.AlignmentFlag.AlignCenter`, signal = `pyqtSignal`). **Licence:** PyQt6 is
  under **GPL-3.0-only** (the free PyPI version) or a paid commercial licence from Riverbank, **with no LGPL option** (not to be confused
  with Qt, which also offers LGPL v3). Scrinium, GPL-3.0-or-later, is compatible; but as long as it uses PyQt6 under the GPL, it must stay
  under the GPL when distributed. Moving to a more permissive or closed licence would need PyQt6's commercial licence or a move to
  PySide6 (LGPL v3, very similar API).
- **cryptography** (encryption): [cryptography.io](https://cryptography.io/): AES-GCM, scrypt, RSA.
- **Icons**: KDE Breeze theme (LGPL-3.0-or-later), see `src/scrinium/icons/NOTICE`.
- The rest of the project documentation: [`plugins.md`](plugins.md), [`principes.md`](principes.md), [`api-partage.md`](api-partage.md),
  [`format-pieces-jointes.md`](format-pieces-jointes.md), [`partage-coeur.md`](partage-coeur.md).
