# CRM-08 — proposer une cédule depuis le devis : audit avant raccord

27 octobre 2026, parent `77cec8bbba546af09382f02451679c409bd57f11`.
Statut **PARTIAL**. Revue indépendante statique puis vérification ROOT des propriétaires.
La première vue de préparation HTTP/SQLite est qualifiée; elle ne propose/applique aucun plan.

## Réutilisation exacte

`m4_proposer_cedule` est T1/N1 : il écrit un brouillon `cedule_proposee`, sans affectation ni
changement d’état. L’argument minimal est `intervention_ids: [id_exact]`, `moteur: auto` et
l’heure serveur. Le port privé ne doit accepter aucune surcharge équipes, durées, compétences,
fenêtres, paramètres ou matrice. Le propriétaire relit les profils équipes/météo et la position
confirmée. Son profil fournit dépôt, quarts numériques, compétences/durée du service,
paramètres et fenêtre par défaut. Ce qui manque demeure un refus nommé, pas un défaut UI.
Sans fournisseur de matrice, le résultat est explicitement bridé (distances approximatives).
Les solveurs déclarés actuellement sont auto/PyVRP/dp; cette tranche n’ajoute pas OR-Tools.

`cedule_tournees.proposer` vérifie la préparation d’une intervention `a_planifier`, construit
l’entrée puis range le plan déterministe. Une proposition identique ne crée pas un second plan.
`instantane_du_registre` et `plan_propose` permettent la future lecture bornée du brouillon.
L’éditeur `cedule_plan_ui` exige un plan appliqué : ne pas y présenter le brouillon.

`m4_appliquer_cedule` est T1/N3, confirmation humaine séparée. Il relit préparation, état,
assignation, localisation, profil et matrice, compare les empreintes puis vérifie le plan.
Il n’est pas appelé dans la première tranche du port de proposition. La confirmation des
dates civiles reste une capacité distincte; les règles météo ne sont pas une prévision.

## Patch minimal et garde-fous

Ajouter un port privé socle/console : session admin SQL vivante, connexion canonique SQLite,
relecture du devis accepté et de son ancre bus complète par `preparation_chantier.lire`.
Première tranche strictement `a_planifier` et prête. Le formulaire futur portera l’empreinte
de cette vue; une préparation/source changée refuse avant toute écriture. L’heure et l’auteur
sont ceux du serveur/session, pas des arguments du navigateur.

Dans un même savepoint : réclamation idempotente console, appel du vrai outil M4, projection
bornée, audit, finalisation du reçu. Échec/refus/retour trop volumineux/échec audit ou reçu
annule toute écriture de la tentative. Un reçu rejoué reste historique, sous autorité actuelle;
il ne donne pas une nouvelle preuve de disponibilité. Aucune portée MCP ajoutée.

Ensuite seulement : route POST CSRF et revue du brouillon exact depuis la fiche devis;
application N3 avec source relue, puis éditeur de dates existant. Aucun envoi client/équipes.

## Qualification prévue et risques

Données fictives et vrais M1/M2/M3/M4/M6 : devis accepté → matériel reçu/réservé → position
confirmée + profils réels → préparation prête → proposition mono-intervention. Vérifier
qu’aucun état ni technicien n’est modifié. Source retirée depuis l’aperçu, profil absent,
quota, admin révoqué, intention contradictoire, rejeu, erreur audit/finalisation : refus ou
reçu historique sans effet supplémentaire, avec instantané complet de la base.

La première qualification portera le port privé; route HTTP, revue persistée, application,
prévision du créneau, navigateur et PostgreSQL restent ouverts. Aucun blocage du moteur
avéré dans cette revue; les prérequis d’instance sont à fournir explicitement.


## Jalon exécuté — port privé uniquement

`src/opsys/console/proposition_chantier.py::{preparer,proposer}` est qualifié localement.
Le préflight relit la vue exacte, les profils équipes/météo et la tête M4. Le POST futur ne
fournira que l’empreinte de cet aperçu et son intention; le port impose lui-même l’intervention
exacte, `a_planifier`, prête, l’auteur SQL actuel et l’heure serveur. Le vrai outil T1/N1 M4
reçoit `intervention_ids: [id]`, `moteur: auto`; aucune surcharge de profil n’est admise.

Après calcul, le port compare le maillon réel à l’intervention, à l’empreinte propriétaire du
profil équipes et à celle de préparation, puis relit les profils pour refuser un changement
observé pendant le dispatch. Cela ne transforme pas des fichiers YAML en une transaction SQL :
une modification de configuration indépendante reste présente si la tentative de proposition
est annulée. La prévision datée et l’application restent hors de ce port.

Le reçu durable réussi est `ok`, sa taille SQL est vérifiée avant décodage. Son enveloppe est
fermée; sa projection est reconstruite depuis le plan propriétaire réel, sans clé libre ni
horodatage d’appareil arbitraire. Le rejeu exige toujours une autorité actuelle et porte
`historique: true`, sans nouvelle affirmation de disponibilité. Le plan, l’audit et le reçu
partagent le même savepoint; refus, quota, panne d’audit et panne de finalisation annulent les
écritures même si l’exception est capturée dans la transaction extérieure.

`tests/test_console_proposition_chantier.py` utilise de vrais profils enregistrés, une
localisation humaine confirmée, une réception M6 et le vrai bus du devis M3 accepté. Aucun
volet de préparation n’est simulé dans cette cohorte privée. Une proposition place le chantier
mais ne modifie ni `a_planifier` ni l’absence d’assignation. Le mode distance bridé est signalé.
Cas vérifiés : profil modifié avant ou pendant calcul, réservation libérée, empreinte fausse,
préparation bloquée, intention contradictoire, révocation avant rejeu, rollback audit/reçu/sortie,
cache altéré et reçu trop volumineux avant son décodeur.

