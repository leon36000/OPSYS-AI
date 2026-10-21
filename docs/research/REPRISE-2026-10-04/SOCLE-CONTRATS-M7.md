# Socle Python : correction des contrats et des mutations M7

Le [diagnostic natif suivant](PDF-RUNNER-UBUNTU.md) décrit le refus de réseau
isolé du runner sur `0c265cc1`. Les qualifications locales ci-dessous sont
conservées; ce refus empêche encore la suite complète du socle de démarrer.

## État natif avant ce correctif

La PR #623, head `b005c4e6240da73651b84076451c7cadf64ab678`, a terminé ses workflows
Core, E2E Core, installateur et audit général des dépendances avec succès.
La CI générale échoue dans le seul socle : **79 échecs, 3 684 réussites,
17 exclusions**, en 40 min 56 s (job `111344154623`, run `37171058345`).
Les dix jobs départementaux et les neuf jobs lourds M3 réussissent : 38 cas M3
répartis exactement une fois. Ces résultats sont ceux de la CI de PR associée
à ce head; les jobs utilisent le merge de PR, pas un checkout local présumé.

L’installateur natif Linux (`111345369247`, run `37171058338`) exerce le vrai
Core et Docker, la migration de l’ancien état, la supervision du moteur,
la relance idempotente, l’export/restauration, le service utilisateur systemd
et la désinstallation conservant les données. Les jobs hébergés Windows et
macOS réussissent aussi. Les parcours réels Docker Desktop Windows/macOS sont
opt-in et exclus de ce run : aucun succès de ces parcours n’est déduit.

## Correctifs

1. **Isolation PDF.** 57 échecs appartiennent aux familles PDF/Fusion AP. Le
   manifeste exact du runner Ubuntu ne liste pas `bubblewrap`, et le workflow
   ne l’installait pas. Le job installe désormais cette dépendance OS et exécute
   un prévol avec les vraies options/montages de `_commande_isolee`, environnement
   vide et délai de dix secondes. Seul le programme du worker est remplacé par
   une instruction inoffensive pour ce prévol. Le parseur et les tests de
   confinement réseau, fichiers et limites restent inchangés. Aucun fallback,
   exclusion, sysctl ou désactivation AppArmor. La compatibilité du nouveau
   runner reste à prouver par la prochaine CI; la sonde locale ne la présume pas.
2. **Contrats des fixtures.** Les lectures MCP fournissent l’identité et non
   une demi-enveloppe d’idempotence; les mutations gardent leurs trois champs.
   Les URL attendues passent par `/mcp/v1`. Les six capacités de calibration
   admin sont épinglées explicitement et documentées (122 outils admin,
   213 exposés). La cascade marge/temps écrit une estimation M3 avec trace de
   calibration qualifiée et lie son hash exact au devis, avant son acceptation.
   Les montants, durées, autorisations et preuves aval demeurent vérifiés.
3. **Contrats M10.** Les doubles acceptent et vérifient le profil d’embedding;
   le wrapper PostgreSQL le transmet au store réel. Le cas sans provider vérifie
   explicitement le mode plein texte, ses filtres d’autorité et son avertissement.
   Le cas de handshake local indisponible conserve ses citations, scopes et
   absence de POST. La suite séparée vérifie aussi le handshake local positif.
   Ces corrections ne remplacent pas les tests PostgreSQL par des doubles.
4. **Portée avant restitution.** Les outils cibles refusent un rôle d’appareil
   non autorisé avant la demande de ticket. Un refus frais est enregistré et
   rejoué. Un succès déjà en cache n’est jamais restitué ni écrasé; les conflits
   de clé ne divulguent pas l’outil ou les arguments antérieurs. Les contrôles
   console et agent restent distincts. Trois régressions vérifient l’absence
   de fuite et la conservation intégrale du reçu antérieur.
