# Outil Open WebUI : « Scrinium · créer une fiche » (facultatif)

*Exemple d'intégration pour qui utilise déjà Open WebUI : Scrinium n'en a pas besoin et ne l'impose pas.*

Permet à un modèle (Ollama, ou autre) de **créer une fiche dans Scrinium** quand on le lui demande : « note ça dans Scrinium »,
« enregistre ce résumé », etc. L'outil s'appuie sur le **dépôt** du serveur de partage (`POST /api/v1/depot`, voir
[`serveur/README.md`](../../serveur/README.md)).

## Sécurité
- Il utilise un **jeton de dépôt** : ce jeton ne sait qu'**ajouter** des fiches. Un modèle (ou une page web piégée qu'il aurait lue)
  ne peut ni lire, ni modifier, ni supprimer vos autres fiches. 60 dépôts par heure au plus ; le jeton se révoque en une commande.
- Les fiches portent le préfixe « [IA] » dans leur titre, pour les retrouver ; ce qu'écrit un modèle est à relire.
- Le serveur voit le texte (pas de chiffrement de bout en bout) : rien de secret.
- Le certificat auto-signé du serveur est vérifié par son **empreinte** (réglage `empreinte`).

## Installation (Open WebUI : Espace de travail > Outils > « + »)
1. Collez le contenu de `scrinium_depot.py` et enregistrez.
2. Réglages de l'outil (icône ⚙) :
   - `serveur` : l'adresse de votre serveur de partage, par exemple `https://scrinium.exemple.org` (depuis Docker, l'adresse IP plutôt qu'un nom `.local`, non résolu dans un conteneur) ;
   - `jeton` : sur le serveur, `sudo -u www-data php bin/scrinium-serveur creer-jeton <votre-compte> "Open WebUI"` (montré une seule fois) ;
   - `empreinte` : SHA-256 du certificat du serveur, s'il est auto-signé (`openssl x509 -in /chemin/du/certificat.crt -noout -fingerprint -sha256`) ; vide si le certificat est public.
3. Dans une conversation, activez l'outil (bouton « + » du champ de saisie > Outils > Scrinium) et choisissez un modèle qui sait appeler
   des outils (famille Qwen 3, Llama 3.1, Mistral…). Réglage utile : *Paramètres avancés > Appel de fonction*.
4. Demandez : « Résume ce texte et note-le dans Scrinium ».

La fiche arrive dans Scrinium à la prochaine synchronisation (*Extensions > Synchroniser les partages*), dans le thème « Partagées ».