Preuves privées `crm-prefill-qa-20261027-r1` : baseline `crm08-proposal-red-v1` module absent;
`v1` conserve l’import erroné introduit `opsys.audit`, corrigé par le vrai propriétaire `opsys.etat`;
`v2` 70 PASS. Revue indépendante : changement YAML entre contrôle et dispatch, reproduit par
`crm08-proposal-integrity-red-v1` (deux FAIL avec le statut de reçu réussi incorrect). Après
correction, `v3` 72 PASS. Deux charges libres de cache reproduites par `crm08-proposal-cache-red-v1`
(deux FAIL), puis enveloppe/projection fermées. Qualification finale `crm08-proposal-v4` :
**76 PASS, 0 FAIL, 0 SKIP, 13,77 s**, Ruff et vérificateur 297/173 passent; les populations
se recoupent avec la vue et ne s’additionnent pas. Revue statique finale indépendante : aucun
nouveau constat. Commandes, limites, empreintes, JUnit, logs et reçus distincts conservés;
Source en lecture seule, réseau bloqué, homes/tmp privés, 1 CPU/1 Gio/96 tâches.

**PARTIAL** : port privé exécuté sur SQLite. Aucune route de proposition n’est encore ouverte;
la revue persistée du brouillon, le POST CSRF, l’application N3 et le raccord aux dates sont les
prochaines étapes. Pas de qualification navigateur, PostgreSQL, météo distante, OR-Tools nouveau,
mobile ou produit complet. Aucun envoi client, affectation ou date produit par cette tranche.


## Jalon exécuté — formulaire et revue HTTP

`proposition_chantier_ui.py` expose maintenant le formulaire uniquement quand le devis accepté,
l’ancre bus et la préparation M4 relue permettent de proposer pour l’intervention `a_planifier`.
`preparation_chantier.py` affiche ce formulaire après le préflight du port; `crm_ui.py` transmet
le contrôle CSRF existant. Champs fermés : `csrf`, `mutation_id`, `empreinte_attendue`.

- `POST /crm/lead/{lead_id}/soumissions/{devis_id}/propositions-chantier` appelle le port
  atomique sous identité actuelle, puis redirige 303 vers la proposition persistée exacte.
- `GET /crm/lead/{lead_id}/soumissions/{devis_id}/propositions-chantier/{plan_id}` relit les
  sources et le plan M4 réel, puis rend équipe, jour numérique, heures proposées, non-cédulés,
  solveur, provenance et avertissement de distance approximative. Préfixe console conservé.

Le lecteur privé `proposition_chantier.lire` exige le lien exact lead/devis/intervention/plan,
une seule intervention et sa présence dans les visites ou les non-cédulés. Il vérifie la forme
propriétaire de sortie, son empreinte canonique, les copies méta/maillon, l’empreinte d’état et
le `plan_id` recomposé. Une revue indépendante a trouvé qu’une sortie modifiée puis rechaînée
pouvait afficher une équipe inexistante : `crm08-http-plan-red-v1` reproduit un HTTP 200 au lieu
de 503; le contrôle commun des empreintes ferme ce cas avant projection et renvoi de reçu.
Il garantit cette cohérence historique, pas une nouvelle résolution de faisabilité avec une
matrice historique absente. La réécriture cohérente de toutes les preuves sans ancre externe
n’est pas une garantie ajoutée ici.

Les changements d’état/localisation/préparation/équipes détectés sont signalés. La consultation
reste sans effet et la proposition est explicitement historique; aucun bouton d’application,
affectation, date civile, message client ou fausse disponibilité. Les règles météo ne sont pas
une prévision datée. Chaque texte rendu est échappé; sortie HTML bornée à 128 Kio, réponse no-store.

`tests/test_console_proposition_chantier_http.py` qualifie le parcours réel prêt → formulaire →
POST → plan persisté → revue → rejeu, sans affectation ni changement d’état. Les GET conservent
l’instantané complet de la base. Refus vérifiés : CSRF, doublons/champs supplémentaires, auteur/
heure/cible fournis par le client, corps/type excessif, job bloqué, matériel retiré depuis
l’aperçu, intention réutilisée, rôle révoqué et plan d’un autre dossier. Une modification réelle
du profil est signalée à la revue; le rejeu reste sans effet. XSS et quota HTML sont couverts.

Preuves privées du même harnais borné : `crm08-http-red-v1` (formulaire absent avant code);
`v1` 97 PASS avec style à corriger; `plan-red-v1` rouge métier décrit ci-dessus; `v2` 104 PASS
et un prérequis de fixture erroné (second devis d’un lead déjà converti, M2 refuse légitimement).
La fixture corrigée crée un second vrai lead M1, qualifié M2, puis son devis et son intervention,
sans réduire le contrôle de quarantaine. Qualification finale `crm08-http-v3` :
**105 PASS, 0 FAIL, 0 SKIP, 33,05 s**, Ruff et vérificateur 297/173 passent. Les populations
se recoupent, sans addition. Revue statique complémentaire : aucun nouveau constat sur le correctif.

**PARTIAL** : cette interface est qualifiée en HTTP/SQLite. Prochaine capacité : application
humaine N3 du plan exact avec sources relues, puis raccord à l’éditeur civil existant sous ses
gardes. Navigateur, PostgreSQL, prévision distante, mobile et CRM-08 complet restent ouverts.
