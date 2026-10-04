# OPSYS-AI — entreprise autonome et apprenante

Source : [instruction de Nathan](INSTRUCTION-NATHAN-2026-10-02.md) et
[directives antérieures](DIRECTIVES-NATHAN.md). Décisions du chef de projet sous le mandat de
reprise. Ce document définit la cible; il ne certifie aucune nouvelle capacité opérationnelle.

## Résultat produit

Une PME dispose de départements qui exécutent leur métier avec ses données, ses politiques,
ses outils et sa mémoire. M1 reçoit, M2 suit les clients, M3 estime, M4 organise le terrain,
M5 protège et prépare les finances, M6 gère les matériaux, M7 développe la croissance,
M8 mesure, M9 propose les décisions et M10 conserve leurs sources et leurs apprentissages.
L'autonomie opère dans les permissions accordées; argent réel, déclarations, engagements et
actions publiques sensibles conservent les validations définies par Nathan.

## Architecture retenue et alternatives

Retenir le core et le socle métier actuels, avec événements transactionnels et adaptateurs
spécialisés. Un assistant unique chargé de tout aurait trop de contexte et trop de droits;
des départements sans contrats communs dupliqueraient les vérités. Les spécialistes existants
restent configurables par responsabilité, modèle, budget et autorisation. Le runtime doit
réserver les ressources avant génération, reprendre un travail interrompu et distinguer un
profil activé d'un travail effectivement exécuté.

L'installation VPS doit fonctionner sans les PC personnels de Nathan. Les services GPU lourds
(vision, STT/TTS, avatar) sont des ressources optionnelles, locales ou distantes explicitement
autorisées, derrière un adaptateur. L'interface textuelle et les workflows métier restent utilisables.

## Dashboard des outils et API

Créer un espace Connecteurs par département : capacité, fournisseur/adaptateur, configuration
requise, référence de secret, scopes, permission de sortie des données, coût, état observé,
dernier contrôle, limites et repli. Les valeurs de secrets et chaînes de connexion ne sont
jamais affichées. Distinguer présence de configuration, validation locale, authentification,
lecture distante prouvée et écriture autorisée. Un paramètre fourni ne prouve aucun appel réussi.

La première tranche R21 affiche les prérequis existants STT M1, SMS M1 et mémoire/embeddings, avec
leur état de présence seulement. Les choix de modèles sont déjà dans Modèles; les banques CSV
restent dans Finance. Les connecteurs comptables, vision métrique, géospatial de mesure et avatar
restent explicitement à construire. Le routage OSRM M4 ne mesure pas un bâtiment.

Les qualifications suivantes prolongent cet état : [R22](../programme/REPRISE-BILAN-2026-10-02.md)
ajoute la configuration STT persistante par références et le contrôle manuel sans audio;
[R23](../programme/REPRISE-PREPARATEUR-BILAN-R23.md) prépare le pilote CSV durable en une action.
[R25](../programme/LOT-QUALIFICATION-MEMOIRE-PG.md) vérifie le store mémoire existant sur
PostgreSQL/pgvector réel en tmpfs, avec embeddings fictifs. Ces tranches ne prouvent pas les
fournisseurs réels, l'ingestion massive ou une note d'assimilation générale.

## Interaction par avatar

Chaque département doit offrir une session texte/audio/vidéo attachée à la même identité,
aux mêmes outils et au même dossier. Pipeline : microphone → STT → intention et contexte
autorisé → outils métier → réponse contrôlée → TTS → animation faciale → avatar 3D navigateur.
Prévoir sous-titres, interruption, reprise textuelle, désactivation caméra/microphone et prise
en charge humaine. Le rendu 3D ne constitue pas une nouvelle autorité ni une source de chiffres.

Approche : étudier Pipecat/LiveKit et un rendu WebGL; Audio2Face/ACE constitue une option GPU.
Vérifier séparément licences du code, voix, avatars et poids ainsi que latence, coût et qualité
du français québécois. Aucune dépendance NVIDIA, clé NGC ou licence de modèle n'est installée
par cette décision. Ne pas inférer les émotions des clients à partir de leur visage ou de leur voix.

