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

## Décision avant le port SQL privé

Ajouter un outil T0 M4 de journal, fermé aux agents sans personne et aux appels MCP/appareil,
autorisé seulement au contexte console d'un admin SQL actif déjà habilité. Aucun rôle de
compte ni droit de production n'est ajouté. Réutiliser `_autoriser_annotation` et la connexion
canonique SQLite, refuser les registres injectés. Le schéma d'appareil déclare admin pour le
transport console, mais le garde interne exige toujours source/origine console et MCP absent.
Le T0 n'est pas inscrit au catalogue générique de lectures HTTP avant qualification du port.

Avant tout décodage, compter les maillons et leurs octets SQL. Capturer le snapshot avec ses
métadonnées canoniques; appeler le pur qualifié et joindre l'empreinte calculée du snapshot.
Relire source et autorité en dernier. Borner l'enveloppe UTF-8 à la plus petite limite de
sortie applicable, avec refus explicite, jamais une réponse coupée prise pour complète.
La continuation du pur reste liée à sa tête et au jour; l'empreinte de snapshot contrôle aussi
les changements de métadonnées pendant chaque requête. Ce n'est pas une attestation native.

Le port console privé capture indépendamment les sources, construit la projection attendue
par le même propriétaire M4, appelle le vrai T0 et compare toute la réponse. Recontrôler le
snapshot puis l'admin/session en dernier. Tests SQL réels sur données fictives : aucun effet
sur aucune table, rôle/session révoqués, fausse connexion ou registre, réponse altérée, quota
avant JSON, continuation périmée. Aucune route, aucun rendu, ni écriture RH dans cette tranche.

## Qualification locale du T0 et du port privé SQL

`journal_durable.py` capture les maillons et métadonnées SQL après bornes10000/8Mio avant
décodage, puis utilise le pur inchangé. `outils.py::m4_lire_journal_quotidien` exige l'admin
console actif, refuse registre injecté/connexion étrangère et relit source puis autorité.
`console/journal_equipes.py` compare ce vrai T0 à une projection sur sa capture indépendante,
recoupe le snapshot et vérifie l'admin/session en dernier. Toute lecture sans injection
compare l'ensemble des tables avant/après, sans écriture ni réparation. Les mutations de rôle,
métadonnées et données invalides sont des injections fictives explicites de test.

Les deux entrées génériques `Capacites.appeler`/`appeler_profil_runtime` refusent le journal
avant normalisation, factory, reçu ou dispatch. Il n'existe aucune voie de rejeu générique
autorisée pour ce port. Aucun ajout à l'allowlist de lectures HTTP. Le transport console passe
le rôle admin existant; aucun compte, rôle de personne ou droit de production n'est modifié.
Le schéma compte désormais298 outils/174 déclarés, dont173 dans la portée nominale admin;
`ROLES.md` explique la restriction console, plus étroite que cette déclaration de transport.

Historique : port/outil absents reproduits par2 FAIL. Le premier test avait un import de
candidat erroné intercepté au lint, corrigé avant exécution. Les négatifs suivants ont révélé
9 FAIL/8 PASS : nouveaux codes de refus non catalogués provoquant `CodeVerdictInconnu`.
Six codes fermés ont été ajoutés au catalogue et à son oracle. Deux rouges supplémentaires
ont prouvé l'absence de garde privée précoce des répartiteurs; leur première occurrence
incluait aussi un mauvais nom d'API dans le test profilé, corrigé et conservé séparément.
Ni ce mauvais nom ni le refus lint ne sont des bugs produit.

`crm16-port-v3` :170 PASS/1 FAIL en11,80s, dont20 contrôles SQL/journal tous PASS; seul échec :
compteurs documentaires de rôles encore173/297. Documentation corrigée sans toucher au produit,
puis `v4` :1 PASS en0,87s pour ce contrôle exact, avec tous les pins produit/tests v3 inchangés.
Populations recoupées, non additionnées. Ruff et vérificateur298/174 passent. Revue corrective
statique indépendante sans défaut concret résiduel. Preuves : `CRM16-PORT-LOCAL-QUALIFIED.json`,
commandes, JUnit, logs, pins, limites effectives du QA privé; aucun appel modèle ou réseau métier.

**PARTIAL — T0 et port privé SQLite qualifiés localement, aucun écran.** Prochaine action :
GET admin du journal avec page/continuation et lien depuis la cédule, dernier contrôle SQL
après rendu, source/validité et avertissements explicites; tests HTTP sans effets et révocation.
Rapprochement exact visite/pointage, heures par jour, absences, membres historiques, extras,
historique annuel complet, navigateur, PostgreSQL et mobile demeurent ouverts.

## Décision avant le GET du journal

GET `/crm/journal-equipes` avec jour ISO explicite, offset/limite canoniques, continuation
par source; clés inconnues ou répétées refusées avant lecture. Liens pour les sept jours
depuis la cédule hebdomadaire et navigation des pages du même jour. Réutiliser uniquement
le port SQL qualifié, conserver sa transaction pendant le rendu, quota HTML128Kio et contrôle
SQL admin/session en dernier avant réponse. Valeurs échappées et protection no-store/CSP
existante. Aucun formulaire de mutation, ajout d'absence, correction de pointage ou export RH.
Une réponse de source refusée affiche une indisponibilité; ne jamais substituer une page vide
ou un ancien résultat. Qualification HTTP distincte de la validation en navigateur natif.

## Qualification locale de l'écran HTTP

Le GET est raccordé depuis chacun des sept jours de la cédule. Il montre séparément prévisions
avec début/fin et validité, pointages et changements d'état; les pages gardent jour et source,
le retour à la cédule garde la semaine consultée. Aucun rôle, date civile ou fait terrain
n'est inféré d'une cellule vide. Le port SQL qualifié et les fonctions `_t0`/`lire` restent
inchangés; lecture, rendu, plafond HTML et dernier contrôle admin/session partagent la même
transaction. Aucun formulaire de mutation; les refus ne contiennent pas d'identifiant de job.

`crm16-http-v2` :119 PASS en38,47s, dont16 cas HTTP du journal et régressions du port, cédule,
pagination et CRM. Journée vide, trois pages complètes sans perte/doublon, requêtes fermées,
accès interdit, révocation pendant rendu, échappement, plafond HTML, source périmée et anciennes
prévisions/report/reprise D+4 vérifiés en HTTP/SQLite avec données fictives. no-store/CSP présents.

La revue indépendante a trouvé un faux message « journée vide » pour une page après la dernière
entrée (`debut == total > 0`, autorisé par le pur). Rouge HTTP1 FAIL conservé. Le rendu distingue
maintenant page vide et journée vide et propose la première page. `v3`3 PASS en2,10s couvre ce
cas et deux parcours déjà inclus, avec correctif limité à cette branche. Les cohortes ne sont
pas additionnées. Ruff et vérificateur298/174 passent. Le premier rouge de route404 et le refus
lint préalable sont conservés distinctement. Preuve : `CRM16-HTTP-LOCAL-QUALIFIED.json`.

**PARTIAL — journal en consultation admin HTTP/SQLite qualifié localement.** Aucun navigateur
natif, PostgreSQL, mobile ou parcours terrain réel complet nouveau. Rapprochement exact des
visites et pointages, heures par jour, membres historiques, absences, extras détaillés et
historique annuel complet restent ouverts. Prochaine action : publier normalement les commits
qualifiés après CI parent terminale, puis traiter un de ces écarts depuis ses sources M4.

## Décision avant le raccord des notes rapides

Réutiliser `annotations_cedule_ui.ancre_de/url` et l'écran existant
`/crm/cedule/annotations`, dont les vrais outils M4 relisent l'ancre et l'autorité courantes.
Depuis chaque ligne de prévision du journal, proposer « Notes et historique » avec les quatre
références exactes. Une ancienne date doit mener à son ancien créneau, pas à la dernière date.
Aucun lien de note pour pointage ou changement d'état sans ancre civile démontrée.

Première tranche : navigation vers l'écran existant, aucune copie de texte ou compteur de
notes dans le journal. Son snapshot reste donc celui des faits M4 seulement; ne pas lui
attribuer une preuve de contenu des annotations non lues. Préciser la portée de l'avertissement
pur : les textes des notes ne font pas partie de sa projection. Pas de nouveau modèle, outil,
rôle de personne, formulaire d'écriture ou automatisme. Le writer existant garde CSRF, révision,
rejeu, piste d'audit et fermeture des anciennes ancres aux nouvelles notes.

Qualifier le parcours HTTP réel journal → notes → création autorisée → report/redatation D+4
→ consultation des deux ancres, sans transfert ni écrasement. Vérifier liens de prévision
seulement, ancien créneau en lecture seule, rôle révoqué, CSRF et GET sans écriture. Si des
badges/compteurs ou du texte sont intégrés ensuite, leur preuve nécessitera une capture bornée
du registre des notes et une référence composée, avant/après toutes les lectures.

## Qualification du raccord des notes et correction d'autorité

Chaque prévision propose maintenant le lien exact vers son écran « Notes et historique ».
Les pointages et changements d'état sans ancre n'en reçoivent aucun. Le journal ne lit ni
ne copie les textes/compteurs : une note nouvelle ne change pas son snapshot de faits M4,
ce qui a été vérifié; le détail propriétaire des notes affiche et source son propre contenu.
L'avertissement pur précise cette séparation sans modifier ses calculs ou sa pagination.

Le parcours a aussi prouvé un défaut existant du GET des annotations : après révocation de
l'admin pendant `gabarit`, la réponse contenait encore la note fictive avec HTTP200. Ce rouge
est conservé dans `crm16-notes-privacy-red-v1`. Le détail et son rendu partagent maintenant la
connexion canonique, avec contrôle SQL admin/session avant lecture et après rendu, et plafond
HTML128Kio avant réponse. Le même scénario retourne403 sans la note. Le POST et le métier
M4 d'enregistrement sont inchangés; aucune attribution de rôle de compte ou donnée réelle.

`crm16-notes-v2` :57 PASS en12,18s, dont7 cas nouveaux de raccord et les régressions des notes,
du journal HTTP et du journal pur. Création autorisée depuis le lien, CSRF, rôles SQL, report
et redatation D+4, conservation exacte de la note d'origine, ancienne ancre en lecture seule,
nouvelle note sur la bonne ancre, échappement, limites HTML et GET sans écriture sont vérifiés.
L'ajout de pointage du test de rendu est une charge contractuelle fictive, pas une nouvelle
exécution d'appareil terrain. La première cohorte21 PASS est incluse, non additionnée.
Ruff et vérificateur298/174 passent. Revue indépendante statique sans défaut concret relevé.
Preuve détaillée : `CRM16-NOTES-LOCAL-QUALIFIED.json`, avec rouges, commandes, JUnit, pins et
limites effectives du QA privé.

