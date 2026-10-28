# CRM-10 — audit des coûts des travaux depuis le devis

## Objectif, pourquoi et état actuel

La secrétaire demande le coût d'une job, ses matériaux, sa main-d'œuvre et l'écart prévu/réel.
CRM-10 reste « outils existants / écran manquant » dans la matrice du cockpit. La section
`couts` de `crm_ui.py` affiche seulement cette explication. Le dossier M2 et la consultation
M3 des soumissions existent; la planification CRM-08 n'est pas un prérequis pour consulter
le coût d'un chantier terminé. Aucun port ni écran nouveau n'est implémenté par cet audit.

M5 possède déjà `m5_lire_rentabilite_chantier`, vrai T0 admin. Il lit les devis acceptés reçus,
WCT, variances M6, factures actives, prix M6, taux configuré et traces de rentabilité.
`_etat_chantier` calcule avec `cout_reel.py`; `_vue_chantier` expose attente, calcul partiel ou
complet, coûts, hypothèses et `trace.a_jour`/`version_entrees`. La lecture n'écrit pas la trace.
Le calcul utilise les prix/taux courants; cette vue ne prouve pas une dépense payée ni un coût
historiquement figé. Une facture brouillon n'est pas un prix définitif.

## Architecture minimale et réutilisation

Réutiliser M2/M3 pour l'ancrage client/devis, puis le T0 M5. Aucun nouveau calcul de montant,
quantité, total, écart ou marge dans le cockpit; pas de nouveau framework ni table financière.
Le port console privé doit lire un devis accepté exact, lié au lead exact, vérifier sa vraie
publication M3 et sa réception M5, puis demander un seul devis à l'outil propriétaire. Ne pas
supposer `lead_id == chantier_id` et ne pas inventer une liaison de job.

Reprendre les gardes SQL/quotas/outil T0 de `preparation_chantier.py`, sans appeler son lecteur
complet : celui-ci concerne M4 et la readiness, étrangères à cette consultation financière.
La projection de devis doit rester validée par M3; `devis_recus.construire` M5 définit les champs
que sa réception copie. Statuts de réception en attente/échec/quarantaine doivent rester explicites.
Une réponse partielle/tronquée ou un filtre sans correspondance ne devient jamais un coût zéro.

Point de preuve à résoudre avant de qualifier le port : une simple tête relue avant/après
ne lie pas le calcul aux sources réellement consommées si une source est substituée puis
restaurée pendant le T0. Capturer des entrées canoniques bornées, utiliser les fonctions M5
pour vérifier la projection/version attendue et comparer au vrai T0; recontrôler les sources
et l'admin à la fin. Toute arithmétique reste dans M5. Réutiliser un contexte propriétaire
existant s'il couvre effectivement ce contrat; ne pas copier un cache de cashflow inadapté.
Les aides de `console/finance_snapshot_prive.py` concernent cash/obligations, pas ce calcul.

## Fichiers, routes et données

Surfaces prévues : `console/rentabilite_chantier.py` (port/rendu puis route), raccord dans le
routeur existant et lien depuis la fiche de soumission. Route envisagée :
`GET /crm/lead/{lead_id}/soumissions/{devis_id}/couts-travaux`, uniquement admin authentifié.
Aucun POST, bouton d'envoi, écriture de rentabilité, facture, paiement ou changement de prix.

Sources : M2 principal; M3 devis/principal et publication d'acceptation; réception M5; M5
`devis_recus`, `wct_recus`, `variance_recue`, `factures`, `rentabilite`; M6 `livre_prix`;
configuration du taux horaire M5. Inspecter leurs formats exacts et toutes dépendances de la
projection avant de fixer le catalogue de captures; borner lignes et octets avant décodage.
Les identités, montants et adresses ne viennent jamais des paramètres d'affichage.

## Workflows et intégrations

Devis M3 accepté et source vérifiée → état de réception M5 → vrai T0 du devis exact →
validation de la réponse/source/version → rendu admin préparatoire. WCT absent : attente
travaux terminés; prix/taux manquant : coût partiel nommé; trace décalée : avertissement.
Matériaux et main-d'œuvre sont rendus depuis leurs blocs M5; extras et autres dépenses ne
sont pas inventés si le contrat actuel ne les couvre pas. La matrice doit garder ces gaps.
Aucun appel M8/M9/M10 d'écriture lors d'un GET; aucune reconstitution de leur mission.

## Permissions, risques et gates Nathan

