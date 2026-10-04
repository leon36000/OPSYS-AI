# Reprise OPSYS — plan d'implémentation

Objectif : compléter les départements existants selon la [vision issue des instructions de Nathan](../produit/VISION-ENTREPRISE-APPRENANTE.md).
Architecture : core et socle existants, adaptateurs bornés, sources transactionnelles et événements.
Socle technique : TypeScript core, Python/FastAPI/SQLAlchemy, mémoire PostgreSQL/pgvector existante;
services spécialisés à qualifier séparément. Exécution : chef de projet et délégation Luna autorisée,
un propriétaire par surface de modification. Publication en branche et dans la PR #623 explicitement autorisée ; aucune fusion de main ni aucun déploiement autorisé.

## Contraintes et risques de revue

- Identité et droits revérifiés avant lecture et avant réponse; aucune autorité déduite du cookie seul.
- Aucun secret/endpoint privé affiché, stocké dans ce catalogue, ou copié dans les traces.
- Configuration présente ≠ validation locale ≠ authentification distante ≠ autorisation d'écriture.
- Source absente, hors périmètre ou contradictoire : limite explicite; pas de réussite par défaut.
- Réutiliser les preuves sans additionner des suites recouvrantes; préserver tous les rouges.

## Lot 1 — espace Connecteurs, première tranche

Spec : [audit préalable](REPRISE-AUDIT-2026-10-02.md), section Dashboard de la vision.
Fichiers : créer `src/opsys/console/connecteurs_ui.py`, `tests/test_console_connecteurs.py`;
modifier seulement montage dans `application.py` et onglet dans `pages.py`.
Interface : `etat_connecteurs(environ, deps)` retourne les prérequis connus et présence déclarée;
`creer_router(session_page, session_api, cnx_factory, deps, prefixe)` monte GET `/connecteurs`
et `/api/connecteurs`. API privée admin/owner, aucun POST ni appel fournisseur.

- [x] Prouver les routes manquantes par test HTTP et oracle 200 contre 404 avant changement.
- [x] Réutiliser `canaux.CANAL_SMS.variables`, constantes STT/embeddings et DSN mémoire existants.
- [x] Montrer les paramètres manquants et les capacités encore à construire, sans valeurs.
- [x] Tester absence de session, rôles non autorisés, retrait/désactivation pendant lecture,
      configuration vide/invalide, secrets et absence d'appel réseau; contrôler quatre tables métier.
- [x] Exécuter les tests affectés, la console, E2E chantier et Ruff/catalogue sur état intégré.
- [x] Mettre à jour bilan/matrice de ce lot et conserver empreintes/commandes/limites.

Cette tranche ne modifie pas les secrets et n'installe pas de connecteur. La configuration
interactive complète exige le contrat de secret et les adaptateurs du lot 2.

### Tranches suivantes qualifiées localement — R22