**PARTIAL — navigation et lecture des notes qualifiées en HTTP/SQLite.** Aucun nouveau writer,
outil, modèle ou formulaire. Les badges/compteurs de notes dans le journal, les extras détaillés,
heures par jour, absences, composition historique, navigateur, PostgreSQL et mobile restent
ouverts. Prochaine action : commit local, qualification CI parent, puis lecture des demandes
d'écart/arbitrages M4 dans le journal sans les présenter comme une facturation d'extras.

## Décision avant la projection des écarts déclarés et arbitrés

Réemploi inspecté : `ecarts.creer_demande_ecart` écrit `demande_revue/ecart_metier` avec
versions exactes durée/périmètre/matériaux; `resoudre_demande` ajoute `resolution_revue`, sans
réécrire la demande. Identifiants propriétaires : empreinte de `demande_revue`/intervention/
horodatage, puis `resolution_revue`/demande/horodatage. La validation d'un écart métier produit
un WCT `completed_pending_review`; l'anomalie GPS appartient à la même famille de demandes
mais reprend `sur_site` si validée. Ne pas fusionner ces sens ni utiliser seulement l'intervention.

Ajouter au journal pur deux événements distincts, chacun daté selon son heure faisant foi.
Déclaration : en attente à cet instant; arbitrage : décision source, séparée, même si un autre
jour. Exiger demande unique antérieure, même intervention, résolution unique, identifiants
déterministes, inscription unique antérieure, versions validées par le propriétaire et
décisions fermées. Inclure tous les types de demandes dans l'index de collision, mais ne
projeter comme écarts que `ecart_metier`. Une résolution orpheline/avant sa demande ou un
doublon ne doit jamais devenir un fait affiché. Les anomalies GPS restent exclues de ce volet.

Sortie minimale : références/IDs, instant/origine, décision et noms des dimensions modifiées.
Ne copier ni périmètre libre, matériaux, motif libre, heure appareil, prix ou coût. Comparer
les dimensions déclarées ne prouve pas une durée travaillée ni un extra facturable; ces
derniers relèvent des propriétaires M3/M5. Aucun statut opérationnel, facture, paie, rôle,
table ou événement n'est écrit par cette lecture. Le snapshot principal M4 contient déjà
ces maillons; son mécanisme canonique et sa continuation peuvent être réutilisés.

Qualification prévue : vraies fonctions pures de `test_ecarts._registre_sur_site`, déclaration
puis décision un autre jour, invariance du registre; références étrangères, doublons, IDs
altérés, résolutions orphelines et collision avec anomalie GPS. Réutiliser les régressions
d'arbitrage M4; adapter le T0/rendu seulement après qualification pure. Aucun nouveau parcours
terrain réel ou accord de facturation n'est revendiqué par ces fixtures fictives.


## Qualification des déclarations et arbitrages M4

La projection expose désormais `ecart_declare` et `ecart_arbitre` au jour local de chacun,
avec références à la demande, à ses maillons et aux seules dimensions modifiées. La déclaration
reste « en attente » à son instant même si une décision intervient plus tard. Aucun périmètre,
matériau libre, motif d'arbitrage, heure appareil, coût ou quantité de durée n'est recopié.
L'écran précise que l'arbitrage M4 ne constitue pas une décision sur un extra facturable M3/M5.
Les nouvelles lignes n'obtiennent pas de lien de note sans ancre civile démontrée.

La revue de la première candidate a prouvé cinq acceptations erronées : décision inversée avec
statut cohérent, transition compagnon retirée, mauvais identifiant de revue WCT, indicateur
`ecart_signale` faux et demande ajoutée après état terminal. Les cinq rouges sont conservés.
La projection vérifie maintenant le préfixe historique propriétaire et la transition immédiate
exacte, ainsi que les invariants WCT et leur liaison à la demande. La demande initiale depuis
`planifiee`, permise par le writer sans présence sur place, reste valide. Les anomalies GPS
partagent l'index de collision mais ne deviennent jamais des écarts métier affichés.

`crm16-ecarts-v3` : 99 PASS en 0,33s, incluant 24 cas de projection des écarts, les 56 cas du
propriétaire écarts et les 19 du journal initial. `crm16-ecarts-http-v3` : 72 PASS en 15,00s,
incluant quatre cas SQL/HTTP nouveaux, les 20 du port privé, les 17 du journal HTTP, les sept
du raccord des notes et les 24 cas purs. Ces populations se recoupent et ne sont pas additionnées.
Les quatre cas SQL/HTTP passent aussi isolément dans v2. Les écritures de fixture passent par
les vraies fonctions propriétaires et le stockage canonique SQLite : aucune nouvelle preuve
MCP/appareil ni parcours terrain réel n'en découle. Les GET/refus conservent toutes les tables.
Pagination liée au snapshot, refus non-admin et révocation pendant rendu restent vérifiés.

Le premier rouge HTTP503 pour les nouveaux types et le refus préalable Ruff (deux défauts de
présentation/import de la candidate) restent historiques, distincts d'un défaut du produit
publié. Ruff et vérificateur 298 outils/174 déclarés passent. Revue indépendante statique finale
sans défaut concret relevé; aucun runtime supplémentaire de l'agent de revue.
Preuve : `CRM16-ECARTS-LOCAL-QUALIFIED.json`, reçus/pins/JUnit et limites privées joints.

**PARTIAL — écarts minimisés qualifiés localement en pur/HTTP/SQLite.** Aucun writer, schéma,
rôle de compte ou effet financier ajouté. Composition réelle historique, absences, heures
quotidiennes, association exacte des visites/pointages, détails et approbation des extras,
navigateur, PostgreSQL et mobile restent ouverts. Prochaine tranche serveur : établir depuis
les sources M4 une association démontrable visite/pointage, avec ambiguïtés explicites et sans
déduire une présence à partir d'une simple prévision.


## Décision avant l'historique des assignations

Inspection de `pointage.enregistrer_pointage` : le maillon propriétaire contient intervention,
technicien, action et heure, mais aucune des quatre références de visite civile. Le contrôle
de technicien relit la transition `en_route`, pas une ancre de calendrier. Une coïncidence de
jour/heure/technicien ne suffit donc pas à rattacher le pointage à une prévision précise,
particulièrement après report ou redatation. Ce rattachement reste ouvert et nécessite un
contrat propriétaire explicite avant modification des writers; ne pas l'inventer au journal.

Une capacité serveur existante et exploitable est en revanche l'historique d'assignation :
`etats.assigner_technicien` écrit `assignation_technicien`, sans modifier le statut; le départ
`en_route` consigne aussi le technicien envoyé. Première tranche : afficher la décision
historique d'assignation et l'identité consignée au départ, à leurs propres instants, sans
présenter ces décisions comme une présence ou une composition d'équipe réellement observée.

La lecture devra exiger inscription antérieure unique, identifiant technicien textuel non vide,
horodatage propriétaire et état historique non terminal pour l'assignation. Reprendre la fonction
`statut_courant` sur le préfixe plutôt qu'un dernier état global qui réécrirait le passé. Les
réassignations successives restent deux faits, sans écraser les anciennes ni inventer un rôle
salarié/équipe. Sortie en liste blanche : source/intervention, instant/origine et technicien
assigné; pas de coordonnées, nom, permis, coût, note ou liste de membres. Aucune ancre de visite
ni lien de note pour cette décision non liée au calendrier. Le rendu distinguera explicitement
« technicien assigné » de « technicien du pointage » et « équipe prévue ».

Tests avant code : vraie assignation propriétaire avant/après report et deux jours distincts,
départ avec technicien consigné, invariance des données, pagination sans perte et conteneurs
indépendants; source orpheline/double/future, état terminal, identifiant invalide. Puis SQL/HTTP
sur fixture canonique propriétaire : libellés sans ambiguïté, échappement, pas de lien de note
inventé, rôle courant et absence d'écriture. Les régressions écarts/notes/journal sont conservées.


## Qualification de l'historique d'assignation

La projection et le journal HTTP distinguent maintenant les décisions d'assignation, le
technicien consigné au départ, l'équipe du plan et le technicien ayant pointé. Les deux
premiers restent des décisions opérationnelles sourcées et ne reconstituent pas une présence,
une absence ou les membres réels d'une équipe. Après report, l'assignation d'origine reste
visible à son jour et la nouvelle décision apparaît au sien. Ni le dernier technicien courant
ni le dernier calendrier ne remplacent les événements passés. Toute ligne hors prévision
reste sans ancre de note civile inventée.

La revue indépendante a trouvé une incompatibilité de la candidate : `_texte` rejetait un
identifiant composé d'espaces alors que les deux writers historiques acceptent toute chaîne
non vide. Le test par les vraies fonctions a reproduit ce refus; rouge conservé. La lecture
s'aligne sur leur contrat sans normaliser la valeur source. L'interface indique alors
« Identifiant à vérifier (espaces uniquement) » sans modifier le registre ni inventer un employé.
Les identifiants vides/non textuels, inscriptions orphelines/futures/doubles, assignations après
état terminal et départs sans préfixe `planifiee` cohérent sont refusés.

La cohorte pure `crm16-assignations-v3` passe : 52 PASS en 0,30s, dont neuf cas nouveaux; les
19 contrôles du journal initial et les 24 des écarts sont inclus, sans cumul. La cohorte
`crm16-assignations-http-v3` passe : 102 PASS en 16,69s, dont quatre nouveaux cas SQL/HTTP,
neuf cas purs et les régressions accès/notes/écarts/journal. Les cohortes 51 et 100 PASS
antérieures sont recouvertes, pas additionnées. Ruff et vérificateur 298/174 passent.
La revue indépendante finale ferme le constat de compatibilité et ne relève aucun autre
défaut concret. Le lecteur privé T0, ses refus et l'autorité SQL finale restent inchangés.
Preuve : `CRM16-ASSIGNATIONS-LOCAL-QUALIFIED.json` et reçus/pins/JUnit privés bornés.
Les rouges de fonctionnalité absente et HTTP503, refus Ruff préalables et erreur de
compatibilité sont des constats de candidate conservés, pas des réparations silencieuses
ni une qualification de l'ensemble du produit.


