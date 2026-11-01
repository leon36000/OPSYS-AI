=== OPSYS Connect ===
Contributors: opsysai
Tags: automation, rest-api, drafts, approval
Requires at least: 6.9
Tested up to: non testé
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Connecteur mince et signé entre ce site et OPSYS-AI : brouillons, médias, état. Aucune publication sans le jeton d'approbation de la direction.

== Description ==

ÉTAT : version 0.1.0, écrite et analysée statiquement, JAMAIS EXÉCUTÉE dans WordPress. Ne pas la mettre sur un site de production avant d'avoir lancé `tests/verifier-vecteurs.php` (PHP 8.1 ou plus), les contrôles PHPCS avec les règles WordPress et Plugin Check, et essayé le plugin sur un site de recette avec des données fictives.

OPSYS Connect laisse OPSYS-AI préparer du contenu sur votre site sans jamais le publier de son propre chef.

* Il reçoit des requêtes REST signées (HMAC-SHA256 sur la méthode, la route, le corps, l'horodatage et un nonce à usage unique, fenêtre de 5 minutes).
* Il crée et met à jour des BROUILLONS (`draft` ou `pending`), et seulement ceux qu'il a créés.
* Il téléverse des images dans la médiathèque après avoir vérifié leur type MIME réel.
* Il lit l'état d'un article et son empreinte (SHA-256 du contenu stocké).
* Il ne publie qu'avec un jeton d'approbation signé, lié au site, à l'article et à l'empreinte du contenu au moment de la publication, valable une fois et au plus 24 heures. Un contenu modifié après l'approbation ne se publie pas.

Le plugin n'appelle aucun service externe, n'envoie aucune donnée, ne charge aucun code et n'écrit rien en dehors de la médiathèque.

== Installation ==

1. Copier le dossier `opsys-connect` dans `wp-content/plugins/` et activer le plugin. L'activation crée la table des valeurs à usage unique, le rôle `opsys_agent` (lire, écrire des brouillons, téléverser ; aucun droit de publier ni d'administrer) et l'utilisateur de service `opsys-agent` (mot de passe aléatoire jamais affiché).
2. Dans `wp-config.php`, définir :
   * `OPSYS_CONNECT_SECRET` : le secret partagé avec OPSYS (32 octets au moins, jamais dans la base ni dans le dépôt), OU `OPSYS_CONNECT_KEY` (32 octets au moins) puis `printf '%s' "$SECRET" | wp opsys-connect set-secret` pour l'enregistrer chiffré.
   * `OPSYS_CONNECT_SITE_ID` : l'identifiant de ce site chez OPSYS (minuscules, chiffres, point, tiret). Sans lui, la publication est désactivée.
   * facultatif : `OPSYS_CONNECT_KEY_ID` (« default »), `OPSYS_CONNECT_AGENT_LOGIN` (« opsys-agent »).
3. Vérifier la page Réglages > OPSYS Connect : le secret, l'identifiant du site, HTTPS et l'utilisateur de service doivent être au vert. Les permaliens « joliment » formés sont requis (l'interface est servie sous `/wp-json/`).

== Sécurité ==

* Toute requête exige HTTPS, une signature valide, un nonce jamais vu et un utilisateur de service qui n'a aucun droit dangereux (publier, administrer, installer des extensions, HTML non filtré). Sinon : refus.
* Les routes n'acceptent aucun paramètre de requête. Les corps JSON sont validés champ par champ ; un champ inconnu est refusé.
* Le statut d'un article n'est jamais `publish`, `future` ni `private` sans jeton valide, y compris si une autre extension tente de le changer en route.
* Le secret n'est jamais une option en clair.

== Changelog ==

= 0.1.0 =
Première version : santé, types, brouillons, médias, état, publication avec jeton d'approbation.
