# Intégration de la mission visites CRM01-16

Version documentaire 1. Contrat de reprise pour la branche de mission ; ce document ne modifie aucun contrat partagé. Base : `3ab7692f041892ec2af0cab6f241a715edac2d50`. La PR est draft et ne constitue ni un déploiement ni une autorisation de fusion.

## Surfaces et effets

| Surface | Symboles ou routes | Effet et contraintes |
|---|---|---|
| M4 | `visites_chantier.py`, `visites_durables.py`, `visites_ecriture.py` | Prévisions et sessions identifiées, registre append-only, projections bornées, vérification des sources et transactions SQLite avec rejeu. Une ancre civile historique ne change pas lors d'un report. |
| Outils privés M4 | `m4_lire_visites_console`, `m4_prevoir_visite_console`, `m4_evenement_visite_console` | Lecture paginée, prévision, ouverture et fermeture ; identité admin console active, source et autorité revalidées. Refus métier enveloppé par `REJ-CONTRAT-INVALIDE` avec détail ; le rejeu utilise l'identité de mutation. |
| Interruption et reprise | `m4_signaler_report`, `m4_replanifier_visite_console` | Le report après commencement exige une session fermée et une source vérifiée ; il n'émet pas de WCT. La reprise réutilise les mécanismes de plan et d'approbation existants. |
| Console | `GET/POST /crm/visites`, `GET/POST /crm/visites/reprise` | Consultation et opérations privées ; CSRF, rôle et contrôles de source. La proposition choisit une équipe et une fenêtre ; l'affectation et la date civile suivent les étapes existantes. |
| Journal console | `journal_visites.py` | Liens vers les seules visites dont les références sont vérifiées ; le curseur associe les sources du journal, des visites et des compositions. Le contrat du journal M4 historique reste inchangé. |
| Temps | `outbox.py`, `pointage.py`, [carte des lecteurs](CRM01-16-CARTE-LECTEURS.md) | Les calculs certifiés additionnent les sessions distinctes ; certains anciens aperçus refusent les sources segmentées au lieu d'inventer une répartition. Aucun calcul de présence individuelle ou de paie. |

Les raccords aux fichiers communs sont isolés dans `333415ecd`, `b9290308b` et `5e8c8427d` : `crm_ui.py`, `metier.py` et `journal_equipes.py`. Ils doivent être revus et intégrés par le coordinateur avec leurs dépendances de branche, sans les traiter comme des changements autonomes à cherry-pick aveuglément. Aucun schéma commun, droit global ou fichier M5 n'est modifié ; aucune migration n'a été créée.

## Consommation et vérification

Le WCT existant est conservé en V1. Son total agrégé et son dernier identifiant pointé ne prouvent pas une présence individuelle ni un coût par équipe en cas de reprise avec une autre équipe. La [proposition de contrat M5 V2](CRM01-16-CONTRAT-TEMPS-M5.md) reste à négocier et à mettre en œuvre hors de cette branche ; la compatibilité métier du consommateur M5 n'est pas démontrée. Garder les faits anciens ambigus non attribués et refuser un total incomplet.

La commande isolée et la liste exacte des tests sont dans `preuves-visites-20261028/commande-regression-40.sh` ; `regression-40.log` et le JUnit correspondant ont terminé avec exit 0. `lint-56.log` documente Ruff sur les fichiers Python modifiés. Les preuves détaillées, les limites des environnements et les parcours HTTP/navigateur sont dans [le rapport de mission](RAPPORT-CRM01-16-VISITES.md). Vérifier à nouveau sur le résultat d'intégration, notamment les trois raccords communs et la consommation M5, avant toute décision de mise en service.
