# Envoyer à Scrinium — extension de navigateur (facultative)

Clic droit sur une sélection (ou sur une page) → **Envoyer à Scrinium**. Scrinium s'ouvre sur une petite fenêtre
« Ajouter » qui montre la fiche proposée (titre de la page, adresse, texte sélectionné). **Rien n'est enregistré
tant que vous n'avez pas validé**, et une fiche existante n'est jamais modifiée.

Elle utilise le lien `scrinium://ajouter` (installé avec Scrinium sous Linux et Windows). Le même dossier sert pour
Firefox, Chrome et Edge. Le texte est limité à 20 000 caractères.

## Installer pour l'essayer
- **Firefox** : `about:debugging#/runtime/this-firefox` → *Charger un module complémentaire temporaire…* → choisir `manifest.json`
  (disparaît au redémarrage ; pour une installation durable, signer le module sur addons.mozilla.org).
- **Chrome / Edge** : `chrome://extensions` (ou `edge://extensions`) → activer *Mode développeur* →
  *Charger l'extension non empaquetée* → choisir ce dossier.

Au premier clic, le navigateur demande l'autorisation d'ouvrir Scrinium : cochez « toujours autoriser ».
