# M5 — Parcours de paie préparatoire composé, versionné, révisable et exportable au CPA

Statut : **PREPARATOIRE — NON_QUALIFIEE_POUR_PAIE**. Aucun salaire n'est versé, aucune remise n'est faite, aucun
bulletin, T4, RL-1 ou RE n'est émis, rien n'est envoyé à l'extérieur, aucune écriture n'est faite au grand livre, aux
factures, aux obligations, aux paiements ni dans M4. Une revue interne n'est ni une validation fiscale ni une attestation
professionnelle.

## Ce que le propriétaire fait (console privée `/finance/paie/dossiers`)

1. **Aperçu** — il déclare l'employé, la période de travail (14 jours), la date de paie, ses attestations, ses crédits
   (TD1, TP-1015.3), ses cumuls, ses pièces et ses paramètres employeur. Le serveur lit les heures M4 validées et le taux
   M5 par les ports existants, vérifie l'admission documentaire, appelle les moteurs réels et rend la matrice des postes
   avec ce qui manque. Rien n'est conservé.
2. **Conserver** — une version immuable et chiffrée est écrite si l'empreinte de l'aperçu vu est encore exacte.
3. **Corriger / période suivante** — formulaire pré-rempli ; une correction est une nouvelle version ; les cumuls de la
   période suivante sont simulés depuis la version courante de la période précédente et restent hypothétiques.
4. **Comparer, vérifier** — différences lisibles entre versions ; contrôle de reproductibilité et de dérive des sources.
5. **Revue interne** — liée à la version et au hash exacts de la version courante.
6. **Exporter** — JSON structuré et page HTML lisible, reproductibles octet par octet, pour le professionnel.

## Réutilisation (rien n'est reconstruit)

| Besoin | Propriétaire réutilisé |
|---|---|
| Heures régulières | port `lecteur_heures_m4` → `m4_lire_heures_regulieres_validees` (lecture seule, owner console) |
| Brut régulier | `preparer_brut_regulier` (taux M5 × minutes, centime demi supérieur) |
| Admission documentaire | `verifier_admission_serveur_preparatoire` (configuration serveur, génération Source, PDF épinglés) |
| RRQ, impôt QC, RQAP/AE, fédéral | `calculer_retenue_federale_qc_preparatoire` (recompose les trois façades publiques) |
| Lien WebRAS | `_LIENS_PAIE_OFFICIELS` repris tel quel dans l'export (aucun appel automatisé) |
| Stockage | `opsys.stockage.maillons` + `opsys.cles_chiffrement` (aucune migration, `schema.py` intact) |

Ajouts M5 : `dossier_paie_preparatoire.py` (contrat, composition, matrice), `cotisations_employeur_2026.py` (RRQ employeur,
FSS, CNESST, normes du travail, FDRCMO), `journal_dossiers_paie.py` (journal chiffré et chaîné), `service_dossier_paie.py`,
`export_paie_preparatoire.py`, `outils_paie_dossier.py` (huit outils) ; console `src/opsys/console/paie_dossier_ui.py`.
Les huit fichiers dont l'empreinte est épinglée par l'admission n'ont pas été modifiés.

## Domaine supporté (tout le reste reste INCONNU ou HORS_COUVERTURE, jamais un défaut)

Québec, année 2026, paie bihebdomadaire à 26 périodes, salaire régulier fixe, emploi annuel continu, résident, assiettes
égales au brut, PM = 12, sans gratification, rétroactif, surtemps, rémunération variable, avantage imposable, transfert,
exemption, taux AE réduit, ni régime CCQ. Période 1 (paie jusqu'au 30 juin) ; périodes 2 à 26 (fenêtres janvier–juin et
juillet–décembre). Une année à 27 paies, une autre année ou un cas CCQ donne HORS_COUVERTURE avant tout calcul. Le régime
CCQ n'est jamais déduit du métier : `NON_CCQ_DECLARE` (avec pièce), `CCQ` ou `INCONNU`.

## Matrice des postes et totaux