SQLite canonique qualifié d'abord; personne SQL admin actuelle et session non expirée avant
les sources, identité appareil issue du serveur pour chaque T0, recontrôle après lecture.
Vendeur, employé et client ne voient pas les coûts/marges; aucun rôle ou droit fourni en URL.
Refus fermé sur source incohérente, trop volumineuse, contrat inconnu ou perte de rôle.
Échapper le rendu, conserver no-store/CSP, refuser les paramètres superflus et borner le HTML.

Risques concrets : devis d'un autre lead, réception altérée, doublon de devis reçu, WCT d'un
autre devis, source A→B→A, configuration changée pendant le calcul, confusion trace ancienne/
calcul actuel, réponse T0 tronquée, lecture qui déclenche une cascade, affichage d'un manque
comme zéro et cumul de montants côté UI. Aucun gate humain nouveau pour cette lecture privée
réversible. Paiement, envoi, approbation financière, production et déploiement restent hors scope.

## Tests et statut

Réutiliser `tests/test_console_preparation_chantier.py`/son vrai bus M1/M2/M3 et les fixtures
M5 `test_lecture_rentabilite.py`. Distinguer complétion contractuelle fictive de M4 et vraie
exécution M4 : ne pas attribuer l'une à l'autre. Vérifier devis accepté en attente M5/WCT,
coût complet/partiel, source de prix et taux modifiés, facture brouillon/émise, devise étrangère,
revocation/session, confusion lead/devis/chantier, quota avant décodage, A→B→A et sources
consommées. Comparer toutes tables SQL avant/après GET, y compris reçus/outbox/traces M10.
Puis HTTP/lien/rendu échappé/no-store/erreurs et cohorte de régression pertinente.

**PARTIAL — audit initial, capacité nouvelle non commencée.** Prochaine action précise :
figer l'ancrage M3→réception M5 et les sources/version du calcul, écrire un premier test de
port privé en attente de WCT, puis implémenter cette lecture sans écran ni effets financiers.
L'écran et ses tests suivront après qualification du port; PostgreSQL/navigateur/mobile et
couverture complète de tous les coûts demeurent ouverts.

### Décision de la première tranche privée

Extraire uniquement l'assemblage des entrées de coût dans un helper privé M5; le calcul et
la présentation propriétaire restent inchangés et leurs tests existants font foi. Le port
capture les vrais registres canoniques avec `copier_maillons_avec_metadonnees`, après bornes
sur toutes sources. Il fournit ces copies au helper M5 pour établir la projection attendue;
la compare au vrai T0 et à sa version. Les prix/taux ne sont jamais reçus en arguments et
aucune formule n'est dupliquée. La configuration M5 est bornée/hashée, avec absence explicite.
Les copies et références sont relues à la fin pour refuser changement de source ou de rôle.
Préserver les cas M3 non publié/M5 en attente sans appeler un calcul financier sans source.
L'écran HTTP attend la qualification de ce port; cette tranche n'ajoute aucune route publique.

## Qualification locale du port privé

Le port `console/rentabilite_chantier.py` est qualifié sur SQLite, sans route HTTP ni rendu.
Il lie le devis M3 accepté exact, sa publication et sa réception M5 aux copies canoniques
bornées. Le vrai T0 M5 doit produire la même projection que les fonctions M5 appliquées à ces
copies. Les références sont des empreintes calculées de snapshots SQL, pas des reçus natifs
supplémentaires. Les formules, arrondis et sélections de coût restent dans M5; le cockpit ne
fait aucune arithmétique. Le taux attendu est extrait des octets de manifeste effectivement
capturés/hashés. La mention préparatoire M5 accompagne aussi la vue privée.

La revue indépendante a identifié deux défauts de candidat, puis la vérification négative
un troisième : configuration A→B→A acceptée, facture altérée sans rechaînage acceptée et
révocation pendant la dernière relecture acceptée. Ils ont tous été reproduits (3 FAIL,
2 positifs PASS) avant correction. Le helper M5 valide maintenant la chaîne des factures,
y compris dans le T0 ordinaire; les reçus plats ne sont pas artificiellement chaînés. L'admin
est relu en dernier. La configuration attendue et celle consommée par le calcul ne peuvent
plus être associées à des octets différents sans refus. Revue corrective sans défaut résiduel
concret dans ce périmètre.

`crm10-port-v5` :263 PASS en26,57 s, dont15 contrôles du port et248 tests existants de coût,
accès et mention M5. `crm10-port-v6` :24 PASS en2,57 s, dont un contrôle supplémentaire du
vrai T0 refusant la facture corrompue et la conformité M5. Source produit identique entre ces
cohortes; seul ce test a été ajouté. Ne pas additionner ces populations comme une couverture
produit globale. Ruff et le vérificateur297/173 passent. Les erreurs d'import de candidat,
refus au lint et les trois rouges de revue sont conservés dans les preuves distinctes.

