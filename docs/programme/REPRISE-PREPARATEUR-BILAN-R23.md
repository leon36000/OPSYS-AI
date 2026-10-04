# R23 — préparation CSV durable en une action

Un administrateur peut désormais préparer un lot financier depuis **Préparer le lot**, sans
répéter manuellement chaque tranche. Le serveur réutilise le parseur M5 et les transactions
du pilote R22; aucun nouveau schéma, service, paquet ou modèle n'est ajouté. Les sources restent
chiffrées et les résultats sont des propositions de rapprochement, sans écriture comptable finale.

## Comportement livré

Deux POST privés, API et formulaire HTML, enchaînent au plus vingt transactions de cent lignes.
Identité active, CSRF, révision concurrente, quota et snapshot M5 sont revérifiés. Les commandes
ne reçoivent ni budget ni plafond du navigateur. Le résumé ne contient que progression, statut,
révision, compteurs et motif d'arrêt; aucune cellule, somme, clé, identité de compte ou source.

Les seuils monotones de deux secondes par tranche et huit secondes au total sont coopératifs,
contrôlés entre transactions. Une transaction ou une attente de verrou peut dépasser un seuil.
La déconnexion observée ou l'annulation demande l'arrêt puis attend la transaction engagée.
La route garde son worker sous contrôle; aucun job autonome ne continue en arrière-plan.

Une panne n'annule pas les tranches déjà validées. Le GET privé fournit la révision actuelle pour
reprendre le même lot. Aucun retry ni rattrapage de révision ne contourne un conflit. Une révocation
refuse le résumé; un snapshot obsolète masque les propositions; un verrou SQLite reconnu produit
un refus 503 borné. L'interface distingue achèvement, refus, obsolescence et arrêt incomplet.

Surfaces : src/opsys/fusion_csv.py, src/opsys/console/fusion_ui.py et tests/test_fusion_preparateur.py.
[Contrat](LOT-PREPARATEUR-CSV-BORNE.md), [guide](../architecture/FUSION-CSV.md).

## Qualification ROOT

Campagne du **2 octobre 2026, 04:32:05 au 04:33:40 UTC** : **496 tests**, zéro échec, erreur ou
skip; durée JUnit 93,064 s. Les 1 093 empreintes sélectionnées sont identiques avant/après.
La sélection reprend R22 et ajoute les 29 nouveaux cas du préparateur : HTTP API/HTML, refus
d'entrée, concurrence à même révision, reprise après commit, snapshot changé entre tranches et
avant réponse, révocation, clé/quota, plafond, budget, arrêt et absence de doublon de provenance.
Ruff sur les trois surfaces et git diff --check passent sur les mêmes sources gelées.

Le cas de 2 000 lignes traite vingt tranches réelles avec une horloge injectée : il qualifie le
plafond de travail, pas un débit ni une durée de production. Les essais de déconnexion/annulation
contrôlent les événements ASGI et le worker; ils ne reproduisent pas une panne réseau de navigateur.
PostgreSQL est explicitement exclu et refusé par le pilote. Aucun appel LLM, service bancaire ou
action financière réelle n'est exercé. Les 405 tests Core de R22 ne sont pas relancés par R23.

Les [preuves R23](../research/R23-2026-10-02/README.md) conservent préimages, sources finales,
revues, commandes, XML et reçus. La première campagne ROOT a détecté un import de helper
incompatible avec le mode importlib du dépôt. Le correctif emploie le namespace tests; l'ordre
des imports a ensuite été corrigé. Ces rouges restent conservés. Les assertions n'ont pas été
affaiblies pour résoudre la collecte. Les 107 tests ciblés de l'auteur et les répétitions ne
s'ajoutent pas aux 496 tests de la campagne intégrée.

## Suite et limites

L'import multi-format, la purge gouvernée, la classification massive et le rappel longitudinal
M10 restent ouverts. Ce lot ne clôture ni M5 CFO IA ni M10 mémoire premium. Les audits historiques
de paie et de calibration ont été actualisés pour distinguer les brouillons bruts et traces déjà
présents des calculs de retenues et de l'apprentissage encore à construire.

La recherche vocale privilégie le Core Talk existant et ses contrats de plugin. Un adaptateur
local par clip requiert une distinction explicite entre terminer et annuler; la fermeture actuelle
ne suffit pas. Le futur lot devra prouver qu'aucun clip annulé n'est envoyé, sans présenter un
protocole local mocké comme un moteur ASR, une qualité fr-CA ou un avatar déjà opérationnel.

Le [plan complet](REPRISE-PLAN-2026-10-02.md) conserve les critères des dix lots. Aucun commit,
push, merge, déploiement ou action publique/financière réelle n'a été effectué.
