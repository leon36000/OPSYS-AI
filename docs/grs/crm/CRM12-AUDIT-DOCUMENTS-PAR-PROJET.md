# CRM-12 — audit des photos et documents par projet

## Objectif et pourquoi
La secrétaire doit retrouver photos et PDF depuis le dossier client/projet, sans chercher dans plusieurs départements. Première tranche : consultation admin du devis accepté exact et des photos déclarées dans son événement de fin de travaux. Le dépôt libre, les preuves de complétion et la bibliothèque documentaire complète restent à livrer.

## État actuel vérifié avant code
Audit sur `10a4af68c25c14a4d667e433b6de41251b469660` (28 octobre 2026 UTC).
- `console/crm_ui.py` : carte Photos et fichiers partielle, sans rattachement. M3 fournit déjà les documents HTML/PDF du devis exact, avec permission et lecture propriétaire.
- `console/preparation_chantier.py:lire` : ancre M2 → devis M3 accepté → publication et réception M4 → inscription unique du chantier; bornes et chaîne vérifiées. À réutiliser.
- `m4_field_ops.outils:completer_intervention` valide `preuves_completion.photos_apres`, puis appelle l’outbox **sans conserver ce dossier**. Impossible de reconstruire ses photos, notes et signature historiques. Constat également identifié par revue statique indépendante; aucune preuve rétroactive inventée.
- Le champ optionnel **distinct** `photos` du WCT est conservé par `m4_field_ops.outbox.completer_intervention`. C’est une liste de références déclarées, pas une preuve de dépôt ou de validité du binaire.
- `opsys.fichiers.lire_blob_verifie` lit le stockage CAS natif, valide blocs, longueur, SHA-256 et signature JPEG/PNG (10 Mio). Il ne contrôle ni utilisateur ni chantier : un hash n’est pas une permission.
- M10 `documents_affaire` est un pilote de texte UTF-8, avec autorité admin **appareil**, SQLite et versions; les procédures ingérées sont également textuelles. Aucune bibliothèque PDF/photos CRM fournie par ces surfaces. Ne pas simuler une identité appareil ni élargir ces droits.

## Architecture minimale et fichiers
Réutiliser M2/M3/M4, le lecteur CAS, les projections et routes PDF existantes. Aucun nouveau paquet, schéma, service, rôle ou outil d’agent. Ajouter `src/opsys/console/documents_chantier.py`, le branchement CRM et `tests/test_console_documents_chantier.py`.

## Routes et données proposées
- GET `/crm/lead/{lead_id}/soumissions/{devis_id}/fichiers` : sources M3 et photos WCT exactes, statut courant M4 distinct de l’existence des photos.
- GET de photo sous ce même triplet, uniquement si sa référence est réellement portée par le WCT canonique; jamais un accès CAS global par hash.
- Conserver les liens natifs HTML/PDF M3; ne pas présenter le PDF recalculé comme une pièce reçue ou un fichier original signé.
Aucune adresse, GPS, signature, prix ou note libre ne doit être recopié dans la galerie. Métadonnées minimales : référence du WCT/maillon, ordre déclaré, statut et heure de consultation serveur. Un projet sans photos reste explicitement vide.

## Workflows et intégrations
Lecture admin → identité SQL/session vivante → bornes avant décodage → ancre propriétaire M2/M3/M4 → chaîne et invariants outbox → WCT unique et égal à la publication native → références de ce WCT → lecture d’un seul binaire vérifié par demande. Relecture des sources et de l’autorité après rendu avant réponse. Le constat sur les preuves non conservées impose ensuite une tranche M4 atomique dédiée, sans rattachement historique conjecturé.

## Permissions et risques
Admin courant uniquement; aucune capacité nouvelle pour employee/seller/system_agent, aucun changement DEVICE. Réponse privée sans cache, CSP/nosniff, sorties bornées, paramètres fermés. Refuser projet étranger, WCT contradictoire/dupliqué, source modifiée/corrompue, listes excessives et binaire absent/incomplet/corrompu. Les références externes ne sont jamais suivies. Aucun usage marketing ni élévation de statut du chantier.

## Tests et critères de sortie de la tranche
Tests HTTP avec M1→M2→M3→M4 natifs, fixture d’état terrain explicitement fictive, outbox et stockage CAS natifs. Vérifier consultation sans DML, absence de données sensibles, PDF M3 déjà disponible, photo réellement servie, projet étranger/hash orphelin refusés, SQL rôle/session révoqués avant et après rendu, corruption/quotas refusés avant sortie. Épingler Source et preuves; aucun parcours appareil complet revendiqué par une fixture d’état terrain. CI de la tête publiée encore en cours, à réconcilier séparément avant nouvelle publication.

## Gates Nathan, statut et prochaines étapes
**PARTIAL, audit terminé; implémentation et tests non encore réalisés à la création de cet audit.** Préflight M10 natif privé `crm12-m10-preflight-v1` rc0, sources versionnées épinglées; cette base vide de développement ne prouve pas l’absence de mémoire projet.
Aucun gate humain nécessaire pour cette lecture locale fictive et réversible. Les engagements réels, données personnelles de production et politiques de collecte restent hors de cette QA. Ensuite : preuves de complétion persistées au propriétaire M4, dépôt/rattachement PDF/photos par projet, cycle versions/retrait/rétention, UI de bibliothèque complète et mobile en dernière phase. Le produit global reste PARTIAL.

## Résultat de la première tranche, après l’audit
La consultation privée est implémentée dans `documents_chantier.py`, avec les limites ci-dessus. `crm12-v3` : **114 tests passés en 37,13 s**, dont 25 sur la nouvelle surface, lint des quatre fichiers de code et vérificateur natif **306 outils / 177 portées déclarées**. Le premier lot de 17 tests n’est pas additionné. Revue statique indépendante : confusion Decimal/texte et NaN de la comparaison initiale reproduite par deux tests SQL, puis corrigée avec le codec natif typé; requêtes libres masquées également dans les journaux. Publication/CI de cette tranche non encore qualifiées à cet ajout. Voir [contrat de livraison locale](CRM12-DOCUMENTS-CHANTIER.md). Le défaut de persistance des preuves de complétion reste ouvert.
