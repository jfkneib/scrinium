# Scrinium

**English** · [Français](README.fr.md)

*Scrinium*: in Latin, the casket where books and precious papers were kept.

Short **notes** (a title and some text) organised by **topic**, saved automatically as plain text files.
Each note can be **locked with a password** (AES-256-GCM, key derived with scrypt). An optional **rescue file**,
created by you, can reopen a note whose password was forgotten.

Qt interface (PyQt6): Linux, Windows, macOS (Windows and macOS packages: coming). Available in English and French.

**[⬇ Download the latest release (.deb package)](https://github.com/jfkneib/scrinium/releases/latest)** · [Installation](#installation)

## Installation

**Debian / Ubuntu**: download `scrinium_0.4.1_all.deb` from the [**Releases page**](https://github.com/jfkneib/scrinium/releases/latest) (section *Assets*, at the bottom), or directly:

```bash
wget https://github.com/jfkneib/scrinium/releases/download/v0.4.1/scrinium_0.4.1_all.deb
```

then install it:

```bash
sudo apt install ./scrinium_0.4.1_all.deb
```

To check the download, also get `SHA256SUMS` from the same page and run `sha256sum -c SHA256SUMS`.

**Windows**: download `Scrinium-0.4.1-setup.exe` from the [Releases page](https://github.com/jfkneib/scrinium/releases/latest) (*Assets*) and double-click it. No administrator rights are needed (it installs for your user, in `%LOCALAPPDATA%\Programs\Scrinium`, with a Start menu shortcut and an entry in *Settings → Apps* to uninstall it). The installer is **not signed**: Windows shows "Windows protected your PC" the first time; click *More info*, then *Run anyway*. Your notes (`%APPDATA%\scrinium`) are never deleted. Extensions that need Linux tools (dictation, read aloud, capture and console) are greyed out on Windows.

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
- **Quick capture**: `scrinium --rapide` (also *File → Quick capture…*, Ctrl+Alt+N, and the notification-area menu) opens only a small "quick note" window; Ctrl+Enter appends the text (dated) to a note of your choice, which is remembered. The topic can be typed: a name that does not exist yet creates it (proposed by default: "Sous le coude" / "Kept handy"). To use it from anywhere, bind `scrinium --rapide` to a keyboard shortcut in your desktop settings (KDE: *System Settings → Keyboard → Shortcuts → Add Command*). With Scrinium running in the notification area it appears instantly; locked notes are never written to.
- **Add from a browser or another program**: the link `scrinium://ajouter?titre=…&texte=…&theme=…` opens a small window showing the proposed note; **nothing is saved until you click "Add"**, and an existing note is never modified (it always creates a new one). Example **browser bookmarklet** ("send this page to Scrinium": title, address and selected text):
  `javascript:(()=>{location.href='scrinium://ajouter?titre='+encodeURIComponent(document.title)+'&texte='+encodeURIComponent(location.href+'\n\n'+getSelection())})()`
  The link is known to the system once Scrinium is installed (Linux: `.deb` or `install.sh`; Windows: the installer); up to 64 KB of text (beyond that, use `scrinium ajouter` with a pipe). Running `scrinium "scrinium://ajouter?texte=hello"` in a terminal does the same.
- **Optional integrations**: nothing forces you to install a third-party service. The `exemples/` folder offers, for those who use them, integration examples (for instance an Open WebUI tool that lets a language model create a note); they are not shipped with the program.
- **Invite someone**: *File → Invite someone to install Scrinium…* creates (or reopens, never overwriting your edits) a ready-to-send note in an "Invitations" topic: download links, installation steps per system, extensions. With the Email extension on, the send window opens right away.
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

## Extensions

Scrinium can be extended with plugins. Eight are shipped with it (and with the `.deb`): **read aloud** (a note, the selection or a whole topic, in French or English: Piper voice or espeak-ng; locked notes are never read), **agenda** (dated reminders, linked to a note or not), **applications** (an icon panel to launch Thunderbird, KWrite, LibreOffice…), **OCR** (Tesseract, text of attached images), **dictation** (local faster-whisper), **email** (send a note by SMTP), **capture and console** (run a command into a note, send the selection to Konsole) and **translation** (TranslateGemma through llama.cpp, no Ollama needed). They are **disabled by default**:
*Extensions → Manage extensions…* lists them and enables them one by one, after a warning (an extension is Python code
running with the same rights as Scrinium: only enable ones you trust). Drop an extension folder into
`<data folder>/plugins/`, or install a package that provides one. Each one lists the optional programs it needs (Tesseract, faster-whisper, llama.cpp…) and asks before installing or downloading anything; nothing leaves your machine except the email you send. A working example is in [`plugins/hello`](plugins/hello);
the API is documented in [`docs/plugins.md`](docs/plugins.md). A faulty extension never prevents Scrinium from starting
and is disabled automatically after repeated errors.

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
python3 outils/i18n.py manquantes manquantes.json   # strings without translation (JSON {french: ""})
python3 outils/i18n.py fusionner traductions.json    # merge them, rewrites po/en.po and po/scrinium.pot
python3 outils/i18n.py verifier                      # fails if a string or a %s placeholder is missing
```

## Name and icon

*Scrinium* is a Latin word (a casket for books and papers). Several unrelated projects use the same name (for example
a research infrastructure for AI agents on PyPI, and an object-document mapper); none is related to this one. The icon
was drawn from scratch for this project from basic shapes.

I am not aware of any conflict, but **if you believe the name or the icon infringes a right or causes confusion, please
[open an issue](https://github.com/jfkneib/scrinium/issues) or write to me: I will change it in good faith.**
If you distribute a modified version, please make it clear that it is not the original (for example by renaming it).

## License

GPL-3.0-or-later (see [`LICENSE`](LICENSE)). Icons: Breeze theme (KDE), LGPL-3.0-or-later (see `src/scrinium/icons/NOTICE`).

Extensions are loaded into Scrinium's process: extensions distributed together with Scrinium should use a GPL-compatible license.