**PARTIAL — décisions historiques d'assignation qualifiées localement en pur/HTTP/SQLite.**
Aucun writer, schéma, compte ou rôle ajouté. Rattachement exact des pointages aux visites,
composition réelle historique, absences, paie/heures quotidiennes et extras détaillés restent
ouverts; navigateur, PostgreSQL et mobile non qualifiés. Prochaine capacité serveur à inspecter :
les événements propriétaires de composition d'équipe existants et leur historisation, avec
révocations/retraits explicites; ne pas en déduire une présence terrain ou une fiche RH.


### Précision du libellé et prochaine source de composition

Le contrat natif `opsys.equipes` précise que l'identifiant d'équipe peut occuper le champ
`technicien_id` d'une assignation. La colonne porte donc « Personne ou équipe assignée », avec
cette précision visible, sans résoudre l'identifiant en noms ou membres actuels. Le cas d'une
assignation native à `eq-a` est vérifié en SQL/HTTP : ID conservé, aucun membre inventé, GET sans
écriture. `crm16-assignations-http-v4` : 5 PASS en 2,97s, dont les quatre cas HTTP déjà inclus
et ce cas nouveau; aucun cumul. Seuls le libellé et son test changent depuis la qualification
précédente; aucune logique de projection ou d'autorité modifiée.

Inspection de `opsys.equipes.enregistrer_equipes` : le profil courant remplace sa clé entière.
L'audit conserve IDs d'équipes, nombres de membres et empreinte, explicitement aucun nom de
membre. Cette preuve n'autorise pas la reconstruction des membres historiques depuis le
profil actuel ou des seuls compteurs. La prochaine tranche doit donc définir une source
historique déclarative minimale et sa provenance, distincte des décisions d'accès courantes,
sans enrichir rétroactivement l'ancien audit ni prétendre prouver la présence réelle.


## Contrat avant la composition journalière déclarée

Objectif CRM-16 : conserver la composition qu'un admin déclare pour une équipe et un jour,
puis ses corrections, sans prétendre constater qui était effectivement présent. Le profil
courant et son audit sans membres ne permettent pas cette reconstruction. Une déclaration
porte deux temps explicites : jour civil visé et horodatage d'enregistrement; une correction
faite aujourd'hui d'un ancien jour n'est pas présentée comme connue ce jour-là.

