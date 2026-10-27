# CRM-16 — Audit du journal quotidien des équipes

## Objectif et pourquoi

Remplacer le cahier de la secrétaire par des faits consultables : prévision du jour,
report conservé, reprise quatre jours plus tard, pointages et fin de chantier. Le CRM
montre la vérité propriétaire M4; il ne calcule ni paie ni composition d'équipe supposée.
La demande complète inclut membres historiques, absences, extras et historique annuel.
Cette première tranche n'en réduit pas l'objectif : elle commence par les sources existantes.

## État actuel et fichiers

Inspection statique au parent `4a5c7cde2da7512b9ea865736a74d00a19c11c65`, après qualification
HTTP des coûts CRM-10. Aucun journal quotidien ni registre `work_sessions` trouvé.
`departments/m04-field-ops/src/m4_field_ops/` fournit :

- `calendrier_civil.py` : plans appliqués et maillons append-only `cedule_datee`, révisions et
  fuseau America/Montreal. La projection hebdomadaire expose la dernière date, pas les anciennes.
- `annotations_calendrier.py` : validation des anciennes ancres via `_creneau`, incluant preuve
  proposition/application, révisions, équipe assignée et état au moment de la datation.
- `etats.py` : inscriptions, assignations, transitions et reports motivés; historique append-only.
- `pointage.py` : technicien, intervention, action, heure faisant foi; heure appareil distincte.
- `outbox.py` : fin de travaux et durée première arrivée–dernier départ moins pauses.
- `ecarts.py` : demande d'écart et décision distinctes; aucune approbation implicite d'un extra.
- `temps.py` : brouillon attribué au jour de complétion, pas un temps quotidien multivisites.

Les profils actuels et le solveur ne prouvent pas qui était physiquement avec qui autrefois.
Un pointage sans ancre civile ne prouve pas la visite précise; aucun pointage n'est une absence.
Le workflow ne permet pas encore `sur_site → reportee`, donc la reprise après travail commencé
est un écart distinct à traiter, jamais une histoire reconstruite par l'écran.

## Réutilisation et architecture retenue

Réutiliser le registre M4, ses horodatages et les validateurs des ancres historiques. Aucun
nouveau moteur de calendrier, événement, RH ou paie. La recherche déjà conservée dans
`docs/research/INGREDIENTS.md` (R7, Field Service Management/ERPNext) établit le coût d'une suite
parallèle lourde; aucune nouvelle dépendance ni extraction externe pour cette projection.
Revue ciblée indépendante en lecture seule par `wave1_m4_calendar`, sans runtime ni mutation.

Première tranche : lecteur **pur privé M4**, journée ISO explicite, snapshot validé/borné,
prévisions de chaque révision et faits datés séparés. Réutiliser `_creneau` pour chaque ancre
historique; aucune substitution par la dernière date. Sortie whitelistée, empreinte de source,
ordre déterministe, pagination liée à la source et refus si source changée entre pages.
Ni contacts, coordonnées/GPS, attestation appareil, coût, salaire ni texte de demande brut.
Pas d'heures quotidiennes inventées, pas de calcul financier. Absence, composition historique,
notes/extra détaillés et session multijour restent des sections à raccorder ensuite.

Seconde tranche : port console admin SQL courant, snapshot canonique, contrôle avant/après,
puis GET/écran seulement après qualification du pur. Les nouveaux outils/routes éventuels
suivront les manifestes existants; aucun outil d'appareil ajouté par ce seul lecteur privé.

## Données et workflow

