# API de partage de Scrinium (version 1)

Statut : **contrat implémenté par `serveur/` (v0.1.0)** (étape 2 du plan, `TODO.md` section « 3 quater-a »). C'est la **source de vérité** entre le serveur
(`serveur/`, PHP) et le plugin « Partage » (client). Le serveur de référence en mémoire (`core/transport.py`, `ServeurMemoire`) en est la
version exécutable : tout ce qui est écrit ici y est déjà testé (rôles, version de départ, droits).

## 1. Principes
- **HTTPS obligatoire** (http seulement vers l'ordinateur local, pour les essais). JSON en UTF-8. Préfixe `/api/v1`.
- **Le serveur fait foi** : droits et versions sont contrôlés côté serveur, jamais côté client.
- **Trois rôles** par fiche : `proprietaire`, `ecriture`, `lecture`. Seul le propriétaire partage, invite, retire un droit ou supprime.
- **Écrire exige la version de départ** : si ce n'est plus la dernière, le serveur refuse (`409`) ; le client garde alors les deux versions
  (voir `docs/partage-coeur.md`, § 3).
- Une fiche **non partagée avec un compte est invisible** pour lui (`404`, jamais `403`, pour ne rien révéler).
- Fiches **verrouillées** : hors de ce contrat à l'étape 2 (le serveur n'en reçoit pas) ; réservées à l'étape 3 (contenu opaque chiffré).

## 2. Authentification
| Requête | Corps | Réponse |
|---|---|---|
| `POST /api/v1/session` | `{"compte": "dede", "mot_de_passe": "…"}` | `200 {"jeton": "…", "expire_le": "2026-11-28T10:00:00Z", "compte": "dede"}` |
| `DELETE /api/v1/session` | — | `204` (le jeton est invalidé) |

Ensuite : en-tête `Authorization: Bearer <jeton>`. Jeton opaque (256 bits), **stocké haché** côté serveur, durée limitée (30 jours),
révocable. Trop d'échecs de connexion : `429` avec `Retry-After`. Mauvais compte ou mot de passe : `401` (même réponse dans les deux cas).

