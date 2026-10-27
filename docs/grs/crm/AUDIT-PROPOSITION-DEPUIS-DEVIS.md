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