Séparer `prevision` (jour de visite confirmé, ancre/revision/équipe planifiée), `pointage`
(jour local de l'heure faisant foi, technicien sourcé, aucune localisation) et `etat`
(jour local de transition, motif de report si autorisé). Ne pas confondre jour de prévision
et jour où l'admin a créé le plan. Une prévision n'est pas une présence. Une ancienne
confirmation remplacée garde son ancre, avec lien vers la révision suivante, sans réécriture.
Les événements réels sans lien exact de visite sont explicitement non associés à une ancre.

Scénario : plan daté D → report avant arrivée → replanification D+4 → pointage → complétion.
La prévision D/report ne disparaît pas; D+4 reste une autre entrée. Les vraies fonctions M4
écrivent la fixture fictive, puis le lecteur ne fait que lire. Aucune simulation ne devient
une preuve de parcours SQL, terrain natif ou mobile.

## Permissions, risques et gates Nathan

Futur écran réservé admin; vendeur/client/employé exclus de l'historique global. Le pur
n'est pas une API exposée et ne reçoit aucun privilège. Risques : source corrompue, révision
sans application, visites ambiguës, affectation actuelle attribuée au passé, jour numérique
transformé en date, offsets incohérents, fuite GPS, absence supposée, heures multijours
attribuées au mauvais jour. Refuser contrats invalides et sources trop volumineuses.
Aucun nouveau gate humain pour cette lecture réversible. Aucun changement RH, paie finale,
engagement client, production ou déploiement autorisé dans cette tranche.

## Tests et statut

Réutiliser `test_calendrier_civil.py`, `test_annotations_calendrier.py`, `test_pointage.py`
et `test_temps.py`. Ajouter ancien D conservé après D+4, aucune présence déduite d'une date,
localisation/Appareil exclus, jour local/DST, chaîne et ancre invalides, source modifiée entre
pages, bornes, indépendance des conteneurs et registre inchangé. Ensuite parcours réel des
ports SQL/admin/HTTP, révocation et GET sans effets, avant toute qualification de l'écran.

**PARTIAL — audit avant code, journal nouveau non implémenté.** Prochaine action précise :
écrire les premiers tests purs de conservation des deux dates et de minimisation, observer
le rouge, puis implémenter ce lecteur. Membres historiques, absences, extras détaillés, reprise
après démarrage, historique annuel complet, SQL/HTTP/navigateur/PostgreSQL/mobile restent ouverts.

## Première tranche pure qualifiée localement

`journal_quotidien.py::lire` conserve les confirmations D et D+4, y compris celles de plans
différents. `source_courante` et `validite` proviennent de la projection M4 validée : une
ancienne prévision est historique, un report sans nouvelle date reste à reconfirmer. Les
faits pointés sont datés dans America/Montreal à partir de l'heure faisant foi; son origine
serveur/appelant est déclarée par le helper propriétaire. Aucun GPS, appareil, attestation
ou heure appareil brute ne sort. Aucune association exacte de visite n'est inventée.

Le lecteur capture un registre en mémoire, contrôle sa chaîne, limite10000 maillons/8Mio
et1000 prévisions de la journée. Les pages de1 à100 lignes sont ordonnées par instant puis
rang canonique du maillon, avec continuation liée à la tête et au jour. Les bornes SQL avant
décodage restent du ressort du futur adaptateur; le pur ne les prétend pas qualifiées.
Chaque pointage/transition exige une inscription unique antérieure, même hors du jour demandé.

Rouge initial : lecteur absent. Revue indépendante et root : validité absente, départage par
hash et faits orphelins acceptés. `crm16-pure-v3` reproduit3 FAIL et1 PASS : les deux orphelins
et l'absence de validité; le cas de tri choisi était déjà vert, sans fausse revendication de
rouge. Correctifs puis `crm16-pure-v4` :166 PASS en0,62s, dont19 cas du journal et les régressions
calendrier/annotations/pointage/temps. Ruff et vérificateur297/173 passent. Les premières
cohortes2/13 PASS sont incluses, non additionnées. Revue corrective statique indépendante sans
défaut concret résiduel. Les rouges, commandes, pins et limites QA privées sont conservés dans
`CRM16-PURE-LOCAL-QUALIFIED.json` (chantier CRM).

Parcours sur données fictives, avec vraies fonctions pures M4 de planification/application,
datation, report, redatation et pointages : ni simulation présentée comme un appareil réel,
ni nouveau parcours complet de travaux terminés. Le registre reste identique après lecture.

**PARTIAL — composant pur privé seulement.** Aucun nouvel outil exposé, port SQL/admin ou écran.
Prochaine action : outil T0 propriétaire de journal et port console admin sur snapshot canonique
borné avant décodage, comparaison des sources avant/après et tests de révocation; HTTP ensuite.
Membres historiques, absences, extras détaillés, reprise après démarrage, journal annuel complet,
navigateur, PostgreSQL et mobile restent des capacités ouvertes distinctes.