## Fusion opérationnelle : assimilation initiale et continue

Nom de travail produit : **Fusion opérationnelle**. À l'achat, un parcours guidé inventorie les
sources, importe des lots autorisés et construit une mémoire utile par département. Il reste
utilisable pendant l'intégration; l'avancement est mesuré sur le périmètre choisi par le client.

Pipeline cible : inventaire → fichiers protégés et empreintes → extraction par format →
classification et contrôle humain des ambiguïtés → rapprochement/dédoublonnage → source
canonique ou connaissance candidate → index lexical/vectoriel → évaluation → disponibilité.
Conserver fichier, version, page/ligne, auteur, droits, lot, erreurs et liens. Une facture extraite
reste candidate : importer des documents ne poste pas des écritures comptables finales.

Jobs durables : manifeste de lot, curseur, quotas, états par document, idempotence, reprise,
quarantaine, versions, annulation et effacement propagé. Limiter aussi taille décompressée,
formats, nombre de pages, concurrence, OCR, embeddings et tokens. Les documents et leurs
instructions intégrées sont des données non fiables, jamais des consignes à exécuter.

Pas de note de « connaissance de l'entreprise » inventée. Afficher séparément documents
inventoriés/traités/validés/en erreur, couverture des domaines et réussite aux questions
de contrôle. Un pourcentage d'import ne prouve pas rappel, vérité, qualité ni intégration.
Une couverture inconnue reste inconnue; un corpus choisi peut être intégralement importé
sans couvrir toutes les données de l'entreprise.

## Mémoire premium et apprentissage

Réutiliser M10, ses deux domaines isolés, sa provenance et ses règles de révision. Le stockage
transactionnel garde les vérités métier; les index servent la récupération. Évaluer rappel,
précision, fraîcheur, contradictions, sources, isolation, latence et coût sur des cas de chaque
département. La mémoire de projet conserve prompts/plans/tests; elle ne devient pas mémoire client.

L'apprentissage continu commence par acquisition de connaissances validées et calibration
déterministe. Le fine-tuning reste une option ultérieure pour extraction/classification,
avec licences, consentement, jeu de référence, budget et contrôle de régression.

Pour M3 : durée/équipe/service/quantités/accessibilité estimées → temps et matériaux validés M4/M6
→ comparaison liée au devis → proposition de paramètres par segment → évaluation sur chantiers
distincts → promotion versionnée → surveillance et retour arrière. Documenter minutes-équipe
contre heures-personnes, pause/déplacement, sous-traitance, météo et saison; exclure les observations
incomplètes. Aucune règle future ne change silencieusement parce qu'un chantier a été plus long.

## Précision photographique et géospatiale

La qualité des métadonnées photo et le géocodage ne constituent pas une mesure. Qualifier une
chaîne segmentation/géométrie/photogrammétrie ou données LiDAR/orthophoto avec unités, échelle,
système de coordonnées, date, provenance et droits. Photos insuffisantes → collecte additionnelle
ou mesure terrain. Street View peut aider au contexte; aucune dimension précise sans preuve.

Mesurer erreur absolue/relative, couverture de l'intervalle et taux de refus sur mesures terrain
indépendantes, par service et conditions. Définir le seuil d'acceptation par usage avant benchmark;
ne pas annoncer une précision exceptionnelle sans observations. Les prix restent déterministes.

## Critères communs de livraison

Pour chaque capacité : parcours métier, identité et permissions, données persistées, source,
rejeu/reprise, test négatif, interface admin/mobile applicable, trace, documentation et limites.
Tests simulés, tests locaux et intégrations réelles sont distingués. Aucun statut global 100 %
ni économie chiffrée sans mesure. Chaque lot choisit la brique utile après recherche GitHub,
GitLab et littérature pertinente; une recherche seule ne vaut pas adoption.
