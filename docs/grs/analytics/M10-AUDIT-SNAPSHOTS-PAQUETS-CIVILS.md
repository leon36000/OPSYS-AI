# M10 — snapshots de paquets par préparation civile

## Objectif, pourquoi et état actuel

La navigation réelle de200 chantiers fictifs sur67 pages a coûté80,492 s et13400 appels T0
M10 (200 par page). Chaque `lire_paquet_affaire_appareil` relit et valide les deux chaînes SQL;
le pur `paquets.assembler_paquet_contexte` les copie/parcourt encore. La réponse paginée et
sa preuve globale sont correctes; la répétition constitue un coût mesuré à réduire.

Ce jalon vise les snapshots SQL/validations par préparation. Il conserve tous les vrais
appels T0 et ne promet donc pas de réduire leur nombre. Mesurer un avant/après compatible
sur SELECT complets, temps et ressources; ne pas annoncer un gain de débit sans ce résultat.

## Réutilisation et architecture décidée avant code

M10 possède déjà le patron privé `invocation_lecture_documentaire_appareil` (ContextVar,
connexion canonique, transaction active, refus d'imbrication, finally). Réutiliser ce mécanisme,
le vrai outil actuel et le pur assembleur; aucun framework, outil public, table ou manifeste
supplémentaire. La copie validée appartient à M10 et n'est pas fournie comme un argument modèle.

Créer `capture_paquets_appareil(cnx)` pour une seule préparation. Admission : connexion SQL
canonique SQLite et transaction d'origine actives, identité d'appareil présente/admin confirmé
courant; borner les deux registres avant décodage (10000 maillons/8Mio chacun). Capturer les
vrais registres canoniques, valider leurs chaînes une fois et exposer seulement copies de
faits/têtes au caller. Les lecteurs privés n'ont aucune méthode d'ajout et `lire` rend une
copie indépendante. Pas de registre mutable transmis au caller, ni de cache interrequêtes.

Lier la capture à connexion, transaction racine, savepoint d'origine et identité. Vérifier ces
liaisons avant toute réutilisation; chaque vrai T0 garde son contrôle SQL admin et `agent=None`,
son quota et sa provenance effectivement consommée. Marquer la capture inactive au finally
avant reset du ContextVar : une référence de contexte héritée ne doit plus fonctionner.
L'imbrication est refusée. Hors capture, l'outil conserve son parcours historique frais.

Le lecteur civil ouvre la capture après validation M4, utilise ses mêmes faits pour l'ancre
M3 et ses paquets, puis ferme avant toute mutation. Il conserve les contrôles de source et
d'autorité en fin de préparation. Après l'effet civil, une nouvelle lecture doit créer une
nouvelle capture; ne jamais réutiliser la capture d'avant l'effet pour le CAS après effet.
La formule de preuve et tous les champs renvoyés restent identiques (sauf heure volatile).

## Données, workflows, routes et permissions

M10 événements/affaires restent la vérité durable. Source_registres cite les têtes des copies
réellement consommées. M3 accepté vs manuel, omissions, signaux, origine et consolidation
conservent leurs règles. Un A→B→A SQL pendant lecture ne doit jamais produire des faits B
citant la tête A : consommer la copie A rend une lecture cohérente de A, sans prétendre détecter
une modification transitoire qui a été restaurée sans avoir été consommée.

GET/POST civils et T0 `m10_lire_paquet_affaire_appareil` existants, mêmes paramètres et rôles.
La capture privée n'accorde aucun rôle, ne remplace ni session ni personne SQL et n'écrit rien.
Aucun fait FINANCIAL/CLIENT_PRIVATE n'est ajouté au paquet; identité changée, révocation,
connexion/transaction terminée et capture héritée fermée doivent refuser avant retour.

## Fichiers, tests, risques et gates

Fichiers : M10 `outils.py`; console `memoire_chantier.py` et `memoire_plan_calendrier.py`;
aucun changement du calcul pur des paquets. Risques : liste mutable cachée derrière dataclass,
contexte trop long, nouvelle transaction sur même connexion, contamination entre acteurs,
quota vérifié trop tard, ancre M3 issue d'un autre snapshot, ancienne capture après mutation.

Tests : nombre de lectures complètes sur24 affaires; équivalence exacte paquet/preuve avant
et après; rôle révoqué entre deux vrais T0; SQL A→B→A et copie indépendante; capture fermée ou
héritée, mauvais acteur/connexion/transaction, exceptions/imbrication; bornes avant décodage;
confidentialité/quotas et vrai parcours200/67pages/date/rejeu sous ressources identiques.
Conserver les rouges et séparer prérequis/harnais et défauts produit. Réutiliser les preuves
compatibles, pas de cumul des populations.

**PARTIAL — audit et candidat à qualifier.** Pas de gate Nathan nouveau pour ce travail privé
réversible; aucune production, donnée réelle, permission, achat, paiement, merge ou déploiement.
M10 complet, routage réel/OSRMbatch, mobile, navigateur et PostgreSQL restent ouverts.
Prochain jalon : rouge de coût réel puis capture bornée et tests de sécurité avant mesure A/B.

## Qualification locale du 27 octobre 2026

Le candidat respecte ce contrat. Sur un vrai plan de 24 affaires fictives, la régression
observée avant modification était de **53 lectures SQL M10 complètes**; après capture elle
est de **4**, avec les **24 vrais T0 conservés**. Le test borne ces lectures à six pour
protéger ce coût. La capture ne mutualise aucune autorisation SQL : révocation en cours,
autre acteur, autre connexion, savepoint fermé, transaction remplacée sur la même connexion,
contexte hérité inactif et rôles insuffisants sont refusés.

L'équivalence exacte au T0 ordinaire, les quatre couches/confidentialité, les copies sans
alias, les quotas des deux sources avant premier décodage, la chaîne corrompue, le nettoyage
sur exception et le refus d'imbrication passent. Le cas SQL A→B→A consomme A et cite A;
une préparation ultérieure relit B lorsque B devient la source actuelle. Les contrôles
civils existants refusent toujours une tête ou une autorité modifiée en fin de lecture.
La revue statique indépendante n'a trouvé aucun défaut concret; elle ne remplace pas ces tests.

Le même parcours de 200 chantiers fictifs a été mesuré séparément, avec exactement les deux
cas de la baseline, leurs fichiers de test inchangés, le même extra PyVRP 0.14.0 et les mêmes
limites effectives : un CPU, 1 Gio, swap nul, 96 processus, réseau interdit, Source en lecture
seule et homes/tmp privés avant imports. Les 2280 fichiers de dépendances privées ont été
revérifiés contre leur inventaire d'acquisition.

| Mesure du même scénario local | Avant | Après capture |
|---|---:|---:|
|Navigation complète, 200 visites / 67 pages|80,492 s|31,290 s|
|Vrais appels M10 pendant cette navigation|13400|13400|
|Plus grande réponse JSON|46275 octets|46275 octets|
|Mémoire maximale du groupe QA|160591872 octets|160018432 octets|
|RSS maximal des enfants QA|174460928 octets|175763456 octets|

Le temps observé baisse de **61,1 %**, soit **2,57 fois plus rapide dans ce scénario**.
Il s'agit d'une paire d'observations, pas d'une distribution de latence ni d'un SLA.
La formule historique de preuve globale, le parcours sans perte/doublon, la vraie confirmation
des dates et le rejeu sans effet restent vérifiés. Les copies/parcours du pur assembleur et
les 13400 T0 demeurent : aucun coût constant ou gain réseau n'est revendiqué.

Preuves : `M10-CAPTURE-FINAL-QUALIFIED.json` dans le chantier CRM; commandes, limites,
pins, logs, JUnit et reçus `m10-capture-*` dans le répertoire QA privé. Les seize contrôles de
sécurité/coût/équivalence et le cas réel 200 passent ensemble (17 PASS); le contrôle complémentaire
de remplacement de transaction passe séparément. La cohorte de régression antérieure conserve
299 PASS et un échec de test dû à l'import d'une fonction au lieu du module `moteur`, corrigé
et requalifié dans les seize contrôles. Les fichiers produit et les autres tests sont identiques
entre cohortes; les populations recoupées ne sont pas additionnées. Les rouges de coût, oracles
erronés et refus au lint restent dans l'historique. Ruff et le vérificateur 297/173 passent.

**PARTIAL — tranche SQLite locale qualifiée, non déployée.** Prochaine action : profiler les
copies/parcours purs par affaire, puis décider d'un index interne au propriétaire M10 seulement
si l'équivalence complète des paquets et leur confidentialité peuvent être prouvées. Routage
réel/batch OSRM, dispatch global, navigateur, PostgreSQL, mobile et qualification globale des
modules restent ouverts. Aucun envoi client/fournisseur, paiement, droit, fusion ou déploiement.
