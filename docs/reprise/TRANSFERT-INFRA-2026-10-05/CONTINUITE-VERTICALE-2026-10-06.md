# Continuité OPSYS-AI — verticale suivante, 6 octobre 2026 Toronto

État : file reprise et raccords identifiés; scénario intégral non livré. Le commit d’intégration `44e388245253b6697391002415b2d0212b1e60cb` conserve dix départements, Core OpenClaw, mobile quatre profils/hors ligne, dashboard, avatars, mémoires métier/développement séparées. La qualification de reprise précède cette verticale.

| Jonction | Réutilisation à confronter | Critère de la prochaine qualification |
|---|---|---|
| M7 → M1 → M2 | `tests/e2e/test_formulaire_utm_bout_en_bout.py` : paquet exporté fictif, route HTTP signée, bus, attribution et readiness | Même lead/UTM et propriétaire; rejeu après qualification et réouverture sans second lead; incomplet/refus nommé |
| M2 → M3 | Même E2E : vendeur autorisé, readiness, barème fictif, photo bloquante; outils vendeur/liste qualifiés | Poursuivre le lead reçu, conserver les contrats v2 et l’identifiant; prix déterministe, revue/envoi humains distincts; vendeur concurrent refusé |
| M3 → M4/M6 | Préparation chantier et parcours employé des E2E mobile; commandes natives des départements | Adapter l’entrée au devis précédent, sans créer un autre lead synthétique; réservations/réceptions/pointage/complétion avec les mêmes devis/intervention/chantier/WCT |
| M4/M6 → M5 | `tests/test_cascade_marge_m5_m8_m10.py` et `tests/e2e/test_admin_appareil.py` | Coûts canoniques et statut de facture : brouillon reste provisoire; finalité après geste humain fictif par outil, aucun paiement réel |
| M5 → M8/M9/M10 | Cascades marge et mesure existantes; classification FINANCIAL et contexte gouverné | Même WCT et séquence de rentabilité, reçus par consommateur, montants sourcés; manque/ambiguïté nommés, absence de fuite financière, pas de décision M9 déduite |
| Core → intentions → remise/ACK M10 | Tests POSTFLIGHT/interop Python HTTP et diagnostic opérateur existants | Ticket/admission/provider actuels encore synthétiques : preuve métier réelle à composer; intention persistée avant effet, incertitude conservée au redémarrage, nouveaux effets bloqués; ACK ne vaut pas exactement-une-fois métier |
| Quatre profils + hors ligne | Harnais HTTP appareil et suites mobile de caches/outbox/propriété | Continuité d’identité et autorité jusqu’au rejeu; caches purgés au changement de personne/révocation, reprise sans perte ni double effet; appareil réel distinct du harnais |

Les identifiants doivent provenir des résultats canoniques successifs. Aucun rapprochement artificiel par remplacement d’ID ni événement de fin de chantier fabriqué pour prétendre un parcours complet. Les fixtures sont explicitement fictives et les effets externes restent fermés.

Ordre de sortie : (1) décrire les contrats de jonction à partir des APIs existantes; (2) composer un scénario durable unique avec assertions négatives et réouverture; (3) prouver SQLite puis PostgreSQL isolé disponible; (4) qualifier le Core réel et les quatre profils; (5) qualifier interfaces/appareils/fournisseurs séparément. Une dépendance manquante reste un blocage précis dans le registre.

Dépendances ouvertes conservées : rapprochement humain des intentions, PostgreSQL/restauration, budget UI, tooling privé/amont, données/calibration terrain, téléphonie et OCR réels, CFO/paie/fiscalité préparatoires sourcées, CMO/ROI, ingestion durable évaluée, avatar audiovisuel et dashboard configurables. Aucune de ces capacités n’est déclarée livrée par ce document. Aucun travail permanent en arrière-plan ni mémoire de conversations absentes annoncé.