- Lot 2, première tranche : [configuration STT persistante](LOT-CONNECTEUR-STT-PERSISTANT.md)
  et [mode d'emploi](../architecture/CONNECTEURS-STT.md). Qualification root : 151 tests intégrés,
  1 075 sources surveillées stables, un PostgreSQL désélectionné. URL/modèle/clé ne sont pas
  conservés en base : seuls leurs noms de référence le sont. Le contrôle manuel `/models` ne
  qualifie pas une transcription ni une authentification distante. Les autres connecteurs restent
  hors de cette tranche.
- Lot 3 : [pilote CSV financier durable](LOT-FUSION-CSV-COMPTABLE.md), qualifié localement;
  [utilisation et exploitation](../architecture/FUSION-CSV.md).
  AES-GCM de `cryptography` 50.0.2, clé externe, snapshot M5, reprise transactionnelle, provenance
  documentaire M10 sans fausse affaire. PDF/OCR et ingestion massive générale restent à construire.
- Lot 9, correction C02 : [création d'un brouillon M3 sous contexte M10](LOT-C02-CREATION-DEVIS-M3.md),
  qualifiée localement. Cible lead exacte, chantier nul ou identifiant lead v1, collision d'identifiant
  revérifiée; niveaux et validations existants conservés. L'exclusion historique avait une raison
  valide et n'est pas levée par simple ajout nominal à la liste des outils.
- Lot 5, préalable : [capture des entrées de durée](CALIBRATION-TEMPS-PREPARATION.md), qualifiée
  localement. Service/quantité/unité/version/taux/empreinte gardés dans la trace M3; temps marqué
  `non_qualifiee`. Aucun paramètre recalibré ni gain de précision mesuré.

Ces tranches ne ferment pas les critères complets des lots 2, 3 ou 9.
La campagne [R22](../research/R22-2026-10-02/README.md) passe 467 cas Python et, séparément,
405 Core. Le pilote CSV et les tickets refusent hors SQLite. La qualification STT 151 ci-dessus
précède les autres tranches; ne pas l'ajouter à 467. Les autres connecteurs restent à livrer.

Qualification du lot 1 : **VÉRIFIÉ LOCALEMENT dans cette portée**. Preuves dans
[R21](../research/R21-2026-10-02/README.md) : 312 cas intégrés dont 17 Connecteurs;
cinq PostgreSQL désélectionnés, aucun fournisseur réel testé. Les qualifications suivantes sont détaillées dans R22.

## Suite dépendante : critères par lot

R23 prolonge le pilote du lot 3 : [préparation en une action](LOT-PREPARATEUR-CSV-BORNE.md)
qualifiée par 496 tests intégrés, dont 29 nouveaux cas. [Bilan R23](REPRISE-PREPARATEUR-BILAN-R23.md).
Le plafond est de vingt transactions; les seuils temporels sont coopératifs. Les lots 3 et 4
restent ouverts pour PDF/OCR, classement massif, isolation et évaluation mémoire.
La première tranche du lot 7 réutilise désormais la dictée Core Talk existante avec un fournisseur
de clip local optionnel : [bilan R24](REPRISE-DICTEE-BILAN-R24.md), 481 cas ciblés ROOT.
Validation et annulation sont distinctes jusqu'au fournisseur; les essais ne qualifient pas
un moteur ASR réel, l'accent fr-CA, TTS ou la réception vocale complète.

R25 qualifie ensuite le store documentaire PostgreSQL/pgvector déjà existant et ses outils
mémoire : [82 cas ciblés](LOT-QUALIFICATION-MEMOIRE-PG.md), aucun skip, embeddings simulés et
PGDATA éphémère en mémoire. Cette qualification prépare le lot 4; elle ne qualifie ni le
backend du pilote CSV, ni l'ingestion documentaire, ni la durabilité VPS. La dictée R24
est qualifiée localement sur une surface Core distincte. La tranche mémoire suivante relie
des procédures UTF-8 autorisées au store existant : admission, versions, citations vérifiables,
quotas et effacement transactionnel dans son interface privée. Cette tranche R26 est
qualifiée localement : son backend corrigé passe 103 cas PostgreSQL/mémoire ciblés,
sans échec ni skip et avec 1 096 sources stables. Sa console privée passe ensuite
85 cas ROOT avec 1 099 sources surveillées stables, dont huit nouveaux cas du
parcours documentaire incluant PostgreSQL réel. Les deux sélections sont disjointes; aucune campagne
de cette tranche n'évalue la qualité d'un modèle ou une assimilation massive.
Voir le [lot R26](LOT-INGESTION-PROCEDURES-M3.md) et son
[archive sourcée](../research/R26-2026-10-02/README.md).

Le préalable suivant du lot 5 établit une référence exacte entre estimation et
devis, sans rapprochement par dernier identifiant. La durée n'est transmissible
que si sa sémantique est déclarée explicitement. Cette tranche R27 est
[qualifiée localement](LOT-PROVENANCE-ESTIMATION-TEMPS.md) : 2 184 cas métier
passent, puis une garde CI sautée localement passe séparément, soit 2 185 cas
uniques couverts. Les instruments de mutation récursifs restent hors de cette
preuve; elle ne constitue pas une calibration ni un gain mesuré.

R28 livre ensuite le [pilote PDF natif et sa console privée](LOT-FUSION-PDF-NATIF.md) :
145 cas ROOT intégrés, aucun échec ou skip, 1 112 sources stables. Source et
extraits chiffrés, parseur isolé et consultation explicite; OCR, documents mixtes
et ingestion massive restent ouverts. R30 qualifie la couche pure de
[cohortes temporelles](LOT-COHORTES-TEMPS.md) : 14 cas ROOT et archive
[R30](../research/R30-2026-10-02/README.md). Les calculs résistent au contexte
Decimal ambiant; aucun barème n’est activé et aucun gain terrain n’est mesuré.
La géométrie synthétique et l’évaluation de recherche mémoire progressent
séparément, sans promotion des critères globaux des lots 4 à 6.

| Ordre | Lot | Critère de sortie qui autorise la suite |
|---|---|---|
| 2 | Registre connecteurs et secrets référencés | Scope/domaine/rôle, secret référencé, probe sans fuite, quotas, lecture seule et dry-run réels; aucun write implicite |
| 3 | Ingestion comptable pilote puis multi-format | CSV/PDF sourcés, lot durable, doublons/versionnage, panne/reprise, contrôles extraction, isolation entreprise et recherche par source |
| 4 | Fusion opérationnelle et mémoire premium | Corpus autorisé représentatif; états par domaine, questions de référence, rappel/precision/sources/latence/coût et effacement prouvés |
| 5 | Calibration M3 depuis M4/M6/M5 | Temps/quantités validés, unités/segments, train/évaluation temporelle distincts, version/rollback et gains mesurés sans regression |
| 6 | Vision/géospatial de mesure | Mesures terrain indépendantes, échelle/CRS/date/droits, erreur/intervalle/refus par service; pas de précision déduite de la résolution photo |
| 7 | Sessions audio départementales | Identité/dossier communs, STT/TTS fr-CA, interruption, escalade, latence/coût, repli texte et permissions conservées |
| 8 | Avatar 3D / option ACE | Rendu temps réel synchronisé, actifs/voix/poids licenciés, profil GPU et coût qualifiés; sans GPU, parcours métier disponible |
| 9 | Autonomie métier approfondie | Parcours réception→CRM→estimation→terrain/matériaux→finance→marketing→analytics→stratégie→mémoire, budgets, reprise et refus prouvés |
| 10 | Installation, exploitation et livraison | VPS neuf, sauvegarde/restauration, migrations, charge, sécurité et appareils réels; CI distante du changement avant publication autorisée |

Chaque lot produit son propre design concret, interfaces, tests, préimages, décision de brique et
rapport de résultats. Les lots 2–10 sont une feuille de route avec critères, pas des cases livrées.


## Point de reprise M5 — étape 20, 4 octobre 2026

La [saisie fournisseur depuis Fusion](../grs/compta/M5-AP-SAISIE-RAPPORT-2026-10-04.md)
prolonge les lots 3/9 : second POST humain, N3 canonique, revalidation, append
unique et rejeu historique, provenance `0024`. ROOT r124 qualifie 637 cas ciblés
sur 18 fichiers complets, sans échec/erreur/skip ; Ruff vert sur 12 fichiers,
1 236 sources inchangées. Reçus dans le rapport; CI de l'étape à suivre sur son propre commit. Aucun paiement, ledger final ou engagement externe.
M5 global reste PARTIEL. Suite utile : corpus de factures fournisseurs réelles
autorisées, mesure des refus/mappings/citations et politique de rétention ;
OCR/scans, sans PO, pont PostgreSQL, mobile et connecteurs exigent leurs propres
tranches. Cette qualification ne clôt aucun des dix lots d'ambition.


## Point de reprise M5 — tranche 21, 4 octobre 2026

La [consultation durable AP](../grs/compta/M5-AP-CONSULTATION-RAPPORT-2026-10-04.md)
est implémentée sur le GET existant : quatre champs de référence/état M5,
reconnexion et corrections, sans nouvelle écriture ni taux recalculé. Liaison
0024 et projecteur M5 réutilisés ; corruption 503, autorité financière vivante
et préconditions PDF conservées. Le rejeu Unicode de la tranche 20 respecte
désormais la sérialisation historique du hash de commande. ROOT r127 rouge et
r128 imports Ruff et r129 (657P/2F de fixtures) restent conservés. ROOT r130 :
668/668 sur 21 fichiers complets, 104,600 s JUnit, sans échec/erreur/skip ;
Ruff vert sur 16 fichiers et 1 240 sources inchangées. Pas de promotion globale
de M5, paiement ou ledger final.
