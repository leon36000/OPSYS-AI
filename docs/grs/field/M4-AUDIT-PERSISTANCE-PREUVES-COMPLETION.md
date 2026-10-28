# M4 — conserver les preuves des futures complétions

## Objectif et pourquoi
Fermer le constat CRM-12 : les photos après, notes et signature exigées à la complétion sont validées puis perdues par le serveur. Conserver leurs références et déclarations dans l’écriture propriétaire de M4 permet une consultation ultérieure du dossier, sans inventer de rattachement historique.

## État actuel avant code
Source `249ded0e301380c2b7f77777960ddcee7f9ad9a2`. `outils.completer_intervention` valide `preuves_completion` et les références CAS, puis appelle `outbox.completer_intervention` sans ce dossier. Le WCT conserve le champ optionnel **distinct** `photos`, pas `photos_apres`. La vue CRM-12 nouvellement qualifiée reste limitée aux photos WCT.

## Architecture minimale
Conserver un bloc privé optionnel dans la **partie transition du maillon composite unique** de complétion. Il contient version du contrat, `signature_requise` et une copie bornée des quatre champs de preuve. Son hash est inclus dans le `hash_maillon` opaque du WCT; son contenu ne figure **pas** dans le WCT ni dans les événements diffusés.

Réutiliser `preuves.valider_preuves_completion`, le registre chaîné, l’unique `ajouter` de l’outbox, le dépôt CAS et la transaction `executer_atomique`. Aucun second registre, outil, rôle, migration ou binaire dupliqué. Les anciens appels purs qui omettent les deux nouveaux arguments gardent exactement leurs anciens maillons et hashes; absence et bloc nul restent distincts.

## Fichiers, routes, données et workflow
- `departments/m04-field-ops/src/m4_field_ops/preuves.py` : snapshot fermé, bornes avant copie, validation du bloc archivé.
- `.../outbox.py` : option de conservation, hash couvrant le bloc, invariants refusant toute présence invalide ou sur une confirmation sans WCT.
- `.../outils.py` : transmettre le dossier et le booléen déjà validés; publication de `maillon['wct']` inchangée.
- Nouveau test dédié, plus les tests natifs preuves/fichiers/outbox/événements concernés.
Aucune route ajoutée dans cette tranche propriétaire. Le futur raccordement CRM utilisera ce bloc explicitement; il ne remplacera pas les références historiques absentes.

## Intégrations et analyse de compatibilité
Revue statique indépendante : les lecteurs outbox/publication extraient uniquement `wct`; calibration, revue et digest projettent explicitement leurs champs. Aucun contrôle runtime examiné n’exige exactement cinq champs de partie transition. Le recalcul d’invariants exclut seulement WCT/ligne/précédent : le bloc privé sera couvert par construction. Garder `CHAMPS_WCT` et le schéma événementiel fermés et inchangés.

## Permissions et risques
Aucune autorité ou permission nouvelle. Les contrôles existants d’appareil, rôle, affectation, contrat et CAS précèdent toujours la complétion. Pas d’export des notes/signatures aux autres départements. Une signature optionnelle déclarée quand elle n’est pas requise conserve sa sémantique actuelle; elle n’est pas présentée comme une signature CAS vérifiée.
Bornes nouvelles nécessaires à la persistance : copie de types fermés, nombre de photos et taille des chaînes bornés avant copie, puis plafond de 64 Kio de représentation canonique du bloc. Un refus ne doit écrire ni complétion ni événement. Le snapshot doit être privé avant le hash; les appels de registre ne doivent pas pouvoir modifier la liste appelante et changer le contenu archivé. Aucun bloc ajouté aux confirmations/revues ultérieures.

## Tests attendus
Rouge démontrant l’absence de preuve durable avec le vrai outil M4 et un vrai dépôt CAS fictif. Puis conservation/reconnexion, une seule écriture composite, hash lié au bloc, événements sans preuves privées, rollback de publication, formes et bornes refusées avant écriture, copie isolée, invariants stricts (bool vs version entière, bloc nul, confirmation sans WCT), compatibilité des anciens maillons et absence d’archive rétroactive. Cas de parcours outil natif, sans prétendre livrer l’application mobile.

## Gates Nathan, statut et prochaines étapes
**AUDIT TERMINÉ, IMPLÉMENTATION NON COMMENCÉE À LA CRÉATION DU DOCUMENT.** Aucun gate supplémentaire pour le correctif réversible et les données fictives. Politiques, rétention et accès aux données réelles ne sont pas qualifiés par cette QA.
Préflight privé M10 `m4-completion-proof-m10-preflight-v1` refusé : le chemin de documentation sous un répertoire nommé `crm` est interdit par la garde mémoire de développement. Refus historique conservé, garde inchangée. Nouveau preflight `v2` avec uniquement les sources permises : rc0; le document CRM reste lu séparément comme source Git versionnée, sans ingestion ni droits élargis. La base privée vide ne remplace pas la mémoire projet.
Après preuves et qualification : doc de contrat, matrice M4 concernée, raccordement de lecture CRM des nouvelles preuves, CI/publication normales selon le checkpoint. La bibliothèque documentaire et OPSYS restent PARTIAL.

## Résultat après audit
Le correctif propriétaire est implémenté, avec copie dans l’outil avant CAS et dans l’outbox avant hash/registre. `m4-completion-proof-v4` : **392 PASS / 23,45 s**, dont 15 ciblés; lint et vérificateur natif 306/177. L’état initial, les rouges et le refus preflight v1 restent historiques. Voir le [contrat local](M4-PREUVES-COMPLETION-DURABLES.md). Raccordement de lecture CRM, CI de publication et produit complet non qualifiés par cette tranche.