Le parcours utilise M1/M2/M3 et la réception M5 réels sur données fictives; pour les coûts,
la complétion M4 et la variance sont des charges contractuelles fictives livrées par le vrai
bus M5. Il ne prouve donc pas une nouvelle exécution terrain M4 complète. Coût complet486,00,
prix courant modifié822,00, trace décalée, taux absent/coût partiel sans faux zéro, devis/lead
étranger, doublon, reçu/publication modifié et quota avant décodage sont vérifiés. Les lectures
positives et refus sans injection comparent toutes les tables avant/après, sans écriture ni
réparation, y compris factures, traces et outbox. Aucune facture réelle n'est créée ou envoyée.

Preuve : `CRM10-PORT-LOCAL-QUALIFIED.json` dans le chantier CRM, avec commandes, JUnit, logs,
pins et limites du QA privé (un CPU/1Gio/swap0/96 processus, réseau interdit, Source en lecture
seule, homes/tmp privés avant imports). **PARTIAL — port privé seulement.** Prochaine action :
raccord HTTP admin de consultation et lien depuis le devis, sans formulaire de mutation;
afficher attente/partiel, sources, hypothèses, prix/taux actuels, trace et mention préparatoire.
Browser, PostgreSQL, mobile, extras/dépenses non couverts et coût payé/historiquement figé
restent ouverts; aucun gain de couverture n'est attribué aux tests recoupés.

### Décision avant raccord HTTP

Ajouter un GET admin sans paramètres ni action au routeur CRM existant, depuis le devis
accepté seulement. Réutiliser le port qualifié; aucun nouveau calcul ou accès direct financier
dans le rendu. Afficher les blocs propriétaires M5, leurs manques/hypothèses et sources de prix,
le caractère actuel/préparatoire, facture non définitive et trace antérieure. Toute valeur
absente reste « Non disponible ». Échapper chaque valeur, garder no-store/CSP et plafond HTML;
refuser POST et toute requête superflue. Qualification HTTP/SQLite distincte du navigateur.

## Qualification locale de la consultation HTTP

Le GET `/crm/lead/{lead_id}/soumissions/{devis_id}/couts-travaux` est raccordé depuis le
devis accepté. Il présente les coûts/prix prévus M5, coût calculé/connu, matériaux, minutes et
taux, marges, sources de prix M6, hypothèses, manques et trace actuelle/ancienne. Aucun calcul
n'est ajouté au cockpit. Les fonctions du port privé qualifié sont inchangées (AST comparé).

Un rouge de revue a reproduit un HTTP200 après révocation de rôle pendant le rendu. Lecture,
rendu, quota HTML et dernière vérification SQL admin sont maintenant dans la même transaction;
ce cas retourne403 sans chiffres. Les valeurs sont échappées, le HTML limité à128Kio,
POST405, paramètres400, sources indisponibles503, no-store/CSP conservés. Les contrôles sans
injection comparent toutes les tables avant/après, sans mutation financière ni réparation.

Preuves locales distinctes : `crm10-http-v2`62 PASS en22,88s (11 cas HTTP et régressions de
port/préparation/modèles); `v3`2 PASS en2,14s, mêmes cas complets/partiels après ajout des deux
montants prévus. `v4`54 PASS et un échec de l'ancienne liste exacte de sections affichées;
seule cette attente a été mise à jour pour inclure « coûts ». `v6`1 PASS en1,10s vérifie cette
attente corrigée; les autres pins produit/tests de v4 sont identiques. Les refus lint v5 et
les rouges restent archivés. Ces cohortes se recoupent : aucun total cumulatif. Ruff et le
vérificateur297/173 passent. Commandes, JUnit, pins, logs et bornes sont liés par
`CRM10-HTTP-LOCAL-QUALIFIED.json`, dans le chantier CRM.

**PARTIAL — consultation admin HTTP/SQLite qualifiée localement.** Les événements M4/variance
de la fixture sont toujours contractuels fictifs reçus par le vrai M5, pas une nouvelle preuve
de chantier M4 complet. Aucun coût payé/historiquement figé, extras/dépenses complets,+navigateur natif, PostgreSQL ou mobile n'est qualifié. Prochaine action : publication normale
après CI du parent terminale, puis journal quotidien CRM-16 avec audit avant code.