## 3. Fiches
Une fiche : `id` (32 caractères, l'identifiant stable du cœur), `version` (entier, 1 à la création), `titre`, `texte`, `pieces`.

| Requête | Rôle requis | Réponse |
|---|---|---|
| `GET /fiches` | — | `200 [{"id","version","titre","role","proprietaire","modifie_le"}]` : les fiches auxquelles j'ai accès |
| `GET /fiches/{id}` | lecture | `200 {"id","version","titre","texte","pieces":[{"nom","type","taille","sha256"}]}` |
| `PUT /fiches/{id}` | écriture | corps `{"titre","texte","pieces":[…],"version_depart": N}` → `200 {"version": N+1}` ; **`version_depart` = 0 : création** (`201`, l'appelant devient propriétaire) |
| `DELETE /fiches/{id}` | propriétaire | `204` |

- Erreurs : `409 {"erreur":"version","version_serveur": M}` si `version_depart ≠ M` (y compris création d'un id qui existe déjà) ; `404` fiche
  inconnue **ou non partagée avec moi** ; `403` rôle insuffisant (j'ai accès mais pas ce droit) ; `413` trop gros.
- Limites (celles du cœur) : image ≤ 8 Mo, 50 pièces et 100 Mo par fiche, texte ≤ 1 Mo ; le serveur les applique et peut les abaisser.

### Pièces jointes (images)
Adressées par leur contenu : `PUT /api/v1/blobs/{sha256}` (octets bruts ; le serveur **recalcule** l'empreinte et refuse si elle diffère) et
`GET /api/v1/blobs/{sha256}` (autorisé si l'une des fiches auxquelles j'ai accès la référence). Une fiche ne référence que des empreintes
déjà déposées ; le client dépose les images **avant** le `PUT /fiches/{id}`. Une image identique n'est stockée qu'une fois.

## 4. Droits
| Requête | Rôle requis | Réponse |
|---|---|---|
| `GET /fiches/{id}/droits` | propriétaire | `200 {"jfk":"proprietaire","dede":"ecriture","alphonse":"lecture"}` |
| `PUT /fiches/{id}/droits/{compte}` | propriétaire | corps `{"role":"ecriture"|"lecture"}` → `204` (crée ou remplace) |
| `DELETE /fiches/{id}/droits/{compte}` | propriétaire | `204` (le propriétaire ne se retire pas : `403`) |

Compte inconnu, rôle `proprietaire` ou rôle invalide : `422`.

## 5. Invitations (inviter une personne par courriel, valable 48 h)
**Scénario.** Le propriétaire clique sur **« Inviter / Partager… »**, saisit une adresse, **coche les droits** (lecture, ou lecture et écriture)
et valide. Le serveur crée l'invitation et rend un **lien** ; c'est **Scrinium du propriétaire** qui envoie le courriel (extension Courriel,
depuis sa propre boîte : le serveur n'a besoin d'aucun réglage de messagerie). La personne ouvre le lien, ou, dans Scrinium, utilise
**« Rejoindre un partage… »** et colle l'adresse reçue. Si elle n'a pas de compte, elle en crée un à ce moment-là ; sinon elle se connecte.

| Requête | Rôle requis | Réponse |
|---|---|---|
| `POST /fiches/{id}/invitations` | propriétaire | corps `{"email":"dede@…","role":"ecriture"}` → `201 {"id","url","expire_le","role"}` |
| `GET /fiches/{id}/invitations` | propriétaire | `200 [{"id","email","role","expire_le","etat":"en_attente"|"acceptee"|"expiree"|"annulee"}]` |
| `POST /invitations` | propriétaire de **toutes** les fiches | corps `{"email","role","fiches":[id,…]}` (1 à 500) → `201 {"id","url","expire_le","role"}` : **un seul lien pour plusieurs fiches** (partage d'un thème entier) |
| `DELETE /invitations/{id}` | propriétaire | `204` (annulée : le lien ne marche plus) |
| `GET /invitations/{jeton}` | **public** | `200 {"invite_par","role","expire_le","fiches"}` (`fiches` = nombre de fiches visées) : de quoi afficher « X vous invite… » (jamais le contenu) |
| `POST /invitations/{jeton}/accepter` | public ou connecté | connecté : `204` (le droit est ajouté à mon compte) ; non connecté : corps `{"compte","mot_de_passe"}` → crée le compte, ajoute le droit, `201 {"jeton": session}` |

- **Lien** : `https://serveur/inviter/<jeton>` (page HTML d'explication, avec un bouton qui ouvre `scrinium://rejoindre?serveur=…&jeton=…`) ;
  le jeton fait 256 bits, est **stocké haché**, à **usage unique**, valable **48 h**, limité à **une fiche et un rôle**, **annulable**.
- **L'invitation n'ouvre que ce qu'elle dit** : un seul rôle sur la ou les fiches nommées (une seule pour `/fiches/{id}/invitations`, la liste pour `POST /invitations`). Elle ne donne jamais plus qu'un rôle `ecriture`.
- **Vie privée** : `GET /invitations/{jeton}` ne dit pas si l'adresse a un compte ailleurs, et un jeton inconnu, expiré ou déjà utilisé donne
  la même réponse (`404`) ; limitation des essais (`429`).
- **Qui peut créer des comptes ?** Accepter une invitation sans compte en crée un. Réglage du serveur : `invitations_creent_des_comptes`
  (oui par défaut ; non = l'administrateur doit d'abord créer le compte) et quota d'invitations en attente par propriétaire.
- Le droit **reste acquis** après les 48 h (l'expiration ne concerne que le lien) ; le propriétaire le retire via § 4.

## 6. Découverte et compatibilité
`GET /api` (public) : `{"api": 1, "serveur": "0.1.0", "inscription": "invitation", "limites": {"image": 8388608, "pieces": 50}}`.
Le client refuse un serveur d'une autre version majeure d'API et le dit à l'utilisateur ; les ajouts compatibles ne changent pas le numéro.

## 7. Erreurs
Réponse d'erreur : `{"erreur": "code", "message": "…"}`.

| HTTP | `erreur` | Exception du cœur (`core/transport.py`) |
|---|---|---|
| 401 | `non_authentifie` | `NonAuthentifie` |
| 403 | `refuse` | `Refuse` |
| 404 | `introuvable` | `Introuvable` |
| 409 | `version` (+ `version_serveur`) | `ConflitDeVersion` |
| 422 / 413 / 429 | `invalide` / `trop_gros` / `trop_de_requetes` | `Refuse` (le message explique) |
| réseau, 5xx | — | `Injoignable` |

## 8. Correspondance avec l'interface `Transport`
| `Transport` | Requête |
|---|---|
| `lister()` | `GET /fiches` |
| `lire(id)` | `GET /fiches/{id}` (+ `GET /blobs/{sha256}` pour chaque image) |
| `ecrire(id, contenu, version_depart)` | `PUT /blobs/{sha256}` puis `PUT /fiches/{id}` |
| `droits(id)` | `GET /fiches/{id}/droits` |
| `partager(id, compte, role)` | `PUT /fiches/{id}/droits/{compte}` |
| `retirer_droit(id, compte)` | `DELETE /fiches/{id}/droits/{compte}` |
| `supprimer(id)` | `DELETE /fiches/{id}` |
| *(nouveau)* `inviter(id, email, role)`, `invitations(id)`, `annuler(invitation)`, `rejoindre(jeton, compte?, mot_de_passe?)` | § 5 |

## 9. Sécurité du serveur (obligations)
Mots de passe avec `password_hash` ; jetons de session et d'invitation **jamais stockés en clair** ; requêtes préparées (PDO) ; limitation
des essais de connexion et des invitations ; tailles bornées ; en-têtes stricts (pas de mise en cache des réponses authentifiées) ;
journal des actions (qui, quoi, quand) ; **configuration et données hors du dossier web** ; sauvegardes. Le serveur **peut lire** les fiches
non verrouillées : à dire clairement aux invités dans la page d'invitation.

## 10. Questions ouvertes
- ✔ Partage d'un **thème entier** : décidé côté client — le serveur ne connaît que des fiches ; le plugin partage chaque fiche non verrouillée du thème, avec une invitation groupée (`POST /invitations`). Reste : le thème d'origine n'est pas transmis (les fiches arrivent dans « Partagées »).
- **Suppressions** : fiche supprimée par le propriétaire = les autres la perdent-ils tout de suite, ou la gardent-ils comme fiche locale ?
- **Renommages simultanés** et fiche déplacée dans un autre thème chez l'un.
- Notifications, historique et corbeille côté serveur : plus tard (étape 4).
