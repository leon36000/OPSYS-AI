# M3 — couverture des réceptions d’apprentissage

État au 5 octobre 2026 : diagnostic local qualifié sur SQLite, apprentissage empirique et complétude du corpus entreprise non prouvés. **173 cas passent dans sept fichiers complets en r382**, Ruff et vérification des manifestes réussis. Cette tranche ne change aucun barème ni aucune politique d’admission des cohortes.

## Problème et résultat

La calibration existante énumère les WCT déjà reçus dans `estime_vs_reel`. Elle ne pouvait pas révéler un événement de fin de chantier publié par M4 mais absent de cette réception. Le nouveau diagnostic compare les identités des publications `m4.travaux_termines` du bus de cette instance aux identités du registre M3, avec le préfixe canonique existant. Il rend les nombres recoupés, manquants et hors univers, ainsi que dix exemples maximum par différence.

Un chantier M4 réel du scénario d’intégration apparaît manquant avant livraison. Après une livraison distincte du bus à M3, il apparaît reçu. Les tables du bus et des registres restent identiques avant/après chaque invocation du diagnostic. Les données du scénario sont fictives; aucun corpus client ni gain de précision n’est mesuré.

## Contrat et sources

- `m3_auditer_couverture_apprentissage` : outil T0/N0, sans paramètres, réservé à un administrateur actif authentifié par appareil. Aucun accès vendeur, console ou agent; aucune identité fabriquée si le contexte manque.
- [Inventaire socle](../../../src/opsys/evenements/inventaire_calibration.py) : projection SQL des seules identités et du contrôle de producteur du bus; lecture des réceptions via le codec canonique après bornes SQL.
- [Comparaison M3](../../../departments/m03-estimation/src/m3_estimation/couverture_apprentissage.py) et [raccord outil](../../../departments/m03-estimation/src/m3_estimation/outils.py) : double relecture des sources, scellement du préfixe et revalidation du rôle avant restitution.
- [Tests du diagnostic](../../../tests/test_couverture_apprentissage.py) et [scénario M4 réel](../../../departments/m03-estimation/tests/test_calibration_promotion_sdk.py).

Version de réponse : `couverture-apprentissage-identites/1`. États : `ecarts`, `identites_recues`, `univers_vide`. Une erreur de source, de rôle, de format ou de limite produit un refus explicite, sans compteurs inventés. Un univers vide ne prouve pas la bonne santé de l’apprentissage.

## Bornes et confidentialité

Le lecteur exige une transaction canonique déjà ouverte sur SQLite; PostgreSQL est explicitement refusé par `backend_source_non_qualifie`. Il ne crée ni ne migre de base. Au plus 2 000 publications sont admises, avec lecture SQL limitée à 2 001 lignes. Les identifiants sont ASCII, de 1 à 128 caractères. Le producteur attendu est `m04-field-ops`; une divergence ferme le diagnostic au lieu d’effacer silencieusement la ligne.

Les réceptions sont bornées avant décodage : 20 000 maillons, 65 536 octets par maillon, 4 000 000 octets cumulés, puis au plus 2 000 identités uniques. Les listes d’exemples sont triées et limitées à dix. La charge des événements n’est jamais sélectionnée ni décodée : aucune photo, position GPS, adresse, donnée de technicien ou valeur financière ne sort de ce lecteur. Ces bornes ne constituent pas un benchmark du coût du scan SQL.

SQLite sérialise les écritures avec la transaction actuelle `BEGIN IMMEDIATE`. Le test de révocation injectée vérifie le contrôle défensif dans cette transaction; il ne prouve pas qu’une révocation concurrente interrompt une lecture déjà engagée. Les empreintes détectent les changements de listes; elles ne sont pas des signatures de provenance.

## Ce que les compteurs prouvent

Ils comparent **des identités de publication et de réception**. Le contenu WCT, la correspondance de sa charge avec sa clé, sa qualité terrain et l’exhaustivité historique M4 ne sont pas vérifiés ici. La réponse conserve `contenu_wct_verifie: false`, `completude_corpus_m4: non_prouvee` et `candidate_active: false`.

Une réception hors univers peut être ancienne ou importée : aucune cause n’est inventée. Le diagnostic ne distribue pas le bus, ne répare pas le registre, ne réessaie pas un effet métier et n’active pas une calibration. Les contrôles d’apprentissage existants demeurent nécessaires. Aucun écran dashboard, nouveau fournisseur ou dépendance n’est ajouté.

## Qualification et corrections

Les sept fichiers complets de r382 couvrent le diagnostic, la promotion SDK, le raccord, les cohortes, la promotion, la lecture individuelle de chantier et les portées appareil. Résultat : **173 réussites, zéro échec, erreur ou test ignoré**. Les nouveaux cas vérifient les quotas inclusifs, les identifiants invalides, les producteurs divergents, les charges non lues, les doublons de réception, les sources modifiées, les tables absentes, les refus de rôle/backend et l’absence de mutations du diagnostic.

Historique conservé : r378 rouge avant implémentation; r379 comportement vert mais import Ruff incorrect; r380 rouge avec cinq échecs, dont le parcours PostgreSQL Docker bloqué par manque d’espace et quatre attentes de droits devenues obsolètes; r381 rouge avec deux attentes administrateur restantes. r382 remplace ces qualifications incomplètes sans additionner leurs tests. Le fichier historique `tests/test_evenements.py` et PostgreSQL ne sont pas déclarés entièrement verts. Un essai Ruff hors garde a également échoué faute d’espace pour son cache; le contrôle final utilise le cache RAM borné et passe.

Les attentes et la [table des rôles](../../architecture/ROLES.md) ont été alignées sur les outils déjà livrés : 125 outils déclarent des rôles appareil sur 217, avec 14 accessibles à l’employé, 15 au vendeur et 124 à l’admin. L’inventaire vendeur reste réservé au vendeur; aucune permission existante n’est élargie par la correction des compteurs.

La revue Luna ciblée n’a trouvé aucun défaut concret dans les sources relues; elle décrit les limites de transaction et ne remplace pas les tests ROOT. Préimages, variantes exactes des sources, essais rouges, reçus de garde et revues sont conservés dans la [capsule de preuves](../../research/REPRISE-2026-10-05/preuves/M3-COUVERTURE-APPRENTISSAGE-r1.tar.xz) et son [manifeste](../../research/REPRISE-2026-10-05/preuves/M3-COUVERTURE-APPRENTISSAGE-r1.json).

## Suite

Raccorder ce diagnostic au pilotage admin avec les mêmes droits; qualifier PostgreSQL dans un environnement disposant des ressources nécessaires; mesurer l’apprentissage sur un corpus client consenti, séparé en entraînement et validation. La réception manquante doit d’abord être expliquée et corrigée par les mécanismes existants avant toute promotion de modèle. Publication privée préparée localement; aucun push, déploiement, autonomie permanente ou achèvement global revendiqué.

## Raccord ultérieur du 5 octobre 2026

La tranche historique ci-dessus ne livrait pas d’écran. Le [raccord console natif](M3-CONSOLE-APPRENTISSAGE-RAPPORT-2026-10-05.md) ajoute désormais une page et une API sous session humaine admin/owner, sans élargir l’outil appareil ni fabriquer son identité. Qualification ROOT r392 : 225 cas dans sept fichiers complets et Ruff. La complétude du corpus et les gains d’apprentissage restent non prouvés.
