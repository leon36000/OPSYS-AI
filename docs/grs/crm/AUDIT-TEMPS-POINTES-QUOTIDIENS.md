# CRM-16 — audit ciblé et contrat de consultation des temps pointés

État inspecté : 196558865867ae6e7ef67b358e1464a14f16124f, sans modification Source ni runtime.
Objectif : rendre à la secrétaire une consultation des durées du jour issues des pointages,
sans reconstruire M4/M5 et sans convertir compositions/absences en heures ou présence.

## Réutilisation démontrée par le code

- `heures_regulieres.previsualiser` calcule travail NET après pauses, déplacement et pause,
  avec intervalles et références exactes. Fuseau IANA explicite; calcul en UTC, dates civiles,
  pas d’arrondi; séquence ambiguë/incomplète, chevauchement ou traversée civile refusés.
  Retour négatif sans source : indisponible, jamais zéro heure. Les sources GPS ne sont pas
  copiées dans la proposition. L’empreinte_sources concerne références/personne/période;
  elle ne remplace pas un snapshot canonique complet.
- Le T0 `m4_previsualiser_heures_regulieres` réutilise cette fonction, contrôle admin effectif,
  personne actuellement active avec rôle employee et chaîne M4. Cette politique exclut les
  anciens employés désactivés; ne pas contourner cette restriction dans le cockpit.
- `m4_lire_heures_regulieres_validees` exige une validation N4 et sa demande exécutée exactes,
  par période exacte, avec dispositions de catégories. Une validation de semaine ne devient
  pas une validation journalière en découpant un total. Ce lecteur et la paie M5 ne sont pas
  nécessaires à une consultation de proposition journalière non approuvée.
- `temps.produire_brouillon_temps` utilise les interventions complétées WCT, le préfixe de
  date de complétion et durée réelle WCT. Cette population et temporalité diffèrent du
  pointage civil journalier; ne pas additionner ni substituer ces valeurs au calcul net.
- `journal_durable.capturer` apporte connexion SQLite courante, pré-comptage lignes/octets
  et maillons avec métadonnées. Le port peut réutiliser cette capture et la validation
  Registre, puis comparer le calcul indépendant au vrai T0 et recapturer avant restitution.
- Le journal actuel affiche les faits pointés mais ne les associe pas à une visite précise
  et ne calcule aucun total quotidien. Le sélecteur de comptes offre une navigation actuelle;
  les noms/états de compte ne sont pas des faits historiques ni une preuve d’emploi.
- `paie_ui` est une surface propriétaire de préparation du brut M4/M5 avec autres droits;
  ne pas l’utiliser pour donner un accès paie aux utilisateurs du CRM.

## Tranche minimale suivante

Écrire un contrat Source avant tests/code, puis un port admin privé `temps_pointes.py` et GET
`/crm/journal-equipes/temps?jour=...&personne_id=...` si les tests du vrai T0 le confirment.
Date locale America/Montreal explicite, ID exact; aucune normalisation de personnes historiques.
Réutiliser le T0 existant, pas de nouvel outil, registre, table, validation N4 ni changement de droits.

Le port doit borner la capture avant décodage, vérifier compte cible actif/employee par colonnes
minimales et ses rôles, garder cette empreinte distincte du snapshot M4, dériver la proposition
avec le domaine existant et comparer la réponse entière du vrai T0. Les refus métier connus
peuvent être présentés par un code fixe sans texte libre source; une réponse altérée, rupture
de chaîne ou divergence reste refus technique sans chiffre. `_appel` du port préparation ne
convient pas tel quel : il transforme tous les refus du T0 en indisponibilité technique.
Valider explicitement le schéma acceptee/refus avant toute restitution, sans relâcher ce helper.

