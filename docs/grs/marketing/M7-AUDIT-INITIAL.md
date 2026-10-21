# M7 — audit initial contenu et calendrier durable

Date du constat initial : 2026-09-30. Périmètre : usine contenu chantier, approbation, export manuel et calendrier.

**Note de statut, actualisée le 2026-10-01 :** cet audit précède la tranche historique du calendrier durable et la console Brand Core. Ses énoncés d’absence de calendrier durable sont historiques. Brand dispose maintenant d’une page et d’une API montées dans `creer_application`, avec lecture courante et mutation propriétaire; admin est en lecture seule et les deux contrôles live empêchent une révocation propriétaire entre parsing et exécution de créer une approbation. La page ne montre ni date ni historique; le contrat MCP direct conserve un horodatage fourni par l’appelant. Voir la [matrice des quinze capacités M7](M7-MATRICE-CAPACITES-2026-09-30.md) pour l’état actuel, les sources et tests pertinents, la validation intégrée datée et les limites des autres capacités.

## Actualisation R18 — 1er octobre 2026, clôture à 16:54:58 UTC

Les constats d’absence de calendrier durable et de stockage/aperçu média réel sont historiques. M7.3a est intégré localement : variantes JPEG/PNG préparées humainement dans le CAS, snapshot du WCT reçu complet et du texte/marque/consentement, revue propriétaire et remise privée sous approbations courantes de texte et de créneau. Il réutilise le stockage et la console existants, sans nouveau backend ni outil MCP. La préparation humaine ne prouve pas un floutage ou nettoyage EXIF automatique.

La campagne intégrée root du 1er octobre 2026, exécutée de **16:52:48 à 16:54:58 UTC**, passe **1 377 cas**, sans échec, erreur ni skip, en **128,406 s JUnit** : **1 038 M7**, **248 console**, **82 fichiers/stockage/idempotence** et **9 E2E chantier par MCP sur SQLite**. Les sept cas du pliage média sont inclus dans M7 et les dix-neuf cas de console média dans la console; aucun de ces sous-comptes ne s’ajoute au total. Deux cas PostgreSQL ont été désélectionnés par `-k not postgresql`, ce ne sont pas des skips. L’ensemble surveillé de **1 066 chemins sources sélectionnés** est identique avant/après; il ne constitue pas une fermeture de tout le dépôt. Les dix-neuf cas média comprennent des tests HTTP, un test direct du parseur ASGI et un oracle de garde substituée; ils ne sont pas dix-neuf parcours complets de bout en bout.

La tranche demeure **PARTIELLE** : aucune publication ou connexion fournisseur, transformation automatique des images, analyse des pixels, suppression EXIF, surface mobile M7 dédiée, essai navigateur réel ou qualification VPS. Les attestations de préparation et de revue restent humaines. Les nouvelles écritures médias refusent PostgreSQL; aucune concurrence PostgreSQL pour ce registre n’est qualifiée. Le catalogue reste à **10 départements, 207 outils et 116 outils déclarés aux appareils**; aucun outil MCP n’a été ajouté. Voir la [matrice actualisée](M7-MATRICE-CAPACITES-2026-09-30.md) et le [document du parcours média](../../../departments/m07-marketing/docs/M7-3A-MEDIAS.md). Les conclusions ci-dessous restent celles du constat du 30 septembre; elles ne décrivent pas l’état actuel de cette tranche.

## Qualification R19 — M7.4a lecture Growth (1er octobre 2026)

Le code M7.4a intégré par ROOT R6 à 18:01:32 UTC sur sept chemins ajoute une lecture privée des observations du registre `growth`, avec source/preuve et confiance déclarées visibles. Elle ne prouve aucune saisie humaine; l’auteur et sa provenance sont inconnus, la référence textuelle n’est pas vérifiée à l’extérieur ni dans le CAS. Admin ou propriétaire actuellement actif est contrôlé avant lecture, puis dans une transaction fraîche avant réponse.

Le lecteur valide les observations et leur empreinte avant le filtre; une corruption hors période provoque aussi un refus. Son budget couvre tout le registre : **1 000 maillons**, **32 Ki caractères par maillon**, **1 Mi caractères au total** de texte JSON, pas des octets. Le filtre fermé accepte au plus **366 jours inclusifs** et seulement les observations entièrement incluses. Chaque page relit un préfixe borné; aucun instantané multipages n’est fourni. Les anciens plans ne sont ignorés qu’après contrôle de leur forme top-level exacte, sans qualification de leur contenu sémantique. L’empreinte locale ne rend pas la chaîne inviolable.

Aucune création de plan, croissance, causalité, ROI ou publication n’est produite. La page vide ne prouve pas zéro activité. Cette actualisation R19 référence les résultats ROOT clos, sans reprendre un compte auteur/QA comme campagne ROOT ni additionner R18. Voir la [matrice M7](M7-MATRICE-CAPACITES-2026-09-30.md) et le [document du lecteur](../../../departments/m07-marketing/docs/M7-4A-GROWTH-LECTURE.md). Les constats initiaux ci-dessous restent historiques.

