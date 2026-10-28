# Notes internes du dossier client — tranche serveur

Statut : PARTIAL pour le CRM complet. Cette tranche permet à un admin SQL actif de consigner une note
interne sur une demande M2 active, puis de la retrouver dans les activités du client. Elle répond à la
partie « notes de suivi » de CRM-05/CRM-06 et prépare CRM-02 ; la pastille sur une carte de cédule reste
à construire. Aucun courriel n’est envoyé et aucune deuxième base commerciale n’est créée.

## Contrat et fichiers

`src/opsys/console/crm_ui.py` ajoute le formulaire au dossier existant et deux routes :

- `POST /crm/lead/{lead_id}/notes` : formulaire puis redirection vers les activités ;
- `POST /api/crm/lead/{lead_id}/notes` : réponse JSON avec reçu M2 et indicateur `rejoue`.

La console peut être montée sous un préfixe, repris dans les liens. Le corps accepte exclusivement
`resume` et `mutation_id` (plus le jeton CSRF dans le formulaire). Le résumé est non vide et limité
à 300 caractères, sans troncature silencieuse. L’identifiant de mutation est non vide et borné.
`application.py` fournit les contrôles de session/CSRF existants. `metier.py` autorise explicitement
`m2_enregistrer_interaction` dans la liste fermée des commandes M2 admin.

M2 reste propriétaire de la note : auteur tiré de l’identité authentifiée, heure serveur, journal
append-only, reçu et audit. Aucun auteur ni horodatage ne provient du formulaire. Les notes historiques
ne sont pas éditées. Une demande perdue ou convertie refuse les nouvelles notes selon la règle M2 ;
un message explique la fermeture. La vue présente les dix interactions les plus récentes du client,
tous projets confondus, avec échappement HTML et affichage de l’heure de Montréal.

## Permissions, rejeu et risques

Session active et CSRF sont obligatoires. Le rôle admin est relu dans SQL avant exécution et avant
rejeu ; `nathan_owner` seul ne contourne pas les droits M2. Aucune personne réelle ne reçoit un droit
nouveau. Une même mutation et un même contenu rendent le reçu sans deuxième note ; un contenu différent
avec la même clé est refusé. Validation et reçu s’exécutent dans la transaction existante ; un refus
métier remonte avant sa validation. Les données des tests sont fictives.

Le futur profil secrétariat, les droits vendeur, les corrections de notes, la pagination historique et
l’ancrage sur une cédule demandent leurs propres contrats et vérifications. Cette tranche n’active ni
suivi courriel, ni agenda, ni modification financière, ni nouveau flux M10. Les frontières Nathan
existantes restent applicables aux actions externes ; une note interne autorisée n’est pas un envoi.

## Vérification et limites

`tests/test_console_crm.py` exerce les routes FastAPI avec SQLite durable et les outils M2 réels :
auteur/heure serveur, affichage échappé, formulaire, doublon, conflit, champs interdits, longueur,
CSRF absent, révocation de rôle, session expirée, lead absent et lead clos. La vérification élargie
couvre aussi les autres surfaces console affectées. Les reçus et résultats exacts sont conservés dans
le chantier privé `crm-root-qa-20261027-r1` ; ils ne constituent ni une preuve navigateur, ni une preuve
de déploiement, ni une qualification complète du CRM.

Prochaine étape : raccorder les soumissions existantes de M3 au dossier, après vérification du contrat
et des droits, sans réimplémenter le calcul ni ouvrir une action d’envoi.