L’écran montre des MINUTES par catégorie et les intervalles/références : « Aperçu des temps
pointés — calcul M4 », distinct d’heures payables, présence complète et approbation. Aucun
montant, taux, salaire, GPS, texte de notes ou motif de santé. Pas de zéro par défaut en cas
de séquence absente/incomplète. Quotas JSON64Kio/HTML128Kio; une journée trop volumineuse est
refusée explicitement. Pagination de grandes journées restera ouverte si le T0 entier dépasse
sa borne, sans annoncer la capacité complète sur une petite fixture.

Navigation depuis le lookup jour/personne, pas d’annuaire copié dans le journal. Paramètres
fermés uniques, GET seulement; no-store/CSP, échappement, masquage complet de query sur le
nouveau chemin avec/sans slash. Autorité SQL/session avant/après calcul et rendu, puis recapture
source+identité cible et autorité finale. Révocation auteur→403 sans anciennes données.

## Preuve attendue avant livraison

Tests rouges ciblés : module/route absents et nouveau chemin privé non masqué. Puis fixture
fictive canonique de transition en_route, arrivée/départ et pause via registre M4 propriétaire,
vrai T0 + port + GET. Vérifier minutes travail net/déplacement/pause sans double compte, UTC/DST,
aucune donnée GPS/paie, source/history identiques, absence/incomplet explicite, jour hors source,
refus cible inactive/client, faux admin/session expirée/connexion étrangère, quotas avant décodage,
réponse T0 altérée, source/rôle modifiés avant restitution/après rendu, aucun write dans les tables.
Réutiliser les tests purs d’heures existants et les preuves du journal; ne pas refaire les 61/168/222
sans changement justifiant une régression. QA privée RO/réseau refusé, noms de phase exclusifs.

Statut : audit statique et contrat préparatoire seulement. Aucun nouvel écran temps livré,
aucun calcul exécuté pendant cet audit. Source demeure propre. Produit PARTIAL, M10/PG/mobile/
navigateur/présence observée et capacité horaire historique complète restent ouverts.


## Contrat d’exécution arrêté avant code

Tranche GET admin de proposition quotidienne individuelle seulement. Les comptes cibles doivent
rester actifs/employee conformément au T0 existant, et la console exclut les comptes system_agent
même mixtes. Le snapshot cible contient id/actif/rôles, sans nom/hash. Une correction historique
d’absence n’est pas bloquée par cette nouvelle restriction de temps : ses routes restent distinctes.
La proposition entière du vrai T0 est comparée à celle du domaine sur le snapshot canonique; le
port n’en change ni calcul ni contrat. Quota de sortie vérifié également sur refus métier minimisés.
Codes de refus métier connus affichés sans détails libres, sans zéro inventé et sans approbation
ou classification de payabilité. Toute réponse inattendue ou source modifiée est un refus technique.
Après rendu, admin avant recapture puis après; source et admissibilité cible inchangées requises.
Navigation via un second bouton GET du lookup existant (mêmes jour/personne), seul le lien est ajouté
aux écrans existants; aucune nouvelle requête de temps dans leurs projections. Catalogue inchangé.

Tests de cette tranche qualifient le stockage canonique, le vrai calcul T0 et HTTP; les pointages de
fixture sont inscrits par le registre M4. Ils ne requalifient pas le parcours complet inscription →
GPS → pointage terrain ni la paie. Pas de qualification de grande journée au-delà du plafond T0.


## Deux constats de revue à reproduire avant correction

La revue statique relève que le vrai T0 recharge encore nom/hash du SUJET via personne_active,
bien que le helper du cockpit soit minimisé. La garde de l’auteur reste hors de cette correction.
Mesurer le vrai T0 puis remplacer uniquement sa requête cible par une sélection d’admissibilité
active+employee équivalente, sans changer identité globale ou droits du T0.

Le domaine recopie aussi validation_precedente.revision sans type : une chaîne rehashée peut
contenir un dict dans revision; comparaison port/T0 identique ne suffit pas. Reproduire sur vrai
T0 et port, puis borner et valider les métadonnées précédentes dans le domaine, et whitelist
explicite des champs/types de la proposition dans le nouveau port. La correction ne constitue
pas une preuve de N4 : elle interdit une charge arbitraire et conserve la validation séparée.


