# Writing a Scrinium extension (API v1)

An extension is a Python package that Scrinium loads **only after the user enables it** (*Extensions → Manage
extensions…*). Extensions are disabled by default and are never imported just to be listed.

> **Security**: an extension is ordinary Python code running inside Scrinium with the same rights. It is **not** sandboxed.
> The API below never hands out a note's encryption key and shows nothing of a locked note that is still closed, but a
> hostile extension could do more. Only enable extensions you trust.

## Where extensions live

1. **User folder** — `<data folder>/plugins/<name>/` (see the README for the data folder), containing:
   - `plugin.json` — `{"titre", "version", "auteur", "description", "classe", "api"}` (`classe` = name of the class in
     `__init__.py`, `api` = API version targeted, currently `1`);
   - `__init__.py` — the code.
   `<name>` must match `[a-z0-9][a-z0-9_-]*`. See [`plugins/hello`](../plugins/hello) for a working example.
2. **Installed package** — declare an entry point (system or pip package, e.g. `scrinium-reminders`):

   ```toml
   [project.entry-points."scrinium.plugins"]
   reminders = "scrinium_reminders:RemindersPlugin"
   ```

## The class

```python
from scrinium.core.plugins import Plugin

class MyPlugin(Plugin):
    api = 1                       # must equal Scrinium's API_VERSION, otherwise the extension is refused
    def activer(self, ctx): ...   # called when enabled (and at startup if it was left enabled)
    def desactiver(self): ...     # called when disabled or at exit
```

## `ctx` (what `activer` receives)

| | |
|---|---|
| `ctx.on(event, fn)` | subscribe to an event (below) |
| `ctx.themes()` | list of topic names |
| `ctx.fiches(theme=None)` | list of `FicheVue` |
| `ctx.fiche_courante()` | the note shown in the window, or `None` |
| `ctx.pieces(vue)` | attachments (images) of a note: list of `PieceVue` (`id`, `nom`, `type` `image/png` or `image/jpeg`, `taille`, `ajoute`, `ocr`, `ocr_moteur`); empty for a closed locked note |
| `ctx.lire_piece(vue, piece)` | bytes of an attachment (`piece` = `PieceVue` or its `id`); `ValueError` for a closed locked note |
| `ctx.maj_piece(vue, piece, ocr=None, ocr_moteur=None)` | store text extracted from an image (encrypted with it if the note is locked; searched by the main window) |
| `ctx.maj_meta(vue, **values)` | add/change/remove (`None`) metadata of a note, saved with it |
| `ctx.modifier(vue, titre=None, texte=None)` | change a note |
| `ctx.reglages` | per-extension settings: `.get(key, default)`, `.set(key, value)`, `.tous()` |
| `ctx.ui` | window helpers (below); `None` without a window |
| `ctx.dossier_donnees` | `Path` of a folder reserved for the extension (models, downloaded dependencies); not created until you do |
| `ctx.api` | API version provided |

`FicheVue` (read-only): `id`, `titre`, `theme`, `verrou` (is locked), `fermee` (locked and not opened yet), `texte`, `meta`.
For a locked note that is still closed, `texte` is `None` and `meta` is `{}`; changing it raises `ValueError`.

**Metadata** are stored in the note itself as one invisible line at the top of its text
(`<!-- scrinium: {"key": "value"} -->`); for a locked note they are encrypted with the text.

## Events (`ctx.on`)

| Event | Arguments |
|---|---|
| `demarrage` / `arret` | — |
| `fiche_ouverte` | `fiche` |
| `fiche_enregistree` | `fiche`, `origine` (extension name, or `None` for the user) |
| `fiche_fermee` | `fiche` |
| `themes_modifies` | — |
| `fenetre_cachee` / `fenetre_montree` | — |
| `piece_jointe_ajoutee` / `piece_jointe_supprimee` | `fiche`, `piece` (a deleted attachment can no longer be read) |
| `piece_jointe_modifiee` | `fiche`, `piece`, `origine` (extension name that called `ctx.maj_piece`) |

Handlers receive keyword arguments; accept `**kw` to stay compatible with future additions.

## `ctx.ui`

`ajouter_action(text, fn, icon=None)` (Extensions menu) · `ajouter_bouton(text, fn, icon=None)` (toolbar) ·
`ajouter_panneau(title, widget)` (dock, any `QWidget`) · `notifier(title, message)` (desktop notification) ·
`planifier(seconds, fn, repeter=False)` (timer) · `afficher_fiche(vue)` ·
`inserer_texte(text)` (insert at the cursor of the open note, `False` if it cannot be edited) · `texte_selectionne()`.
Everything added is removed automatically when the extension is disabled.

## Robustness

Every call into an extension is protected: an exception is logged and shown in the extensions dialog; after 5 errors
the extension is disabled automatically. A failing extension never prevents Scrinium from starting.

## Compatibility

`API_VERSION` is incremented on incompatible changes; additions (new events, new `ctx` methods) keep the same version.