5. **Écritures M7 réellement classées.** Le consentement de référence, l’export
   manuel de réponse et l’import manuel d’avis sont T1/N2. Les deux premiers
   avaient hérité de T0/N0; le troisième était T0/N2 et apparaissait encore
   comme lecture dans MCP. L’appel MCP réel du consentement sans clé avait
   créé une preuve avant correction. Désormais il est refusé sans changement
   SQL; avec clé, deux appels produisent un seul maillon et un seul reçu.
   Les trois annotations MCP déclarent l’écriture. Aucune publication ni
   validation humaine propriétaire n’est contournée.

## Qualification ROOT

- `qa-r60` : **228 réussis, aucun ignoré**, sept fichiers entiers permissions,
  MCP, idempotence, approbations et liaison de cibles. Ruff/actionlint réussis.
- `qa-r63` : **197 réussis, aucun ignoré**, dix fichiers entiers contrats,
  cascade M3/M5/M8/M10, routage, autorité mémoire, handshake et métier M7.
  Ruff/actionlint réussis. Le JUnit fournit explicitement le chemin du fichier
  pour les cas regroupés en classes : attribution exacte et unicité contrôlées.
- `qa-r64` : **8 réussis, aucun ignoré**, fichier entier de console métier et
  parcours privés M7, sans modification de son interface. Ruff/actionlint réussis.
- `qa-r62` : sonde native PDF locale réussie, compilation des deux fixtures
  PostgreSQL réussie (syntaxe seulement, aucune exécution PostgreSQL locale);
  Gitleaks des 17 fichiers modifiés sans alerte brute.

`qa-r65` analyse aussi les preuves extraites : 99 alertes brutes, toutes
classifiées par lecture JSON comme empreintes SHA256 de sources dans les
champs `source_before`/`source_after` ou `freeze.json`. Le rapport expurgé,
le reçu rouge et la classification liée à son hash restent dans la capsule r2.
Aucune règle ni baseline changée; ce scan brut n’est pas déclaré sans alerte.
La capsule initiale r1 reste conservée séparément.

Les campagnes rouges `qa-r52`, `qa-r53`, `qa-r54`, `qa-r56` et `qa-r59`
sont conservées. `qa-r61` exécutait les tests, mais son reçu est non qualifié :
le parseur JUnit ne reconnaissait pas le module lorsqu’une classe suivait son
nom. `qa-r63` reprend exactement les dix fichiers avec métadonnées de chemin,
sans supprimer de test ni assouplir le contrôle d’attribution. Les campagnes
figent les sources et contrôlent ressources/processus/OOM. Leurs comptes ne
constituent pas une couverture globale du dépôt.

## Suite et limites

La nouvelle CI doit exercer le prévol Ubuntu, les tests PostgreSQL réels et
l’intégralité du socle. Les succès précédents ne sont pas transférés au nouveau
commit par déduction. Le gate mobile reste rouge sur l’audit npm : 56 alertes,
dont 46 high; installation, typecheck et Jest n’ont pas été exécutés dans ce job.
Des candidats de correctifs source existent dans [braces #72](https://github.com/micromatch/braces/pull/72)
et [forge #1152](https://github.com/digitalbazaar/forge/pull/1152), mais aucune
publication stable corrigée compatible n’est qualifiée ici. Ces candidats
exigent leurs suites amont, tests adversariaux et intégration Expo/Metro; renommer
une version pour faire disparaître une alerte ne prouverait pas sa sécurité.
Le gate et son seuil restent actifs, sans mise à jour forcée.

La prochaine tranche d’assimilation M10 doit ajouter un manifeste durable de
lots bornés au PostgreSQL propriétaire existant : admission de source et état
d’emplacement atomiques, reprise après crash, révocation vivante par fichier,
effacement via les deux chemins d’oubli. Les corps ne seront pas copiés dans
un second canon. Un lot de cinq procédures ne sera pas présenté comme ingestion
massive ni comme apprentissage validé. Le plan détaillé de cette prochaine
tranche et la recherche mobile sont conservés dans la capsule; ils ne sont
pas déclarés implémentés. OPSYS-AI reste **PARTIEL**, PR brouillon, sans fusion.

[Archive vérifiable](preuves/SOCLE-CONTRATS-M7-r2.tar.xz) et
[inventaire SHA256](preuves/SOCLE-CONTRATS-M7-r2.json).
