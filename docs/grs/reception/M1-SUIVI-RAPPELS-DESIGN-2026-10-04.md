# M1 — suivi humain non terminal des rappels : design adapté

**4 octobre 2026 — tranche 25 qualifiée localement par ROOT r150.**
Contrat adapté à la décision ROOT ; [audit ciblé](M1-SUIVI-RAPPELS-AUDIT-2026-10-04.md)
et [rapport de préparation](M1-SUIVI-RAPPELS-RAPPORT-2026-10-04.md).
M1 global demeure **PARTIEL**.

## Source admissible et propriétaires

Un dossier doit être un transfert `ventes` ouvert, **réellement relié** à une
entrée `appel_importe.reponse.tache_rappel.transfert_id`. Le seul type `ventes`
ne suffit pas. Plaintes, urgences et transferts ordinaires sont hors de cette
tranche. La date de prochaine tentative est du travail M1, pas une disponibilité
ou réservation M4.

Réutiliser [le registre et la projection des transferts](../../../departments/m01-front-office/src/m1_front_office/transferts.py),
[les outils M1](../../../departments/m01-front-office/src/m1_front_office/outils.py),
[l’identité et la mutation console](../../../src/opsys/console/metier.py)
et [la fiche réception](../../../src/opsys/console/frontoffice_marketing.py).
Aucune table, migration, inbox, scheduler ou moteur générique supplémentaire.
Les événements portent le type existant `transfert` ; le statut ouvert dépend
toujours de l’absence de clôture. Les historiques sans suivi gardent leur
comportement actuel.

## Deux actions et projection attendue

- `prise_en_charge` : l’owner ou l’admin actif s’attribue à lui-même un dossier
  libre ; aucun remplacement implicite du responsable.
- `tentative_sans_contact` : seul l’attributaire consigne une tentative et
  choisit explicitement sa prochaine échéance. Le dossier reste dans la file.

La lecture et le succès de mutation exposent `resultat.suivi_rappel` :
`snapshot_suivi` SHA-256, `responsable`, `role`, `pris_en_charge_le`,
`tentatives_sans_contact`, `derniere_tentative_le`, `prochaine_tentative_le`.
Les valeurs non encore connues sont nulles, le compteur est entier. Cet objet
n’inclut aucune donnée client. Les libellés disent « tentative consignée sans
contact » et « prochaine tentative prévue », sans certifier un appel ou un
contact réussi. La clôture humaine N3 reste son action séparée, inchangée.

## Identité et paramètres

Le nouvel outil canonique `m1_consigner_suivi_rappel` est **T1/N2** : ajouté à
`COMMANDES`, jamais à `DECISIONS_HUMAINES`. Il ne demande aucune approbation N3.
Le parcours est réservé à une session humaine owner/admin de console.
Le backend refuse `source=appareil`, même humain actif, et le catalogue ferme
la portée publique de la commande : `roles_appareil=frozenset()`. Le SDK
N2 générique peut rendre un reçu avant le corps M1 ; authentification/rejeu
Core restent à qualifier avant ouverture. Aucun port appareil/admin n’est
livré. Identité absente, rôle retiré et
compte désactivé doivent refuser. Au port métier, relire l’autorité et
l’expiration **avant claim/replay**, puis après l’outil, avant finalisation ;
les routes revalident avant commit/retour. Ne pas assouplir la clôture existante.

Corps navigateur fermé : `action`, `snapshot_attendu`, `mutation_id`, et
`prochaine_tentative_le` seulement pour la tentative. L’identifiant du dossier
vient de la route. Ni acteur, rôle, heure de réalisation ni texte libre.
L’outil reçoit `horodatage` injecté par `metier`, jamais par le navigateur.
L’échéance est obligatoire pour la tentative, interdite pour la prise : ISO
ASCII avec offset, valide et strictement future à l’heure serveur, puis
normalisée UTC. Aucune échéance ou réattribution automatique.

## CAS, transaction et rejeu à vérifier

SQLite durable seulement, factory canonique et **`BEGIN IMMEDIATE`**.
La révision couvre toutes les entrées d’appel importé liées au dossier,
ouverture/clôture, signaux rattachés et événements de suivi. Une arrivée
tardive sur ce dossier invalide le snapshot ; les autres dossiers ne le
modifient pas. Le hash est une révision CAS. Le nouveau suivi ajoute un contrôle de
chaînage interne en mémoire ; aucune ancre externe ou détection de toute
réécriture complète cohérente de la base n’est revendiquée.

