# Scrinium

**English** · [Français](README.fr.md)

*Scrinium*: in Latin, the casket where books and precious papers were kept.

Short **notes** (a title and some text) organised by **topic**, saved automatically as plain text files.
Each note can be **locked with a password** (AES-256-GCM, key derived with scrypt). An optional **rescue file**,
created by you, can reopen a note whose password was forgotten.

Qt interface (PyQt6): Linux, Windows, macOS (Windows and macOS packages: coming). Available in English and French.

## Installation

**Debian / Ubuntu** (`.deb` package from the *Releases* page):

```bash
sudo apt install ./scrinium_0.1.0_all.deb
```

**Other distributions** (no root needed, from this repository):

```bash
./install.sh              # installs into ~/.local (isolated Python environment + launcher + icon)
./install.sh --uninstall  # removes it (your notes are kept)
```

`install.sh` needs Python ≥ 3.10 with `venv`. PyQt6 and cryptography are installed by pip.

## Usage

On first launch Scrinium creates a **Welcome** topic (5 notes that explain the tool, including a locked note to try)
and a few template topics to fill in (Personal, Home, Computers, Travel). Delete them whenever you like.

- `scrinium` opens the window: topics on the left, notes in the middle, editor on the right.
- **Note** (Ctrl+N) / **Topic**: create. Right-click a topic, or use the buttons under the list, to rename it, change its icon or delete it.
- **Automatic** saving (Ctrl+S to force). Search: Ctrl+F, across all topics.
- **Delete = trash** (`corbeille/` next to the notes): nothing is ever erased.
- **Notification area**: closing or minimising the window sends it to the notification area (click the icon to show/hide, right-click for the menu). Turn it off with *File → Minimise to the notification area*. On a desktop without a notification area (GNOME without the AppIndicator extension) the window behaves normally. When it hides, Scrinium **closes open locked notes**: the password is asked again.
- **Single instance**: launching `scrinium` again wakes up the window that is already open. `scrinium --minimise` starts hidden in the notification area. The *File → Start at login* checkbox sets this up for you (XDG autostart file on Linux, Run key on Windows, LaunchAgent on macOS).
- Options: `--theme NAME` (open on that topic), `--nouvelle` / `--new` (open with an empty note ready to type).
- **Language**: automatic (system language), or *Help → Language*, or the `SCRINIUM_LANG` environment variable (`en`, `fr`).

## Data

| System | Folder |
|---|---|
| Linux | `~/.config/scrinium/` |
| Windows | `%APPDATA%\scrinium\` |
| macOS | `~/Library/Application Support/scrinium/` |

`SCRINIUM_HOME` forces another folder. Inside: `fiches/<Topic>/<title>.md` (or `.lock`), `corbeille/` (the trash), `settings.json`.
The `.md` files can be read and edited with any text editor; to back up, just copy this folder.

## Locking and the rescue file

- **Lock…** encrypts the text of the note; the title stays visible, and search does not read the content of a locked note.
  No plain text is ever written to disk, even while editing. The password is never stored.
- **Rescue file**: if you forget the password of a note, it lets you reopen it. Scrinium offers to create it the
  **first time you lock a note** (or later: *Security → Rescue file…*). You choose its name (default
  *Scrinium-secours-<user>-<date>*) and its folder (default *Documents*), with an optional password protecting the file.
  Technically: an RSA key pair generated **on your machine**; the public key (`recovery.pub`) wraps the key of every note
  locked afterwards, and the rescue file is the private key (PEM). **Keep it away from the computer**: Scrinium keeps no
  copy. A new rescue file can be created at any time; it only covers notes locked after its creation (the others can
  only be opened with the old one). Notes locked *before* the very first rescue file was created receive it the next
  time they are unlocked.
- Recovery: menu *Security → Reopen a note with the rescue file…*, or from the command line:

```bash
scrinium rescue list
scrinium rescue open "title" --key ~/rescue-file.pem
scrinium rescue unlock "title" --key ~/rescue-file.pem    # puts the note back in plain text
```

(The French spelling `scrinium secours lister|ouvrir|deverrouiller` also works.)

## Integration (optional)

If an executable `~/.config/scrinium/hooks/themes-changed` exists, it is called each time a topic is created, renamed,
deleted or gets a new icon, with the JSON list `[{"nom","icone","fiches"}]` on its standard input.
Handy to generate launchers, a dashboard, etc.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[test]' && .venv/bin/pytest
dpkg-buildpackage -us -uc -b    # builds the .deb (in the parent folder)
```

The code is split into `core/` (storage, encryption, rescue file, no GUI dependency at all) and `ui/` (PyQt6).

### Translations

Texts use gettext. Source strings are in **French** (`_("…")` in the code); `po/scrinium.pot` is the template and
`po/en.po` the English translation. The `.po` files are compiled to `.mo` at build time (no extra tool needed).
To add a language, copy `po/scrinium.pot` to `po/<code>.po`, fill in the `msgstr` entries and run the tests (they
check that every string is translated and that placeholders such as `%s` match). To refresh the template after
changing the code:

```bash
xgettext --language=Python --keyword=_ --from-code=UTF-8 --sort-by-file -o po/scrinium.pot $(git ls-files 'src/*.py')
msgmerge -U po/en.po po/scrinium.pot
```

## License

GPL-3.0-or-later. Icons: Breeze theme (KDE), LGPL-3.0-or-later.
