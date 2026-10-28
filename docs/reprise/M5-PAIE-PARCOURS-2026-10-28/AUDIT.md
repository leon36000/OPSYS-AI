# Audit ciblé (avant modification)

Base vérifiée : `git cat-file -t 3ab7692f…` = commit après `git fetch` (la base est sur `codex/restructuration-2026-09-30`,
**pas** sur `main`, qui est en retard de 478 fichiers). Branche de mission créée depuis cette base ; aucun checkout du
coordinateur n'a été utilisé.

## Ce qui existe déjà (réutilisé, non reconstruit)

- Brut régulier : `brut_regulier.calculer_brut_regulier`, `outils.preparer_brut_regulier` (taux M5 × minutes M4, centime demi supérieur).
- Port M4 : `Capacites._lecteur_heures_m4` → `m4_lire_heures_regulieres_validees`, exige console + owner + contexte M5.
- Admission : `admission_paie_preparatoire.verifier_admission_serveur_preparatoire` (config serveur, 8 fichiers Source épinglés, PDF épinglés).
- Moteurs : `cotisations_rrq_regulieres`, `impot_quebec_regulier`, `cotisations_rqap_ae_2026`, `paie_qc_preparatoire` (façade partielle), `impot_federal_qc_2026` (recompose les trois).
- Console : `paie_ui` (brut + WebRAS), `paie_admission_ui`, `obligations_privees` (modèle de journal chiffré).
- Le fédéral **n'est pas** absent : `retenue_impot_federal` est calculée ; seuls `revenu_net`, `das_complete` et `cout_employeur_global` restent `None` dans ce moteur.

## Lacunes prouvées (réellement comblées ici)

1. Aucun parcours humain composé : admission → composition → conservation → revue → export.
2. Aucun dossier ni cumul préparatoire durable, aucune version, correction, comparaison, rebase.
3. Postes employeur absents : RRQ employeur, FSS, CNESST, normes du travail, FDRCMO ; donc ni net, ni DAS, ni coût employeur justifiables.
4. Aucun export reproductible pour le professionnel.

## Contraintes découvertes (elles ont façonné la conception)

- Les huit fichiers `__init__.py, contrats.py, validation.py, cotisations_rrq_regulieres.py, cotisations_rqap_ae_2026.py,
  impot_quebec_regulier.py, paie_qc_preparatoire.py, impot_federal_qc_2026.py` sont liés par SHA à
  `admission_paie_preparatoire.v1.json` : **aucun n'a été modifié** (sinon l'admission refuserait). Les codes de refus du dossier vivent donc
  dans l'espace `REJ-DOSSIER-PAIE-*`, hors de `validation.py`.
- `metier.executer` ne donne le port M4 qu'à une liste fermée d'outils et ne connaît que les noms de `LECTURES`/`COMMANDES` : raccord minimal commit séparé.
- `idempotence.finaliser` stocke la réponse en clair : les commandes ne rendent que des reçus sans montant.
- `executer` n'annule la transaction que sur une exception métier (`ValueError/TypeError/KeyError`) : `DossierErreur` en hérite et porte son verdict en JSON.
- La console limite `_formulaire` à 20 champs : le formulaire de dossier (≈ 80 champs) lit lui-même un corps borné à 64 Kio.
- Gardes de conformité M5 : pas de clé `cause`, pas d'aléa système (`secrets`) ni d'énumération sans échappatoire dans le paquet → nonce AES-GCM dérivé (HMAC), énumérations privées ou `CHAMPS_*`.
- Les PDF d'admission ne sont pas dans le dépôt : en production l'admission refuse (diagnostic exact) tant qu'ils ne sont pas déposés ; les tests utilisent des PDF fictifs.
- Réseau du bac à sable : `www.revenuquebec.ca`, `canada.ca`, `cnesst.gouv.qc.ca` répondent 403 au tunnel : impossible de re-hacher les PDF épinglés ; les règles employeur ont été lues en texte officiel par un service de lecture tiers (Firecrawl).

## Défauts de produit trouvés par les tests (corrigés)

- `_fmt` quantifiait sous le contexte Decimal de l'appelant (InvalidOperation sous `prec=3`) ; l'addition DAS RQ + ARC se faisait hors contexte isolé (270,34 $ au lieu de 270,30 $ sous contexte hostile).
- Schéma d'outil `m5_conserver_version_dossier_paie` sans `horodatage` (injecté par la console) : appel refusé en intégration.
- Doublon possible d'un même employé et d'une même période sous deux références d'employeur : refusé (`DOSSIER-DOUBLON`).