## Qualification locale de la tranche

Le GET admin `/crm/journal-equipes/temps?jour=...&personne_id=...` est maintenant raccordé au
vrai T0 existant, avec proposition indépendante sur snapshot SQLite borné. Le lookup jour/ID
du journal et des absences offre un second bouton GET, sans consulter ou copier les temps dans
leurs projections. La page montre minutes nettes après pauses, déplacement et pauses séparés,
intervalles locaux avec offsets et références source; les intervalles sur site sont explicitement
bruts avant déduction des pauses. Aucun cumul doublant les pauses ou calcul monétaire ajouté.

Codes métier incomplets/ambigus/sans source : état indisponible sans total ni détail libre. Source
corrompue ou proposition inattendue : 503 sans chiffres. Compte actif/employee requis comme le T0,
avec exclusion complémentaire des comptes system_agent du cockpit, sans réactivation. La lecture
cible ne prend ni nom ni hash; l’authentification de l’auteur conserve sa garde existante.

Deux constats de revue ont été reproduits puis corrigés :
- Le SELECT du vrai T0 rechargeait nom/hash du sujet. `review-red-v1` le prouve par SQL sur le
  sujet exact; la correction est limitée à la sélection active+employee du T0 d’aperçu, avec
  même admissibilité native. L’API globale identite et les autres outils de paie sont inchangés.
- Une révision de validation précédente dict/bool/négative était recopiée dans le vrai T0.
  `review-red-v3` reproduit trois acceptations fautives sur chaîne native rehashée. Le domaine
  refuse désormais les types/références de métadonnées invalides. Le nouveau port ajoute aussi
  une whitelist des clés/types des catégories, intervalles, références et métadonnées. Trois
  contrôles distincts injectent une charge partagée par domaine ET T0 : elle reste refusée par
  le schéma du port, preuve que la comparaison seule ne fait pas office de validation.

`crm16-temps-v4` : **103 PASS, 0 FAIL/SKIP, 25,65 s**, dont 34 cas nouveaux SQL/T0/HTTP,
les 25 tests natifs d’heures (dont N4), les régressions sélecteur/formulaires et le masque q.
`crm16-temps-schema-v1` : trois contrôles complémentaires passent en 2,62 s, Source produit
identique entre ces phases. Les cohortes historiques 69 et suivantes se recoupent et ne sont
pas additionnées. Ruff et catalogue natif 303/177 passent, aucun outil ou droit ajouté.
Relecture statique indépendante des corrections : deux constats fermés, aucun résiduel concret,
sans runtime du relecteur. Preuve privée : `CRM16-TEMPS-LOCAL-QUALIFIED.json`.

Les rouges initiaux (module absent et deux logs non masqués), refus de lint et erreur de fixture
sans horodatage restent historiques. Ils ne sont pas tous des bugs produit. Données fictives,
Source RO Landlock, homes/tmp privés avant imports, réseau refusé, CPU1/mémoire1Gio/swap0/PIDs96.
Les tests inscrivent des pointages dans le registre propriétaire puis exercent vrai T0 et GET;
ils ne prouvent pas un nouveau parcours complet de pointage terrain ou de géolocalisation.

Statut **PARTIAL — aperçu individuel admin HTTP/SQLite qualifié localement**. Grandes journées
au-delà du T0 entier, historique des comptes désactivés, périodes traversant minuit, heures
payables/N4 journalières, présence réellement observée, M10, PostgreSQL, navigateur et mobile
restent ouverts. CI parent 19655886 au jalon de revue : 22 succès/4 SKIP/16 en cours/42 observés;
aucune publication anticipée, fusion ou production. Aucun salaire, paiement, export réel ou
modification de droits effectué.