La campagne intégrée ROOT du 1er octobre 2026, de **18:01:32 à 18:03:51 UTC**, passe **1 436 cas**, sans échec, erreur ni skip, en **137,133 s JUnit** : **1 066 M7**, **279 console**, **82 fichiers/stockage/idempotence** et **9 E2E chantier MCP SQLite**. Les **59 cas Growth (28 lecteur + 31 console)** sont inclus dans ces groupes, sans addition. Deux cas PostgreSQL sont désélectionnés par `-k not postgresql`; ce ne sont pas des skips. Les **1 070 chemins sources sélectionnés** sont identiques avant/après; cet ensemble n’est pas une fermeture de tout le dépôt. Ruff sur sept fichiers et le catalogue (**10 départements, 207 outils, 116 déclarés aux appareils**) passent dans des commandes distinctes. Les qualifications R18 et antérieures gardent leurs arbres; leurs comptes ne s’ajoutent pas à 1 436.

Preuves ROOT closes : [résultat](../../research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-resultat-json-39d3b4870b.gz) · [JUnit](../../research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-xml-c8db58b5f3.gz) · [journal](../../research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-log-8c7e9f181c.gz) · [promotion R6](../../research/R20-2026-10-01/preuves/r19-m74a-integration-root-r6--resultat-json-1909dc8172.gz) · [Ruff](../../research/R20-2026-10-01/preuves/r19-preuves--m74a-ruff-root-r1-2026-10-01-resultat-json-3fb7557c96.gz) · [catalogue](../../research/R20-2026-10-01/preuves/r19-preuves--m74a-verifier-root-r1-2026-10-01-resultat-json-032e699528.gz) · [lecture indépendante](../../research/R20-2026-10-01/preuves/r19-m74a-cloture-independante-r1--rapport-json-190e148f67.gz). Ces preuves sont conservées dans les archives R20, sans modifier le R19 scellé du 30 septembre.

## Constat avant choix d'implémentation

Le chemin chantier n'est pas une simple fabrique en mémoire. `departments/m07-marketing/src/m7_marketing/usine/service.py` persiste la réception WCT, les brouillons versionnés, les décisions, les exports et retraits par `opsys.stockage.maillons`. Il revalide l'acteur propriétaire depuis l'identité d'appareil vérifiée ou l'approbation native, le hash exact du texte, les contrôles de texte et le consentement au moment de décider et d'exporter. Le retrait bloque les brouillons et exports futurs ; un paquet déjà remis exige un retrait manuel.

Les modules `content/approval.py` et `content/factory.py` n'offrent qu'une file process-local générique. Ils ne conviennent pas comme source canonique durable. `workflows/campagne_saisonniere.py` fabrique des items génériques depuis un calendrier YAML statique et les soumet à cette file en mémoire. Il ne constitue pas un calendrier éditorial de chantiers.

Le paquet (`usine/paquet.py`) est explicitement une remise manuelle : aucune API de plateforme, programmation ou preuve de publication n'est fournie. L'export existant enregistre le contenu et son horodatage, mais aucun créneau éditorial durable n'existe dans les registres inspectés.

## Décision de tranche

Le premier ajout sera un journal calendrier append-only dans le stockage canonique OPSYS, relié à un contenu chantier existant par son `contenu_id`, sa révision, son WCT source et son empreinte exacte. L'approbation de créneau sera un acte propriétaire distinct et versionné. La remise officielle restera manuelle, exigera les deux approbations actuelles et réévaluera retrait, consentement et hash avant d'écrire une preuve de remise comprenant source, identifiant et heure serveur. Aucun statut ne signifiera publication ni métrique de plateforme.

Les prix ou garanties ne seront pas introduits : les règles existantes de contrôle de texte et leur refus restent applicables. Aucun registre SQL ou graphe secondaire ne sera ajouté.

## Sources et limites

- `docs/research/R16-2026-09-30/recherche-m7.md`, lignes de constat M7.2/M7.3 et recommandations : conserver l'usine native et commencer par publication manuelle ; calendrier M7.2 absent.
- `departments/m07-marketing/src/m7_marketing/usine/service.py`, `registre.py`, `decision.py`, `retrait.py`, `paquet.py` : parcours canonique source et mécanismes à réutiliser.
- `departments/m07-marketing/src/m7_marketing/content/approval.py` et `workflows/campagne_saisonniere.py` : primitives en mémoire, non adaptées à une reprise durable.

L'audit historique R16 mentionne 992 tests au HEAD du rapport ; ce chiffre n'est pas un nouveau résultat de cette tranche. Ce document ne conclut pas à la complétude de M7.
