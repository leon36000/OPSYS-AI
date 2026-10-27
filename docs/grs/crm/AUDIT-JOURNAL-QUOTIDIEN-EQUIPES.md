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