Réemploi choisi : `Registre` M4, son support durable existant et les patrons auteur/mutation/
révision des annotations. La [bibliothèque eventsourcing](https://github.com/pyeventsourcing/eventsourcing)
et sa [licence](https://github.com/pyeventsourcing/eventsourcing/blob/9.5/LICENSE) ont été examinées
comme piste; aucune version, dépendance ou extraction n'est adoptée. La [recherche GitLab](https://gitlab.com/explore/projects/topics/Event%2BSourcing)
n'a pas fourni de raccourci métier démontré pour ce contrat. Ajouter une seconde infrastructure
événementielle dupliquerait ici le stockage propriétaire déjà utilisé; aucun gain de temps
chiffré n'est revendiqué. Aucun package installé ni code externe copié.

Première tranche pure : module `composition_journaliere.py`, registre distinct
`compositions_journalieres`, type fermé `composition_journaliere`, clé `(jour,equipe_id)`.
Données : identifiants uniquement, `statut_declaration` (`declaree` ou `retiree`), membres
triés sans doublons (50 maximum), révision, lien précédent exact de la paire, auteur admin,
mutation d'intention et horodatage. Liste vide = liste explicitement vide; aucun maillon ou
retrait explicite avec `membres=None` = composition inconnue. Retrait sans déclaration active
refusé. Une nouvelle déclaration peut suivre un retrait. Pas de nom libre, permis, santé,
GPS, note, coût, heure travaillée ou sanction. Identifiants pures : textes bornés sans contrôle
ni espaces en bordure; validation de l'identité canonique par le futur adaptateur, sans copier
la grammaire socle ni affirmer l'existence SQL dans cette tranche.

CAS par paire, rejeu exact avant CAS, unicité globale `(appareil,cle)` et empreinte sur arguments
normalisés dont révision attendue. Rejeu d'une ancienne révision après correction retourne son
ancien accusé, sans ramener l'état courant en arrière. Même clé avec autre auteur/arguments =
conflit. Accusé sans liste de membres pour éviter sa copie dans les journaux génériques.
La chaîne ET le schéma fermé, liens/révisions/horodatages/mutations seront vérifiés à la lecture,
y compris après rechaînage. Pagination de l'historique liée à la paire et à la tête entière.
Pas de remplissage automatique depuis le profil courant, de disparition des anciens membres
désactivés, d'exclusivité entre équipes, d'accès conféré ni de pointage/paie déduit.

Bornes : 10 000 maillons, 8 Mio UTF-8 avant décodage côté futur adaptateur; contrôles purs avant
lecture et après capture, réponse/enveloppe UTF-8 bornée avant append et retour, maximum 100
lignes par page. Utiliser des octets, pas la limite en caractères du helper des annotations.
Tests : deux journées indépendantes; correction et retrait/rédéclaration; doublon de membre,
arguments/roles invalides; CAS et rejeu ancien/conflits; invariance et copies indépendantes;
registre corrompu/rechaîné invalide, schéma et mutation incohérents; pagination périmée et quotas.

Cette tranche pure n'est ni un port SQL/admin ni un formulaire utilisable. Les futurs ports
vérifieront l'admin SQL actif avant/après, la source et les identités canoniques, CSRF, transaction
et reçus bornés. Ils n'utiliseront jamais cette histoire déclarative dans `equipes_de`, `acces`,
les permissions courantes, disponibilités ou paie. Aucune donnée réelle ni nouveau droit.
Statut attendu après tests purs : **PARTIAL — fondation déclarative pure**, pas capacité CRM
complète; branchement durable et journal/admin à qualifier ensuite.


### Qualification de la fondation pure des compositions déclarées

`composition_journaliere.declarer/lire` conserve les révisions par paire jour/équipe dans le
registre séparé prévu. La dernière déclaration connue, son retrait explicite et l'historique
restent distincts. Deux équipes peuvent déclarer le même identifiant sans que cela prouve un
chevauchement de présence. Rejeu exact d'une ancienne révision après correction : ancien accusé,
aucun retour arrière. L'accusé ne contient pas les membres; la lecture ne renvoie pas les
mutations. Copies indépendantes, validation de chaîne ET sémantique fermée, précédents/révisions,
unicité globale d'intention, horodatages par paire et plafonds UTF-8 sont exercés.

`crm16-composition-v4` : **173 PASS en 0,88s**, dont 30 cas de cette nouvelle fondation et les
régressions registre/annotations/couleurs/journal/écarts/assignations. Aucun cumul avec les
cohortes précédentes. Ruff et vérificateur 298 outils/174 déclarés passent. Revue indépendante
statique sans défaut concret relevé; aucun runtime de l'agent de revue.

Historique conservé : rouge de module absent; `v1`20 PASS et une erreur de fixture (tri d'une
chaîne avant appel du produit), corrigée sans la présenter comme bug produit; `v2`172 PASS et
un refus du catalogue figé des types, mis à jour explicitement pour le seul nouveau type
inspecté; `v3` refus préalable Ruff sur le commentaire de ce test, sans exécution produit.
Le code produit de v2 est inchangé dans v4; le catalogue de régression reste fermé et vérifié.
Preuve détaillée : `CRM16-COMPOSITION-PURE-LOCAL-QUALIFIED.json` avec commandes, reçus, pins,
limites effectives et JUnit.

**PARTIAL — fondation pure seulement.** Aucun outil, formulaire HTTP, nouveau droit, port SQL,
contrôle d'identité courante, mémoire M10, politique RH ou preuve de présence ajouté. Rien n'est
lu ni écrit dans le profil entreprise courant. Prochaine tranche : source durable bornée et
port privé admin, avec résolution des identités et autorité canonique; ensuite formulaire et
historique dans le CRM. Ne pas marquer la composition historique CRM disponible avant ces preuves.


## Contrat avant la lecture durable privée des compositions

Prochaine tranche serveur : une lecture de l'histoire déclarative déjà écrite, via vrai outil
propriétaire T0 et port privé console. Le formulaire et le writer admin restent à suivre; les
fixtures pourront écrire par le pur sur `stockage.maillons` canonique sans prétendre démontrer
une saisie HTTP ou une autorité d'appareil. Aucune composition créée depuis le profil courant.

Réemploi de `journal_durable` : capture SQL canonique SQLite, compte et octets UTF-8 avant
décodage, `copier_maillons_avec_metadonnees` et empreinte calculée incluant rang/metadata.
Nouveau wrapper `composition_durable` fixé au registre `compositions_journalieres` seulement.
La projection pure fournit le jour/équipe explicitement demandés, historique et dernière
composition connue, puis snapshot calculé. Plafond d'enveloppe selon le contexte et 64Kio.

Nouveau T0 `m4_lire_composition_journaliere_console` : double autorité console admin SQL actif,
origine console et MCP absent; `_cnx_durable` refuse les registres injectés et la connexion
étrangère. Capture → projection → quota → recapture de source → autorité finale. La forme
nominale `roles_appareil={admin}` ne confère aucun droit de compte ni accès d'appareil direct.
Les répartiteurs `appeler` ET `appeler_profil_runtime` ferment le nom avant factory, normalisation
ou reçu générique : les identifiants de membres n'y sont jamais recopiés.

Port `console/compositions_equipes` : autorité/session SQL avant, capture indépendante/projection
attendue, vrai T0 propriétaire, comparaison exacte, recapture de metadata, borne de sortie et
autorité SQL/session finale. Retour privé sans champ inventé; aucune écriture. Une identité de
membre désactivée aujourd'hui demeure une donnée de déclaration historique; lire l'histoire
ne filtre ni ne réattribue les membres d'après les comptes/profils actuels. La validation des
identités lors d'une nouvelle déclaration appartient au futur writer, pas à cette lecture.

Tests SQL canoniques fictifs : écrire/corriger/retirer par les fonctions pures, relire après
réouverture de transaction, dernier état et ancien historique, pagination, source et aucune
écriture; refus agents/MCP/appareils même admin et non-admin/expiré; connexion étrangère,
registre injecté, source/metadata altérées, réponse T0 falsifiée, révocation lors de la dernière
capture, quota SQL avant décodage, enveloppe UTF-8 et deux répartiteurs fermés avant effet.
Régressions journal/annotations/composition pure et catalogue rôles/outils ciblés. Aucun nouveau
writer, compte, endpoint HTTP, M10, PostgreSQL, mobile, paie ou preuve de présence revendiqué.


### Qualification de la lecture durable privée

Le nouveau T0 privé et le port console lisent maintenant les compositions depuis le vrai
registre séparé SQLite, avec snapshots calculés indépendants, métadonnées recoupées et admin
SQL/session avant et après. Les identifiants historiques inactifs restent visibles dans leur
déclaration; aucun membre n'est substitué depuis le profil courant. Les GET futurs devront
encore garder l'autorité finale après rendu : aucun endpoint HTTP ajouté dans cette tranche.

`crm16-composition-port-v3` : **150 PASS en 12,77s**, dont 20 cas nouveaux de source/port privés,
30 purs, 20 du journal privé et les régressions verdicts/rôles. `v4` : **116 PASS en 1,17s** pour
le catalogue natif des portées et les compteurs documentaires. Les populations se recoupent,
aucun cumul. Ruff et vérificateur **299 outils/175 déclarés** passent; le transport nominal admin
est le seul ajout, fermé aux deux répartiteurs génériques et à MCP/appareil/agents directs.
Aucun compte ou droit de personne n'a été modifié hors des fixtures fictives.

Les refus sont exercés : identités/sessions non autorisées, connexion étrangère, registre
injecté, mutation des métadonnées, réponse T0 altérée, révocation après dernière capture,
source illisible ou invalide, pagination périmée et quota avant décodage/retour. Source valide
24 révisions × 50 identifiants : grande page refusée sans contenu, petite page encore lisible.
Les instantanés de toutes les tables confirment l'absence d'écriture des lectures/refus non
injectés. Les écritures de préparation des tests passent par le domaine pur et le vrai support;
elles ne sont pas une preuve de formulaire, approbation SQL d'écriture ou appareil terrain.

Historique conservé : T0 absent au rouge initial; refus Ruff avant exécution; v2 neuf PASS et
huit FAIL dus aux nouveaux codes non catalogués, puis ajout explicite des six codes fermés et
de leurs attentes; rouge quota reproduit (mauvaise classification SOURCE-INVALIDE), puis
préservation des refus de volume dans le wrapper. Revue indépendante finale : deux constats
fermés, aucun autre défaut concret. Aucun runtime ni mutation du relecteur.
Preuve : `CRM16-COMPOSITION-PORT-LOCAL-QUALIFIED.json`, reçus/pins/JUnit et limites privées.

**PARTIAL — lecture privée propriétaire qualifiée en SQLite, sans écran ni writer admin.**
Aucune interface de déclaration, résolution des identités à l'écriture, mémoire M10, preuve
de présence, PostgreSQL, navigateur ou mobile revendiquée. Prochaine tranche : affichage HTTP
admin avec source/temporalisations/inconnu-vide-retrait explicites et autorité après rendu,
puis saisie signée sous CSRF et identités canoniques sans modifier le profil ni les accès.


## Contrat avant l'affichage HTTP des compositions déclarées

GET privé `/crm/journal-equipes/composition` : jour civil et identifiant d'équipe explicites,
paramètres uniques fermés, reprise paginée avec source exacte. Réemploi du port T0 qualifié,
du parseur strict du journal et du gabarit admin. Source/lecture/rendu/limite HTML128Kio et
contrôle SQL admin/session final partagent la transaction canonique. Cache interdit et CSP
existante conservés. Aucun POST, formulaire de déclaration, auto-remplissage ou effet métier.

Afficher séparément : inconnu sans déclaration, retrait, liste explicitement vide, liste
courante et historique; jour visé et instant d'enregistrement distincts. Un ID de membre
historique n'est pas remplacé par son nom ou son état de compte actuel. Le texte rappelle la
nature déclarative et l'absence de preuve de présence/droit courant. Échapper tous les champs.
Aucune mutation, appareil, GPS ou note libre n'est rendu; empreinte de snapshot calculée.

Navigation depuis la prévision du journal uniquement, vers son équipe et son jour. Ce lien
concerne la déclaration journalière de l'équipe, sans rattacher les membres à cette intervention.
Ne pas supposer qu'un technicien pointé/assigné représente une équipe. Le journal ne lit aucun
membre/compteur de composition : son snapshot principal ne change pas pour ce simple lien.

Preuves HTTP avec vrais stockage, T0 et gabarit : rouge404; inconnu/vide/retrait/corrections,
liens exacts sans texte de membre copié dans le journal, pages et continuation périmée, rôles,
échappement, limite HTML, autorité révoquée pendant rendu et aucune écriture des GET/refus
non injectés. La préparation pure de fixtures n'est pas une preuve d'écriture HTTP autorisée.


### Qualification de l'affichage HTTP

L'écran admin affiche désormais dernière composition déclarée et historique via le port T0,
en distinguant inconnu, liste explicitement vide et retrait, ainsi que jour visé et instant
source d'enregistrement. Les identifiants restent ceux des déclarations; aucun nom, profil
courant, statut de salarié ou présence réelle n'est substitué. Source calculée et pagination
explicites, retour au journal, contrôle SQL admin/session après rendu dans la transaction,
plafond HTML128Kio, no-store et CSP. Aucun POST ni nouvelle écriture exposé.

Le journal ne fait qu'ajouter un lien depuis une prévision, pour l'équipe et la journée exactes.
Une nouvelle composition ne modifie pas son snapshot principal, ne lui ajoute aucun membre ou
compteur et n'attribue aucun membre à l'intervention. Les faits/assignations sans source d'équipe
civile ne reçoivent pas ce lien. La revue a trouvé des IDs historiques valides pour les tournées
mais non représentables par ce nouveau contrat (65 caractères ou espace en bordure). Deux
rouges par vrais plans purs DP/appliquer/confirmer ont reproduit les liens inutilisables.
Le lien n'est maintenant émis que si la clé exacte passe les validateurs de la cible; sinon
message explicite « Composition non consultable pour cet identifiant historique », sans
normalisation ni fausse composition inconnue. Le lien de notes d'origine reste disponible.

`crm16-composition-http-v2` : **63 PASS en18,94s**, incluant 17 nouveaux cas HTTP/SQLite, deux
cas de rendu sur plans purs historiques et les régressions port privé/journal HTTP/notes.
La cohorte v1 de61 PASS est incluse, pas additionnée. Ruff et vérificateur299/175 passent.
Révocation pendant le vrai gabarit :403 sans membre; HTML trop grand :503 borné; identifiants
échappés; paramètres absents/doubles/inconnus et source périmée refusés; page terminale vide
ne devient pas une déclaration inexistante. Instantanés SQL des lectures/refus non injectés
inchangés. Les fixtures de préparation ne prouvent ni formulaire d'écriture ni appareil terrain.
Revue indépendante finale ferme le constat legacy, aucun autre défaut concret relevé; pas de
runtime du relecteur. Preuve : `CRM16-COMPOSITION-HTTP-LOCAL-QUALIFIED.json`.

**PARTIAL — consultation admin HTTP/SQLite des compositions déclarées qualifiée localement.**
Saisie/correction/retrait par writer admin, validation canonique des identités à l'écriture,
CSRF d'écriture, M10, navigateur natif, PostgreSQL et mobile restent à qualifier. Les noms,
absences, heures/paie et présence réellement observée ne sont pas reconstitués par cet écran.
Prochaine tranche : déclaration manuelle signée par l'admin courant, avec identités canoniques,
CAS/rejeu et CSRF; aucun profil d'équipe ni droit courant modifié par la déclaration historique.


## Contrat avant la déclaration admin et son formulaire

Nouvelle tranche : `m4_declarer_composition_journaliere_console`, T1 privé sans portée d'appareil,
fermé aux deux répartiteurs génériques. Réemploi du contexte d'intention des annotations et du
port humain `metier`, sans reçu central contenant les membres. Un wrapper propre à la composition
vérifie connexion canonique SQLite, admin SQL/session avant et après l'action dans un savepoint.
Auteur et heure de réception sont calculés côté serveur; le client ne les fournit jamais.

Capturer la source bornée et préparer l'opération complète sur copie par le domaine, accusé
et quota compris. Retrouver le rejeu exact avant CAS et validation des identités contemporaines;
revalider quand même l'admin courant, la source et la sortie. Ancien rejeu = ancien accusé sans
membres, puis lecture fraîche de l'état courant; aucun retour arrière, aucune nouvelle trace.
L'existence historique d'une paire se déduit uniquement des maillons validés `(jour,equipe_id)`,
pas du numéro de révision fourni ni d'une autre journée.

Pour une première déclaration, l'équipe doit exister dans la copie exacte du profil canonique
consommé. Son empreinte vient de cette même copie et est revérifiée avant/après l'ajout.
Pour corriger une paire déjà historisée (même retirée), ne pas exiger qu'elle existe encore dans
le profil courant. Retrait : aucune validation de membres ou d'équipe contemporaine qui empêcherait
de retirer une ancienne déclaration erronée. Toute nouvelle liste utilise exclusivement les
identifiants de comptes canoniques existants, sans nom libre ni création de compte. Un compte
désactivé peut être cité dans une déclaration explicite : cela ne le réactive pas et ne prouve
ni disponibilité, présence, rôle passé ou appartenance actuelle. Aucun membre n'est copié depuis
le profil; pas d'exclusivité entre équipes imposée à cette histoire déclarative.

SQLite BEGIN IMMEDIATE et savepoint encadrent la relecture/CAS/append. Vérifier le maillon réellement
ajouté contre le préparé et le préfixe SQL/metadonnées inchangé; une panne d'audit, de source,
de profil ou d'autorité après append doit lever hors du savepoint et annuler toutes les écritures
avant conversion en refus métier. Ne pas supposer que `executer_atomique` annule un refus dont
l'enveloppe technique porte `ok=True`. Audit minimal : source, jour/équipe, révision, statut,
effectif et empreintes; jamais la liste de membres dans les journaux/reçus génériques. Aucun
envoi M10 ou événement d'accès automatique dans cette tranche.

Formulaire sur l'écran déjà qualifié : déclaration/correction avec identifiants un par ligne,
préremplis seulement depuis la déclaration courante; après retrait, liste inconnue et champ vide.
Formulaire distinct de retrait pour revenir à inconnu, pas à une fausse liste vide. CSRF, mutation
UUID, révision attendue, corps UTF-8 et champs strictement bornés; jour/équipe proviennent de l'URL
exacte et sont inclus dans l'empreinte d'intention. POST303 vers une lecture fraîche. Auteur,
heure, rôles, profils et paie ne sont ni modifiables ni traités par ce formulaire.

Tests : writer réel absent au rouge; identités connues/inactives, équipe initiale inconnue et
paire d'un autre jour refusées, retrait/correction après disparition de l'équipe, rejeu ancien
sans profil/identités contemporaines, CAS concurrent de deux transactions, conflit d'intention,
source/profil A→B→A, rôle ou audit défaillant après append avec rollback, sortie bornée avant append,
aucun changement du profil/des droits/du principal/du reçu central. Puis vrais POST HTTP CSRF,
déclaration→correction→retrait→nouvelle déclaration, réouverture et historique, faux auteur/heure,
champs doubles et taille, rôle révoqué, forme et classement privé de l'outil. Aucun accès réel,
paiement, présence, sanction, navigateur, PostgreSQL ou mobile revendiqué.


## Déclaration admin et formulaire qualifiés localement

Le vrai T1 privé et le formulaire admin CSRF existent maintenant. Déclarer, corriger, retirer
puis redéclarer conserve les quatre révisions dans la base canonique; le retrait signifie
inconnu, tandis que la liste vide demeure une déclaration explicitement vide. POST303 relit
l'état courant, même après rejeu d'une ancienne intention. Jour et équipe restent fixés par
l'URL; auteur et heure proviennent du serveur. Les identifiants ne sont ni créés, ni réactivés,
ni copiés depuis la configuration actuelle. La disparition actuelle d'une équipe n'empêche
pas de corriger son jour historique; elle interdit une première déclaration pour un autre jour.

Cohorte intégrée `crm16-composition-form-v3` : **273 PASS, 0 FAIL, 0 SKIP, 35,63 s**, Ruff et
vérificateur natif passent. Elle inclut 21 cas du writer et 19 cas du formulaire, les lecteurs
SQL/HTTP, le domaine, les portées d'appareil, les verdicts et les régressions notes/journal.
Les cohortes antérieures se recoupent et ne sont jamais additionnées. Catalogue natif :
300 outils, 175 déclarés aux appareils; ce nouveau T1 demeure fermé aux appareils et aux
agents, aucun rôle de compte ajouté. Source en lecture seule sous Landlock, réseau refusé,
homes/tmp privés avant imports, 1 CPU / 1 Gio / 96 tâches / 600 s, données fictives uniquement.

Rouges conservés : writer absent, formulaire absent, puis trois POST acceptant à tort des
séparateurs de contrôle comme deux membres. LF/CRLF sont désormais les seules fins de ligne
interprétées; caractères de contrôle, espaces de bord, doublons et identités inconnues sont
refusés. Les erreurs de préparation (fixture, syntaxe de test, import ou lint) restent classées
comme erreurs du harnais, sans attribution au produit. Panne d'audit après append, perte
d'autorité après ajout, métadonnées altérées, profil A→B→A et deux transactions concurrentes
sont exercés; les refus annulent les écritures. Rejeu exact = ancien accusé sans nouvelle trace;
conflit de corps ou révision périmée = refus sans écriture. Aucun membre dans les accusés ou
journaux génériques; aucun changement des autres tables, profils ou droits.

Revue statique indépendante backend et formulaire : aucun constat concret supplémentaire,
sans runtime du relecteur. Le défaut de séparateurs a été reproduit et corrigé par le root.
Preuve : `CRM16-COMPOSITION-WRITE-LOCAL-QUALIFIED.json`, avec reçus, pins, limites et historique.

**PARTIAL — saisie admin déclarative HTTP/SQLite qualifiée localement, publication en attente
de la CI du parent.** Ce résultat ne prouve ni présence, absence, heures/paie, composition
réellement observée, M10, PostgreSQL, navigateur natif ou mobile. Prochaine capacité : journal
administratif explicite des absences par journée, sans motif de santé, sans déduction à partir
d'une composition et sans décision RH automatique; son contrat et ses sources restent à examiner.


## Prochain besoin réel examiné : absences administratives par journée

Examen de source, sans code d'absence ni nouveau runtime : `journal_quotidien.py` avertit déjà
qu'un pointage manquant ne signifie pas absence et exclut ces données de sa projection.
`composition_journaliere.py` sait seulement déclarer des membres d'équipe. `temps.py` concerne
les pointages et refuse les champs de paie. Aucun writer, lecteur ou formulaire d'absence
journalière n'a été trouvé dans ces propriétaires, le catalogue `outils.py`, la console du
journal ou les tests M4 concernés. Un motif libre d'une réassignation commerciale M2 n'est
pas une source d'absence. `identite.Personne` fournit identifiant, état actif et rôles actuels;
ces rôles ne constituent pas une preuve d'emploi ou de présence à une date passée.

Patch minimal envisagé, à vérifier avant exposition : registre M4 distinct
`absences_journalieres_declarees`, clé exacte `(jour,personne_id)`, type fermé dédié. Une
entrée signifie seulement « absence pour la journée signalée par un administrateur » et
reste une déclaration. Son retrait rétablit l'inconnu; ni aucun signalement, ni retrait ne
signifie présent. Aucun motif, maladie, document médical, durée rémunérée, sanction ou calcul
de paie ne fait partie du schéma. Jour civil explicite et instant d'enregistrement serveur
restent distincts. Auteur admin et intention bornée, révisions append-only avec lien précédent,
CAS, rejeu exact avant CAS et accusé ancien sans données du sujet. Aucun hard-delete.

Fondation pure en premier : date/identifiants canoniques de transport, champs exactement fermés,
révisions monotones, retrait seulement après signalement actif, source/sortie bornées et paginées,
validation sémantique même si une chaîne altérée a été rehachée. Aucun import d'identité SQL,
profil, temps, réseau ou horloge dans cette fondation. Réutiliser les validateurs et primitives
chaînées existants sans transformer la composition d'équipe en registre d'absences ni recopier
sa liste de membres. Ne pas extraire un framework commun au prix de changements sans besoin.

Adaptateur futur : SQLite canonique, admin SQL/session avant/après sous transaction/savepoint.
Pour la première paire jour/personne, résoudre un compte existant ayant un rôle interne humain
parmi employee, seller, manager, finance, admin, nathan_owner; un compte désactivé peut rester
citable pour une déclaration historique, sans réactivation. Aucun compte seulement client ou
agent système proposé pour une première saisie. Pour retirer ou corriger une paire déjà
historisée, les rôles actuels ne doivent pas effacer l'histoire; revalider l'auteur courant,
pas inventer les rôles passés du sujet. Tout contrôle d'identité doit porter sur la même
transaction que l'écriture. Aucun droit ni profil modifié; pas d'export M5/M8/M10 automatique,
pas d'accès agent/générique, pas de décision RH automatique. La validation explicite de l'admin
est l'action humaine requise. Toute extension sensible ou export sera une autre tranche.

Lecture et écran futurs : accès admin seul, état explicite et sources, pagination liée à la
source; pas de nom actuel substitué à un identifiant historique. Lien indépendant depuis le
journal par jour; la source principale du journal demeure inchangée. Formulaire humain CSRF,
UUID et CAS, aucune raison libre, puis POST303 vers la lecture fraîche. Un jour sans déclaration
reste « aucune absence signalée », jamais « tout le monde présent ». Une incohérence avec une
composition ou un pointage ne déclenche ni retrait automatique ni pénalité.

Tests à écrire ensuite avant implémentation : signalement→retrait→nouveau signalement et ancien
rejeu, distinction aucun signalement/retrait/présence inconnue, paires indépendantes, doublons
et champs sensibles refusés, chaîne rehachée invalide, temporalité et pagination/quotas. Puis
identités humaines/client/agent et comptes désactivés, rôle admin révoqué, deux transactions,
rollback après append et audit, vrais GET/POST CSRF, aucun changement de pointage, paie,
composition, profil, droits ou mémoire. Les preuves compatibles de composition seront réutilisées;
aucun ancien runtime ou modèle n'est rejoué. **STUB : contrat préparé, fonctionnalité non codée.**


## Absences : fondation pure qualifiée, sans exposition CRM

`absences_journalieres.py` existe maintenant, après le contrat et le rouge d'absence du module.
Registre distinct, état aucun_signalement/signalee/retiree, révisions et retrait conservés,
jour/personne indépendants, source de pagination et accusé sans personne concernée. Auteur
et identifiants restent des charges pures; aucune autorité SQL ou présence réellement observée
n'est prouvée à ce stade. Réemploi des validateurs et du registre, sans changer la signification
ni les données des compositions ou pointages. Le type supplémentaire est explicitement ratifié
dans l'énuméré fermé ET son assertion gelée; aucun élargissement par wildcard.

Cohorte `crm16-absence-v3` : **101 PASS, 0 FAIL, 0 SKIP, 0,37 s**, dont 20 nouveaux cas purs,
avec registre, compositions et journal. Ruff et vérificateur natif passent : 300 outils,
175 déclarés, aucun nouvel outil exposé. Les 99 cas de v2 sont inclus et ne sont pas additionnés
à la cohorte de composition de 273 cas. Même enveloppe privée bornée et sans réseau.

Revue indépendante : le calcul des octets hors conversion pouvait laisser échapper une
UnicodeEncodeError ou TypeError sur une source corrompue. Deux rouges réels reproduits
(`crm16-absence-source-red-v1`) avec surrogate rehaché et charge non JSON. Mesure et lecture
sont maintenant dans la conversion vers un refus métier; le contrôle du nombre précède
encore toute lecture. Relecture statique ferme le constat, sans runtime du relecteur.
Les rouges de lint, module absent et assertion d'énuméré omise restent historiques avec
leur classement respectif. Preuve : `CRM16-ABSENCE-PURE-LOCAL-QUALIFIED.json`.

**PARTIAL — fondation pure seulement.** Aucun T0/T1, SQL, formulaire, nom de personne résolu,
contrôle d'identité réel, événement M10, absence mesurée, paie ou décision RH automatique livré
par cette tranche. Prochaine action concrète : capture canonique SQLite bornée avant décodage,
projection indépendante et vrai T0 privé admin/session avec recapture et sortie minimisée;
ensuite seulement writer à identité confirmée et formulaire sans motif de santé.


## Contrat avant le lecteur SQL privé des absences

Réutiliser le snapshot SQL canonique avec métadonnées et la garde admin/session déjà qualifiés,
sans nouvelle dépendance. `absences_durables.py` fixe département et registre; SQL compte les
maillons et octets UTF-8 bruts avant tout décodage. Source malformée, maillon hors schéma ou
chaîne invalide = refus, sans réparation. La projection du domaine ajoute l'empreinte calculée
du snapshot; source et sortie ont des bornes indépendantes. Conserver le classement des refus
de quota plutôt que les confondre avec un défaut d'identité.

Ajouter `m4_lire_absence_journaliere_console`, T0 au seul transport interne admin console,
refusé aux agents/MCP/appareils directs ainsi qu'aux deux répartiteurs génériques AVANT factory,
normalisation et reçu. La déclaration nominale de portée admin du transport est explicitement
ratifiée avec catalogue gelé et documentation; elle ne donne aucun rôle à une personne et
n'autorise pas un appel externe. Garde SQL courante avant/après et connexion SQLite exacte;
aucun profil courant, nom ou rôle actuel du sujet lu pour reconstruire son histoire.

Le port `console.absences_personnes.lire` compare une projection indépendante de la même
capture au résultat du vrai T0, vérifie le quota puis recapture et contrôle à nouveau la
session/admin. Identifiant et jour restent ceux demandés. Aucun faux état présent quand
aucun signalement ou après retrait. Aucun writer, formulaire, calcul d'heures, paie, événement
M10 ou décision RH dans cette tranche. PostgreSQL reste fermé tant que non qualifié.

Tests avant implémentation : source SQLite réellement rouverte, états et temporalités, compte
historique inactif sans réactivation, zéro écriture; fausse portée admin/session expirée,
appareil/MCP et registre/connexion injectés refusés; réponse altérée et métadonnées changées,
révocation après dernière capture, quotas SQL avant décodage et sortie, JSON/maillon invalides,
pages liées à la source, répartiteurs privés sans factory/reçu. Catalogue et registres existants
restent contrôlés, preuves de composition compatibles réutilisées sans réexécutions inutiles.


## Lecture privée durable des absences qualifiée localement

`absences_durables.py`, le vrai T0 `m4_lire_absence_journaliere_console` et le port
`console.absences_personnes.lire` existent maintenant. La même base canonique est rouverte :
signalement puis retrait, identifiant historique exact, deux temporalités et empreintes de
source restent consultables, sans nom actuel ni réactivation du compte inactif. Projection
indépendante et réponse du T0 sont comparées, métadonnées recapturées et admin SQL/session
recontrôlés avant restitution. La source principale M4, les compositions, profils, droits,
pointages et tous les autres états restent inchangés par une lecture ou un refus.

Cohorte `crm16-absence-port-v2` : **186 PASS, 0 FAIL, 0 SKIP, 13,83 s**, incluant 20 nouveaux
cas SQL/T0, les 20 cas purs, les verdicts, portées et lecteurs de composition. Les anciennes
cohortes sont incluses ou recoupées et ne sont pas additionnées. Ruff et vérificateur natif
passent : 301 outils, 176 déclarés au transport; le catalogue gelé et ROLES.md sont mis à jour
explicitement. Aucun rôle de personne ajouté. Les appareils/agents/MCP et répartiteurs
génériques refusent ce T0 avant normalisation, factory ou reçu. Les codes de quota restent
distincts de ceux d'identité. Données fictives, source RO sous Landlock, réseau refusé et
limites 1 CPU / 1 Gio / 96 tâches / 600 s vérifiées avant imports.

Rouge `absence-port-red-v1` : vrai outil absent. `port-v1` est un refus de lint (deux lignes
trop longues), sans erreur produit; aucun artefact remplacé. JSON/maillon invalide, quotas SQL
avant décodage, fausse autorité et session expirée, registre/connexion injectés, réponse altérée,
révocation après dernière capture et mutation des métadonnées ont leurs refus vérifiés.
Revue indépendante statique : aucun défaut concret supplémentaire, sans runtime du relecteur.
Fonctions existantes de lecture/écriture des compositions et de journal inchangées par AST.
Preuve : `CRM16-ABSENCE-PORT-LOCAL-QUALIFIED.json`.

**PARTIAL — lecture privée SQL/T0 uniquement.** Aucun writer, formulaire, vue par jour de toutes
les absences, emploi/absence réellement vérifié, paie, M10, PostgreSQL, navigateur ou mobile
prouvé ici. Prochaine capacité : exposer une consultation admin HTTP au jour/personne exacts,
avec session revérifiée après rendu et paramètres/sortie fermés; la saisie et la liste quotidienne
viendront avec leurs sources et contrôles distincts. La CI du parent 4752 est maintenant terminale
(40 succès, 4 SKIP historiques, 44 observés), sans déclaration de complétion produit.


## Contrat avant consultation HTTP des absences

GET `/crm/journal-equipes/absence` : jour et identifiant de personne explicites, mêmes paramètres
fermés de pagination/source que le journal. Réemployer le port SQL/T0 réel et garder la transaction
canonique pendant le rendu. Contrôler HTML ≤128 Kio, source inchangée puis session/admin après
rendu, no-store/CSP. Afficher aucun_signalement/signalee/retiree, versions et deux temporalités;
jamais traduire le retrait ou l'absence de signalement en présence. Les identifiants historiques
restent exacts et échappés, sans nom ou rôle actuel. Page terminale vide ≠ aucune absence.

Le journal gagne uniquement un formulaire GET de consultation par identifiant/jour, sans
lire/compter/copier le registre d'absences dans sa projection. Aucun faux lien ne vise une URL
qui requiert une personne manquante. Les logs d'accès Uvicorn masquent toute query contenant
`personne_id`, clé encodée comprise, en conservant chemin/méthode/statut; réutiliser le filtre
déjà branché pour la recherche `q`. La requête n'est pas une preuve qu'un compte existe.
Aucun POST, writer, raison, paie, export ou notification dans cette tranche.

Tests avant code : vraie route/SQLite/T0/rendu, historique signalement→retrait, inconnu distinct,
paramètres uniques et fermés, non-admin et révocation pendant rendu, source changée pendant
rendu, échappement/HTML borné, pagination et reprise périmée, formulaire GET du journal utile
sans copie de données ou compteur, logs Uvicorn réels formatés sans identifiant. Régressions
journal/composition et ancien masquage de recherche, sans refaire les cohortes compatibles.


## Consultation HTTP des absences qualifiée localement

GET admin `/crm/journal-equipes/absence?jour=...&personne_id=...` utilise le vrai port privé et
la base canonique pendant le rendu. Historique, signalement retiré et aucun signalement sont
visibles sans déduction de présence, paie ou nom actuel. Paramètres fermés, pagination liée
à la source, page terminale explicite, HTML borné/échappé, no-store/CSP; source et autorité
SQL/session sont recontrôlées après rendu. Le journal possède un formulaire GET utile par
identifiant/jour, sans requête, copie ou compteur du registre d'absences dans sa projection.
POST reste 405. Aucun writer ou formulaire de mutation d'absence n'est affiché.

Cohorte `crm16-absence-http-v2` : **79 PASS, 0 FAIL, 0 SKIP, 22,07 s**, dont 22 nouveaux cas HTTP,
avec les 20 lecteurs privés SQL, journal, consultation des compositions et ancien masquage
Uvicorn. Les 78 cas de v1 sont inclus; aucune addition aux cohortes précédentes. Ruff et
catalogue natif 301 outils/176 déclarés passent. Même enveloppe QA privée, source RO sous
Landlock, sans réseau, données fictives et ressources bornées avant imports. Fonctions
privées de lecture existantes inchangées par AST; aucun SDK ou profil/identité modifié.

Rouges réels conservés : route 404, deux logs `AccessFormatter` exposant identifiant/jour
(clé normale et encodée), puis défaut signalé par la revue indépendante avec slash final et
clé invalide. Le vrai premier GET307 a été reproduit et son log divulguait la query. Le filtre
masque désormais toute query du chemin privé, slash final et chemin décodé compris; il masque
également la clé personne_id et conserve l'ancien comportement de q. Chemin/méthode/statut
restent disponibles. Cela qualifie Uvicorn; les logs d'un proxy externe ne sont pas prouvés.
Relecture statique ferme le constat, aucun runtime du relecteur. Révocation ou source changée
pendant rendu refusent l'ancien contenu; lecture/refus ne modifient aucune table, hors mutations
explicitement injectées dans les tests. Preuve : `CRM16-ABSENCE-HTTP-LOCAL-QUALIFIED.json`.

**PARTIAL — consultation admin HTTP/SQLite qualifiée localement, commit à publier après CI
terminale du parent ebce.** Absence réellement constatée, saisie staff à identité confirmée,
liste quotidienne globale, heures/paie, M10, PostgreSQL, navigateur natif et mobile restent
ouverts. Prochaine action : writer admin privé des signalements/retraits, cible humaine
canonique initiale, auteur/heure serveur, CAS/rejeu et rollback audit/source/autorité, avant
formulaire CSRF. Aucun motif de santé ni action RH/financière automatique.


## Contrat avant le writer admin des signalements d'absence

Réutiliser le domaine pur et le parcours signé des compositions : nouveau T1 privé
`m4_declarer_absence_journaliere_console`, sans portée d'appareil et fermé aux deux répartiteurs
génériques avant factory/normalisation/reçu. Paramètres exactement jour, personne_id, statut
signalee/retiree, révision attendue. Auteur et instant de réception sont fournis par le serveur;
aucun motif, santé, montant, heure, paie, nom ou rôle modifiable par le client.

Pour la première paire jour/personne, résoudre un compte canonique existant ayant au moins un
rôle interne humain employee/seller/manager/finance/admin/nathan_owner; refuser system_agent,
même combiné à un rôle interne, et les comptes seulement client. Un compte désactivé peut être
cité pour l'histoire, sans activation ni emploi passé déduit. Capturer uniquement identifiant,
état actif et rôles du compte effectivement consommé, pas son nom ou mot de passe. Recontrôler
cette même source avant/après append. Une paire déjà historisée validée, même retirée, reste
corrigeable/retirable sans reconstituer les rôles actuels ou passés du sujet. La paire d'un
autre jour n'autorise jamais une première saisie. Aucun compte ni rôle n'est créé ou modifié.

Préparer et valider l'opération entière sur copie bornée avant append : CAS, schéma, chaîne,
intention et quota d'accusé. Rejeu exact avant CAS et validation contemporaine du sujet :
renvoyer l'ancien accusé sans sujet et sans nouvelle écriture, après autorité courante et
source revérifiées. Conflit d'intention, auteur différent ou historique altéré = refus.

Savepoint propre et transaction canonique SQLite BEGIN IMMEDIATE. Avant append vérifier
source/identité/auteur; après append comparer accusé, maillon réel et préfixe/métadonnées
intacts, puis identité initiale et auteur. Journal d'audit minimal : jour, révision, statut,
empreintes et marqueur de validation initiale; pas de sujet, nom ou rôles dans journal/reçus
génériques. Une erreur d'audit, d'identité, de source ou d'autorité après append sort du
savepoint avant conversion en refus, même si l'appelant capture l'exception. Le wrapper SDK
révérifie la session/admin après retour du writer et annule aussi toute perte d'autorité tardive.
Aucun événement M10, automatisation RH, effet de présence ou calcul financier.

Tests avant code : vrai outil absent au rouge; signaler/retirer/redéclarer, cible humaine
inactive et chaque rôle interne, client/agent/inconnu et champs sensibles refusés; ancien
rejeu sans lecture contemporaine du sujet, historique après changement de rôle et autre
jour refusé; CAS/intention, deux transactions réelles concurrentes; source d'identité A→B→A,
panne d'audit/révocation/métadonnées ou cible changée après append, accusé altéré, quota avant
append et refus directs/MCP/injection. Tables/profil/pointage/composition/paie inchangés hors
registre et audit minimisé. Formulaire CSRF et liste quotidienne viendront séparément.


## Writer privé des absences qualifié localement

Le vrai T1 privé `m4_declarer_absence_journaliere_console` et `absences_ecriture.py` existent.
Compte interne humain confirmé pour une première paire, comptes désactivés admis sans activation,
agent système refusé même combiné; historique et retrait gardés après changement du rôle actuel
du sujet. Un autre jour redevient une première paire. Le rejeu exact renvoie l'ancien accusé,
sans validation contemporaine du sujet, sans nouvelle trace et sans revenir sur les retraits.
Auteur/session SQL restent courants. Les deux transactions concurrentes n'acceptent qu'une révision.

Cohorte `crm16-absence-write-v2` : **222 PASS, 0 FAIL, 0 SKIP, 21,96 s**, dont 35 nouveaux cas
writer/identité, plus les compositions, lectures privées, domaine pur, portées et verdicts.
221 cas de v1 inclus, aucun cumul des cohortes. Ruff et vérificateur natif : 302 outils,
176 déclarés au transport, nouveau T1 fermé aux appareils/agents/MCP et répartiteurs génériques.
Aucun rôle de personne ajouté. Même enveloppe privée : source RO Landlock, sockets refusés,
1 CPU / 1 Gio / 96 tâches / 600 s, données fictives, dépendances déjà privées avant imports.

Rouge initial : outil réellement absent. Le root a ensuite reproduit par hook SQLAlchemy une
sélection excessive du nom et du hash secret du sujet via `identite.personne` (aucun export
observé). La résolution initiale sélectionne maintenant uniquement identifiant/actif et rôles
bornés à neuf lignes, validés par le catalogue fermé. Revue statique indépendante ferme cette
correction; aucun autre constat concret, aucun runtime du relecteur. Aucun changement de l'API
identité globale. Le wrapper SDK partagé est seulement renommé; son corps est identique par AST.

Préparation et quota avant append, source/identité effectivement consommées et auteur revalidés,
accusé réel/maillon/préfixe/métadonnées comparés. Panne d'audit, identité/rôle modifié, source
altérée ou autorité perdue après append annulent toutes les écritures, même si l'appelant
capture l'exception. Une perte d'autorité après retour du writer annule également l'opération
au niveau SDK. Audit minimal et accusé sans sujet; autres tables, profils, accès, composition,
pointage et paie inchangés. Champs santé/motif/auteur client/heure/paie refusés par le schéma.
Preuve : `CRM16-ABSENCE-WRITE-LOCAL-QUALIFIED.json`.

**PARTIAL — backend privé HTTP/SQLite qualifié, formulaire de mutation encore absent.** La
saisie UI vient ensuite sous CSRF, UUID et CAS, sans motif libre. Pas d'absence observée,
présence, emploi passé, paie, liste quotidienne complète, M10, PostgreSQL, navigateur natif,
mobile ou décision RH automatique qualifié. Parent ebce : dernier jalon CI 26 succès,
4 SKIP, 12 en cours, 42 observés; les commits locaux restent retenus, sans annulation/rejeu.


## Contrat avant formulaires admin des absences

Sur la route déjà qualifiée, ajouter un formulaire POST de signalement et un formulaire
séparé de retrait seulement quand un signalement est courant. Quatre champs exactement :
csrf, revision_attendue, mutation_id UUID, statut_declaration. Jour/personne restent dans
l'URL canonique sans pagination. Réutiliser le parseur de formulaire des annotations (corps
UTF-8 borné à 30 000 octets, champs uniques/fermés) et son entier canonique; valider UUID et
statut. Réutiliser le classement de confirmation des déclarations avec préfixe ABSENCE explicite.
Aucun champ libre pour santé, motif, temps, paiement, nom, rôle, auteur ou heure client.

Première déclaration : forme visible seulement si la même connexion canonique confirme le
compte humain interne avec le sélecteur SQL minimisé. Sinon message explicite, sans bouton
inopérant ou nom actuel. Pour une paire déjà historisée, forme encore disponible après changement
du rôle actuel, sans lookup du sujet. Retrait garde l'histoire et ne signifie jamais présent.
L'admin valide explicitement le signalement pour la journée/identifiant affichés; aucun calcul RH.

POST appelle le vrai T1 sous transaction canonique et savepoint, CSRF et session/admin SQL,
confirme le refus dans le savepoint puis recontrôle l'admin avant 303 vers une lecture fraîche.
Rejeu ancien = ancien accusé serveur mais état courant affiché, jamais retour arrière. Refus
400/403/409/503 selon cible/autorité/CAS/source; toute panne après append annule les écritures.
GET et lookup restent des lectures; les formulaires sont des actions distinctes et explicites.

Tests avant code : vraies formes signalement→retrait→redéclaration/rejeu, ancien rôle du sujet,
autre jour initial refusé, changement de corps/URL, CAS simultané, CSRF/UUID/révision/statut,
champs sensibles/doubles, JSON et taille, non-admin/rôle révoqué, audit après append et autorité
HTTP perdue après retour SDK. Régressions des formulaires de composition et annotations, des
lectures et de la confidentialité. Le test POST sans Content-Type attend désormais 415 au lieu
de405, avec invariant zéro écriture. Aucun navigateur, PostgreSQL ou mobile revendiqué.


## Formulaires admin des absences qualifiés localement

La page propose maintenant deux actions explicites : signaler et, si un signalement est
courant, retirer. Quatre champs cachés seulement, sans motif/santé/paie : CSRF, révision,
UUID et statut. Jour et identifiant restent dans l'URL fermée; le résultat POST303 relit
l'état courant. Le premier formulaire exige un compte humain interne canonique et les
anciennes paires restent corrigeables après changement du rôle actuel. Un compte désactivé
n'est jamais réactivé. Après retrait, aucune présence n'est affirmée. Le GET et le lookup
restent des lectures; les mutations exigent une validation administrative distincte.

Ce jalon qualifie les écritures HTTP; le jalon précédent qualifiait le backend SDK/SQLite.
Le parseur existant des annotations est réutilisé : UTF-8, 30 000 octets, quatre champs
uniques et fermés, entier canonique. UUID/statut validés avant écriture. Le confirmateur
partagé garde le préfixe COMPOSITION par défaut et reçoit explicitement ABSENCE ici; refus
cible/CSRF/CAS/source en 400/403/409/503. La transaction et le savepoint englobent le vrai T1,
la confirmation et l'admin SQL après retour SDK. Panne d'audit ou autorité HTTP perdue annulent
l'append, même après succès du writer. Aucun reçu générique ne contient le sujet.

Cohorte `crm16-absence-form-v2` : **107 PASS, 0 FAIL, 0 SKIP, 30,90 s**, dont 17 nouveaux cas
HTTP/formulaire, avec 22 lectures/logs, 19 formulaires de composition, 14 annotations et
35 writers. Les anciens 79/186/222 et ces populations se recoupent et ne sont pas additionnés.
Ruff et vérificateur natif : 302 outils/176 déclarés, aucune nouvelle portée ou droit accordé.
Même enveloppe QA privée, réseau refusé, source RO Landlock, 1 CPU / 1 Gio / 96 tâches / 600 s
avant imports. Aucun navigateur natif utilisé. Rouge initial : vrai formulaire absent;
v1 est seulement un refus de lint sur une ligne longue, sans runtime produit. Revue statique
indépendante : aucun constat concret supplémentaire, aucun runtime ou mutation du relecteur.
Preuve : `CRM16-ABSENCE-FORM-LOCAL-QUALIFIED.json`.

Vrais formulaires signalement→retrait→redéclaration, ancien rejeu après corrections sans retour
arrière, historique après changement du rôle et autre jour initial refusé, conflit de corps/URL
ou révision, JSON/champs doubles/taille, CSRF/UUID/révision/statut et champs sensibles refusés.
Non-admin et admin révoqué ne peuvent écrire/rejouer. Tous les autres états, rôles et profils
restent inchangés hors registre/audit minimisé; compte inactif toujours inactif. POST sans
Content-Type est désormais 415, contre 405 avant création de la route, et n'écrit rien.

**PARTIAL — signalement/retrait admin HTTP/SQLite qualifiés localement.** Ce n'est pas une
absence réellement observée, une présence, un calcul de paie ou une décision RH automatique.
Liste quotidienne globale, heures, M10, PostgreSQL, navigateur et mobile restent ouverts.
Prochaine capacité utile : liste journalière paginée des signalements courants et retirés,
avec liens vers cet historique, sans annuaire contemporain, compteur dupliqué dans le journal
ou déduction de présence. Publication des commits locaux retenue par la CI du parent ebce.


## Contrat avant la liste quotidienne des signalements

Réutiliser exclusivement le registre d'absences et son `_charger` validé. Pour un jour explicite,
retenir une seule dernière révision par personne exacte, y compris les retraits; tri stable
par identifiant sans normalisation. `total` = nombre de personnes ayant une déclaration dans
ce jour (retirée comprise), jamais nombre d'absents observés ni de salariés présents. Aucune
addition des révisions/visites ou recoupement avec le profil/pointage. Jour sans ligne = aucun
signalement documenté, pas tout le monde présent. Liste minimisée : identifiant, statut courant,
révision, auteur, deux temporalités et source; aucun motif, paie, nom ou intention.

Pagination liée à la tête source et au jour; continuation sans source ou source périmée refusée,
page terminale vide distincte de journée vide. Bornes source et enveloppe UTF-8 préservées,
chaîne et schéma validés même pour les autres jours, copies indépendantes. Pas de nouveau registre
ni vérité parallèle. Fondation pure d'abord, puis adaptation du snapshot canonique existant,
vrai T0 privé avec mêmes contrôles d'autorité/recapture/quota et page GET admin.

Le journal ne lit/compte pas les absences; lien de jour exact vers la liste. Chaque ligne mène
à l'historique individuel déjà qualifié. Consultation GET seulement, formes de mutation restent
sur la page individuelle. Paramètres fermés, HTML borné/échappé et source/admin après rendu;
masquer aussi la query du chemin pluriel dans Uvicorn, slash final compris. Pas d'annuaire
contemporain, d'automatisation RH, de paie ni de présence déduite.

Tests avant code : plusieurs personnes et révisions/retraits, tri et total uniques, autre jour,
jour vide/page terminale, cursors périmés ou d'un autre jour, copies sans mutation, schéma altéré
rehaché et quotas source/sortie. Puis vrai T0/source canonique, autorité et données altérées,
route/lookup/journal sans copie, historique source exact, confidentialité/révocation après rendu,
logs privés. Réutiliser les preuves compatibles du writer et du formulaire, sans refaire tout.


## Vue quotidienne des déclarations qualifiée localement

Le journal mène à GET admin `/crm/journal-equipes/absences?jour=...`. Une ligne par dernière
révision exacte d'une personne pour ce jour, retraits conservés, tri par identifiant sans
normalisation. Le total compte ces personnes ayant une déclaration, pas des absences observées,
des visites, des salariés présents ou l'annuaire complet. Journée vide et page terminale sont
distinctes. Un choix de date permet de revoir d'anciens jours; chaque ligne ouvre l'historique
individuel au jour/personne exacts, avec source de la révision affichée séparément. La saisie
reste sur la page individuelle déjà qualifiée; le lookup GET y donne aussi accès.

La fondation réutilise `_charger`, sans registre parallèle : 65 PASS/0,50 s incluent 13 nouveaux
cas purs et les registres précédents. L'adaptation complète `crm16-absence-day-port-v2` passe
**168 tests, 0 FAIL, 0 SKIP, 11,51 s**, dont 21 nouveaux cas SQL/T0/HTTP et les 13 cas purs,
avec portées, formulaires et ancien masque q. Populations recoupées, jamais additionnées.
Ruff et catalogue natif : 303 outils/177 déclarés, T0 de console privée seulement; aucun rôle
ou compte ajouté. Projection indépendante comparée au vrai T0, source SQLite bornée avant
décodage, recapture et session/admin après rendu, HTML borné/échappé, no-store/CSP. Le journal
ne lit ni copie ni compte ce registre : seul le lien du jour est ajouté.

Rouges réels : fonction pure absente, T0 manquant, GET404 et deux logs pluriels exposant
jour/source. Le filtre Uvicorn couvre maintenant aussi le chemin pluriel, avec ou sans slash
final. v1 du raccord est un refus de lint sur imports/ligne longue, sans runtime produit.
Revue statique indépendante de la fondation et du raccord : aucun constat concret, aucune
exécution ou mutation du relecteur. Preuves : `CRM16-ABSENCE-DAY-PURE-QUALIFIED.json` et
`CRM16-ABSENCE-DAY-LOCAL-QUALIFIED.json`. Fonctions existantes de lecture/écriture et capture
inchangées par AST; source RO Landlock, réseau refusé et ressources privées bornées avant imports.

**PARTIAL — vue quotidienne admin HTTP/SQLite qualifiée localement.** Retrait ou absence de
signalement ne prouve aucune présence, absence observée, emploi passé, heure ou paie. M10,
PostgreSQL, navigateur natif et mobile restent ouverts. Parent ebce au dernier jalon :
37 succès, 4 SKIP, 2 en cours, 43 observés; pas de publication anticipée ni remplacement CI.
Prochaine amélioration utile : sélecteur privé de comptes internes pour faciliter la saisie
sans devoir connaître l'identifiant; noms actuels explicitement séparés des faits historiques,
SQL minimisé/borné, aucun hash secret, droit ou profil modifié. Réutiliser la politique staff
validée; le sélecteur paie existant utilise une lecture globale trop large pour cette surface.


## Contrat avant le choix de compte interne

Le lookup actuel exige un identifiant connu. Ajouter une consultation privée paginée de
comptes internes humains, avec nom ACTUEL, identifiant et état actif ACTUEL clairement séparés
du jour de déclaration visé. Le sélecteur paie existant utilise `identite.lister`, qui lit des
lignes complètes et exclut les comptes désactivés : ne pas l'appeler sur cette surface. Réemployer
les tables canoniques et ROLES_INTERNES du writer, sans nouvelle vérité, rôle ou compte.

Sélection SQL par EXISTS (pas de jointure multipliant les comptes) : au moins un rôle humain
interne, aucun system_agent même combiné et aucun rôle inconnu. Comptes désactivés inclus,
explicitement étiquetés, sans réactivation. Ne sélectionner nom/id/actif et rôles que des
comptes éligibles; jamais nom de clients/agents seuls, hash secret ou colonne inutile. Compter
lignes et octets bruts UTF-8 avant chargement; plafond comptes/rôles/8 Mio, puis snapshot
minimal stable et sortie ≤64 Kio. Valider les identifiants canoniques, tri nom actuel puis ID,
pagination liée au snapshot et au jour. Une modification de nom/rôle invalide la continuation.

GET admin `/crm/journal-equipes/comptes?jour=...`, sans mutation. Autorité SQL/session et connexion
SQLite canonique avant/après, recapture avant restitution et après rendu; HTML ≤128 Kio,
échappement, no-store/CSP, logs Uvicorn masqués avec/sans slash. Les liens ne transportent que
jour/personne vers l'historique individuel existant; aucun nom courant n'est copié dans le
registre ni substitué aux événements passés. Garder le lookup par ID exact pour les anciennes
paires dont le compte n'est plus éligible. Journal et liste d'absences ajoutent seulement un lien
vers ce choix, sans requête de répertoire ni copie de noms dans leur projection.

Tests avant code : vraie source SQL minimisée (colonnes et périmètre), actif/inactif et homonymes,
client/agent/mix exclus, doublons de rôles sans doublons de comptes, quotas avant chargement,
source périmée après renommage/rôle, faux admin/session expirée, noms échappés, rendu après
révocation/source changée, navigation vers ID exact et fallback historique conservé, zero écriture.
Réutiliser les preuves des déclarations, pas de modèle, API externe ou données réelles.


## Choix privé de compte interne qualifié localement

Le journal et la liste quotidienne proposent maintenant un lien GET vers
`/crm/journal-equipes/comptes?jour=...`. La secrétaire peut choisir un compte par son **nom actuel**,
avec identifiant et état actif/désactivé explicites, puis consulter le signalement du jour/ID exacts.
Les homonymes restent distincts. Le lookup par identifiant est conservé pour les anciennes paires
dont le compte n’est plus admissible. Aucun nom actuel n’est copié dans les déclarations historiques,
ni affiché comme preuve d’emploi ou de présence passée. Les deux projections de journal ajoutent
uniquement une navigation; elles ne chargent aucun nom du répertoire.

`comptes_terrain.py` sélectionne seulement id/nom/actif et les rôles utiles des comptes admissibles,
avec EXISTS corrélés et sans doublons : rôle interne humain requis, system_agent même mixte et rôle
inconnu exclus; désactivés inclus sans réactivation. Comptes/rôles et octets UTF-8 sont comptés avant
chargement (10 000/80 000/8 Mio), puis snapshot minimal, JSON ≤64 Kio et HTML ≤128 Kio. La garde
d’authentification existante lit le compte de l’auteur; le test de minimisation mesure les requêtes
propres au répertoire, sans modifier cette garde. Aucun hash secret n’alimente le snapshot/cursor.

Pagination triée nom puis ID, source liée au jour/snapshot; changement de nom, rôle ou activation
invalide la continuation. Un changement de hash de mot de passe n’affecte pas le snapshot minimisé.
Page terminale vide distincte de répertoire vide. SQLite courant, admin SQL/session avant/après
lecture et rendu; autorité contrôlée avant puis après la dernière recapture, révocation→403 sans
ancien nom. Rendu échappé, no-store/CSP, POST405, query Uvicorn masquée même avec slash final.

Qualification `crm16-staff-v2` : **61 PASS, 0 FAIL/SKIP, 16,76 s**, dont 22 nouveaux cas et les
régressions liste quotidienne/formulaire/masque q. Quatre contrôles complémentaires ciblés
`crm16-staff-cursor-v1` passent en 2,25 s (homonymes/fin de page/autre jour/rôle/activation/secret).
Les preuves antérieures sont réutilisées; populations recoupées jamais additionnées. Source produit
identique entre ces deux phases, seuls les quatre tests complémentaires ont été ajoutés. Ruff et
catalogue natif 303/177 passent. Revue statique indépendante : aucun constat concret, sans runtime.
Les trois rouges réels initiaux (module absent et deux logs exposés) et les refus de lint du harnais
sont conservés. Preuve : `CRM16-STAFF-LOCAL-QUALIFIED.json`.

**PARTIAL : sélecteur admin HTTP/SQLite qualifié localement.** Aucun droit, compte, stock, paie,
présence observée ou donnée réelle modifié. M10, PostgreSQL, navigateur natif et mobile non qualifiés.
La CI parent ebce est maintenant terminale : 40 succès/4 SKIP/44 checks, sans pagination restante;
elle permet une publication normale du lot local, mais ne prouve ni sa nouvelle tête ni le produit.
