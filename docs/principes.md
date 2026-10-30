# Principes du projet / Project principles

*Français d'abord, English below.*

## Français

Scrinium est un **logiciel libre** (GPL-3.0-or-later) fait **pour n'importe qui** qui veut ranger ses petites notes, pas pour une
installation en particulier. Ces règles guident chaque ajout ; en cas de doute, elles passent avant la commodité.

### 1. Le cœur ne dépend d'aucun service tiers
Scrinium fonctionne seul, hors ligne, avec de simples fichiers. Aucun service (assistant d'IA, outil de messagerie, hébergeur,
tableau de bord…) n'est requis pour l'utiliser, et aucun n'est mis en avant plus qu'un autre.

### 2. Les intégrations sont **proposées, jamais imposées**
Une intégration avec un produit précis (Ollama, Open WebUI, Claude, Caddy, Syncthing…) :
- vit dans le dossier **`exemples/`** (non livré avec le programme) ou dans une **extension désactivée par défaut** ;
- est écrite **parce qu'une personne en a besoin**, pas par principe ;
- ne doit jamais devenir une dépendance du cœur, ni de l'installation, ni des tests (les tests tournent sans ces services).

### 3. Des briques génériques d'abord
Plutôt qu'une fonction pour un produit, on offre une brique que chacun peut brancher à son idée : la ligne de commande
(`scrinium ajouter`), le **dépôt** par requête `POST` avec des jetons à portée limitée (`serveur/`), les liens `scrinium://`,
l'API des extensions ([`plugins.md`](plugins.md)), le contrat d'API du partage ([`api-partage.md`](api-partage.md)). Ces briques sont
documentées avec des exemples **neutres**.

### 4. Rien de personnel dans le dépôt
Aucun nom de domaine, adresse IP, nom de machine, chemin, port ou compte réel de l'auteur ou d'un contributeur dans un fichier suivi
par git. Pour les exemples : `exemple.org`, `192.0.2.x` et `2001:db8::` (plages réservées à la documentation), `utilisateur`, `/chemin/…`.
Ce qui n'est utile que sur une installation précise reste **hors du dépôt** (notes privées, dossier ignoré par git).
Vérification avant de publier :

```bash
git ls-files | xargs grep -n -I -i "<votre domaine>\|192\.168\.\|<nom de votre machine>"     # doit ne rien trouver de personnel
```

### 5. Sécurité par défaut
- **Jamais d'écriture venue de l'extérieur sans validation visible** : un lien, un programme ou un modèle de langage qui demande
  d'ajouter une fiche ouvre une fenêtre ; rien n'est enregistré avant le clic de l'utilisateur, et rien n'existant n'est écrasé.
- **Portée minimale** : un jeton ne donne que ce dont son usage a besoin (le jeton de dépôt ne sait qu'ajouter) ; il est stocké
  haché, révocable, limité en nombre d'usages.
- **Aucun secret en clair** dans les fichiers de réglages ; une fiche verrouillée n'est jamais écrite en clair ni envoyée sans accord.
- **Les extensions ne sont pas un bac à sable** : désactivées par défaut, activées par l'utilisateur seulement, et on le lui dit.
- Les données reçues de l'extérieur (liens, serveurs, modèles) sont des **entrées non fiables** : nettoyées, bornées, jamais interprétées
  comme du code ou du HTML.

### 6. Les données restent à l'utilisateur
Fiches = fichiers Markdown lisibles avec n'importe quel éditeur, thèmes = dossiers. Pas de format fermé, pas de compte obligatoire.
Rien ne se perd sans retour possible (corbeille, copies de conflit plutôt qu'écrasement, fichier de secours pour les fiches verrouillées).

### 7. Plusieurs systèmes
Linux et Windows aujourd'hui, macOS à venir. Une fonction propre à un système est grisée ailleurs (champ `plateformes` des extensions),
jamais présentée comme générale. Une fonction qui ne marche que sur une infrastructure particulière n'a pas sa place dans le cœur.

### 8. Tester, traduire, expliquer
- Chaque fonction a ses tests (`python3 -m pytest`, hors écran) ; les erreurs trouvées deviennent des tests.
- L'interface est en français et en anglais, **sans chaîne manquante** (`python3 outils/i18n.py verifier`).
- Ce qui change ce que voit ou fait l'utilisateur est documenté (README, `docs/`, fiches d'aide) ; les limites sont dites franchement.
- Flux de travail : développement sur `dev`, puis `main` quand c'est stable ; une publication se décide explicitement.

---

## English

Scrinium is **free software** (GPL-3.0-or-later) made **for anyone** who wants to keep small notes — not for one particular
installation. These rules guide every addition; when in doubt, they come before convenience.

1. **The core depends on no third-party service.** Scrinium works alone, offline, with plain files. No service (AI assistant,
   messaging tool, host, dashboard…) is required, and none is promoted over another.
2. **Integrations are offered, never imposed.** An integration with a specific product (Ollama, Open WebUI, Claude, Caddy,
   Syncthing…) lives in the **`exemples/`** folder (not shipped with the program) or in an **extension disabled by default**; it is
   written because someone needs it, and never becomes a dependency of the core, the installation or the tests.
3. **Generic building blocks first**: the command line (`scrinium ajouter`), the **deposit** `POST` request with narrowly scoped
   tokens (`serveur/`), `scrinium://` links, the extension API ([`plugins.md`](plugins.md)), the sharing API contract
   ([`api-partage.md`](api-partage.md)) — documented with **neutral** examples, so anyone can plug in what they like.
4. **Nothing personal in the repository**: no real domain name, IP address, machine name, path, port or account of the author or
   a contributor in any file tracked by git. Examples use `example.org`, `192.0.2.x`, `2001:db8::` (ranges reserved for
   documentation). What is useful on one installation only stays **outside** the repository.
5. **Safe by default**: nothing coming from outside (a link, a program, a language model) is written without a visible
   confirmation, and nothing existing is overwritten; tokens carry the minimum scope, are stored hashed, revocable and
   rate-limited; no secret in clear text in settings; extensions are not a sandbox, are disabled by default, and users are told;
   data received from outside is untrusted input — cleaned, bounded, never interpreted as code or HTML.
6. **Data stays with the user**: notes are Markdown files readable with any editor, topics are folders; no closed format, no
   mandatory account; nothing is lost without a way back (trash, conflict copies instead of overwriting, recovery file for locked notes).
7. **Several systems**: Linux and Windows today, macOS to come. A system-specific feature is greyed out elsewhere (extensions'
   `plateformes` field), never presented as general.
8. **Test, translate, explain**: every feature has tests (`python3 -m pytest`, offscreen); the interface exists in French and English
   with **no missing string** (`python3 outils/i18n.py verifier`); changes visible to users are documented and limits are stated plainly;
   work happens on `dev`, then `main` when stable, and a release is an explicit decision.