Le rejeu exact est traité avant les préconditions métier courantes : reçu
historique autorisé, sans nouvel append. Même clé avec d’autres arguments :
conflit. Nouvelle clé avec snapshot périmé : refus. Chaque succès ajoute un
seul événement ; refus ou exception doivent faire rollback de la réclamation,
des maillons et des journaux dans la transaction jointe. Concurrence sur une
même révision : un seul gagnant. Ces propriétés sont couvertes par la qualification locale ROOT r150.

## Lecture SQL et chaînage interne

Le helper commun [lecture M1](../../../src/opsys/stockage/lecture_m1.py)
borne le premier chargement en transaction SQLite, avant appel au décodeur :

| Plafond inclusif M1/principal | Valeur |
|---|---:|
| Maillons | 10 000 |
| Octets UTF-8 par maillon | 65 536 |
| Octets UTF-8 cumulés | 8 388 608 |

Tout dépassement refuse l’ensemble. Le digest réutilise ce préflight avec ses
constantes inchangées ; son texte conserve sa borne de 32 768 octets UTF-8.
Le périmètre n’est pas étendu à d’autres lecteurs ou départements.

Après cette lecture durable bornée, `Registre(lignes).valider_chaine()`
contrôle le chaînage interne sur les données en mémoire. L’append reste porté
par le registre durable canonique, jamais par cette copie. Une chaîne altérée
refuse le suivi sans append ; ce contrôle ne certifie pas une origine externe.
Un refus métier, même dépourvu de code exploitable, ferme en erreur interne
générique et interrompt la transaction, sans finaliser de succès. Après
l’append, vérifier de nouveau les quotas SQL **avant** la seconde lecture du
registre ; le dépassement doit faire rollback sans décodage post-append.

## Routes privées et qualification

Sous le préfixe réel de la console :

- POST `/reception/transferts/{id}/suivi-rappel` : formulaire fermé, session et
  CSRF, succès 303 vers la fiche ;
- POST `/api/reception/transferts/{id}/suivi-rappel` : JSON fermé et protections
  de session/CSRF de la console, succès selon l’enveloppe métier existante.

Malformed : 400 ; stale/préconditions : 409 ; authentification/autorité :
401/403 ; erreur interne : 503 générique sans contenu client. Aucun réseau,
fournisseur, LLM, notification, CRM, agenda M4 ou clôture implicite.

ROOT r150 couvre un vrai import → prise → tentative → dossier toujours ouvert
après reconnexion SQLite, puis clôture distincte ; source ordinaire exclue,
champs/dates/CSRF invalides, rôle retiré, agent refusé ; replay/conflit,
arrivée tardive, CAS concurrent et rollback forcé avec non-delta des tables.
Préserver les oracles d’import, transfert, clôture et digest : les nouveaux
événements n’ajoutent pas de faux signal/lead/appel aux compteurs. ROOT r150 passe 1 737/1 737 sur 39 fichiers complets, sans échec/erreur/skip ;
PostgreSQL et réattribution restent hors qualification.

Les nouveaux cas SQL/backend doivent utiliser la base réelle et vérifier le
compteur de décodages nul au refus ; un simple 503 ou un mock ne le démontre
pas. Les tests directs de `metier.executer` couvrent expiration et révocation,
y compris sur rejeu, avant la réclamation et à son retour. La campagne finale inclut 61 cas console/SQL/métier et neuf unitaires de
domaine, tous inclus dans les 1 737 ; les mocks de domaine ne sont pas des
preuves SQLite. ROOT r147 reste rouge 1 723P/9F, r148 vert intermédiaire
1 734/1 734 et r149 rouge 1 734P/1F de fixture ; aucun historique n’est effacé.

Le nouvel oracle réussi de dépassement après append utilise une vraie chaîne SQLite
valide de 10 000 maillons, attend 503 et vérifie zéro décodage post-append,
avec toutes les tables META inchangées. L’ancien `m1_lire_transfert` direct
charge encore avant bornage hors wrapper : les nouveaux GET fiche/API et le
nouveau writer sont couverts par le bornage, pas une qualification générale
du lecteur MCP/appareil historique. PostgreSQL reste exclu.