| Poste | Source du calcul | Condition |
|---|---|---|
| RRQ employé, impôt QC, RQAP/AE employé, impôt fédéral | moteurs existants | domaine ci-dessus |
| RQAP employeur, AE employeur | moteur RQAP/AE existant | idem |
| RRQ employeur | égale à la retenue de l'employé (TP-1015.F 2026-01, p. 7 et partie 3.2 p. 40) | idem |
| FSS | D2 = W × S2 arrondi au cent (TP-1015.F partie 5, pp. 43-45) | secteur, masse salariale et base d'estimation déclarés |
| CNESST | (salaire assurable − excédent du maximum 103 000 $) × taux / 100 | taux de la Décision de classification déclaré, base annuelle |
| Normes du travail | 0,06 % jusqu'à 103 000 $ (TP-1015.G partie 7, p. 74) | assujettissement déclaré |
| FDRCMO | seuil strictement supérieur à 2 M$ (TP-1015.G partie 8, p. 75) | masse déclarée ; au-delà du seuil : inconnu |
| Autres retenues, autres coûts employeur | déclarés par le propriétaire avec pièce | `null` = inconnu |

- **Retenues totales, net préparatoire, DAS Revenu Québec, DAS ARC, DAS complète, coût employeur global** n'existent que si
  tous leurs postes sont couverts, la classification CCQ est `NON_CCQ_DECLARE` et aucune sortie de domaine n'est déclarée.
  Sinon `montant = null` et `manques` nomme le poste, le paramètre ou la classification manquants. Aucune somme partielle.
- Un net ne devient jamais négatif : retenues supérieures au brut → inconnu.
- Aucun taux employeur par défaut, aucune reconduction 2026 → 2027 : une date de paie hors 2026 rend tout inconnu.

## Versions, cumuls et durabilité

- Registre `m05-financecore/dossiers_paie_preparatoires` (append-only) ; enveloppe en clair = empreintes seulement ;
  contenu chiffré AES-256-GCM, une clé par dossier ; identifiant de dossier = HMAC (clé d'index du coffre).
- Intégrité vérifiée à chaque lecture (chaîne, MAC, déchiffrement, forme, projection) ; toute anomalie ferme la lecture.
- Idempotence : rejeu exact → même reçu ; même mutation et autre charge → refus ; CAS sur la version courante ; deux
  écritures concurrentes → une version, un refus. Un refus annule toute la transaction.
- Cumuls : `NUL_PERIODE_1`, `DECLARE_HISTORIQUE`, `CONFIRME_AUTORITE_HUMAINE`, `SIMULE_VERSION_PRECEDENTE`. Un cumul simulé
  est toujours recalculé par le serveur depuis la version courante de la période précédente et marqué hypothétique ; si
  cette période change, la dépendance est détectée (`CUMUL-SIMULE-PERIME`) et une nouvelle version explicite est requise.
- Une nouvelle source, un moteur modifié ou une correction d'heures M4 n'écrase jamais l'ancienne version
  (`CALCUL-NON-REPRODUCTIBLE`, `SOURCE-*-MODIFIEE`) : rebase explicite.

## Outils M5 (propriétaire-console seulement, aucun grant d'appareil ni d'agent)

`m5_apercu_dossier_paie`, `m5_conserver_version_dossier_paie`, `m5_rouvrir_dossier_paie`, `m5_revue_dossier_paie`,
`m5_exporter_dossier_paie`, `m5_lire_dossier_paie`, `m5_verifier_dossier_paie`, `m5_lire_export_dossier_paie`.
Les commandes ne rendent que des reçus sans montant. Les outils sont listés sur le serveur MCP du département (comme le
brut régulier) mais leur appel est refusé hors du propriétaire console : voir `docs/reprise/M5-PAIE-PARCOURS-2026-10-28/`.

## Limites assumées

Voir `docs/reprise/M5-PAIE-PARCOURS-2026-10-28/RAPPORT.md` (limites et critères non vérifiés). Ce parcours ne ferme ni M5.4,
ni FinanceCore, ni la paie complète.
