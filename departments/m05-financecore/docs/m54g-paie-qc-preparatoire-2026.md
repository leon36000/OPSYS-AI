# M5.4.g — RQAP et assurance-emploi QC préparatoires, édition 2026

Ces fonctions ajoutent des calculs préparatoires isolés. Elles ne réalisent pas une paie : les règles et l’applicabilité individuelle restent non qualifiées, les preuves d’entrée sont déclaratives, et une personne compétente doit vérifier les paramètres et montants avant tout usage.

## Composition offerte et limites

`calculer_cotisations_rqap_ae_preparatoires` reçoit des assiettes séparées, les cumuls salarié/employeur avant la période et une référence/hash pour chacune. Il retourne quatre postes distincts. Il ne déduit jamais une assiette d’un brut M4, d’un chantier, d’une photo ou d’un taux horaire. `calculer_paie_qc_preparatoire` appelle les API publiques RRQ et R42, recopie le `CSA` réellement calculé par RRQ dans l’appel R42, puis appelle le calculateur RQAP/AE. Il ne touche ni au registre ni au catalogue des règles.

Le contrat étroit couvre une période régulière bihebdomadaire de 2026, juridiction QC, emploi continu et un seul employeur; toute date doit être ISO et chaque calcul reçoit le même année/date/province/fréquence/période. À la période 1, les quatre cumuls antérieurs doivent être zéro. Sont refusés : transfert de province, taux AE réduit, gratification/rétroactif, exemption spéciale, salaire non confirmé en argent pour le RQAP, indicateur non booléen, champ inconnu, cumul au-dessus du plafond, montant float/bool, montant texte non canonique ou preuve absente/mal formée. Les attestations et SHA ne sont pas authentifiés. Les statuts légaux d’assurance/assiette doivent être établis par l’autorité de paie.

Le paquet de la façade demeure `INCOMPLET`: il ne calcule pas l’impôt fédéral sur le revenu ni les autres obligations. Aucun `net`, DAS complète, coût employeur global, paiement, bulletin, remise ou déclaration n’est produit. CCQ, FSS, CNESST, vacances, fonds et règles de convention restent `UNKNOWN`; aucune classification construction n’est inférée.

Les champs `Q` et `Q1` de R42 désignent FTQ/Fondaction. RQAP ou AE ne doivent jamais y être placés. RRQ et R42 demeurent des composantes séparées et transmettent leurs propres statuts `NON_QUALIFIEE_POUR_PAIE`.

## Paramètres 2026 exécutés

Le module porte un snapshot JSON des valeurs, arrondis, bornes, édition, pages et empreintes de sources; chaque résultat contient ce snapshot et son SHA-256 canonique. Le label de version seul ne fait pas foi. Les contextes Decimal sont isolés du contexte de l’appelant (précision 50, `Emin=-999999`, `Emax=999999`, `clamp=0`, half-up et pièges désactivés). L’arrondi numérique est une convention de calcul reproductible, pas une garantie de précision des données terrain.

| Cotisation | Assiette et cumul distincts | Valeurs 2026 | Calcul préparatoire |
|---|---|---|---|
| RQAP salarié | Salaire admissible RQAP par période; cotisation RQAP salarié antérieure chez cet employeur | 0,430%; maximum assurable 103 000 $; plafond de cotisation 442,90 $ | `min(442,90 − cumul, 0,00430 × assiette)`; arrondi au cent selon TP-1015.F p.41. Un montant positif inférieur à un cent donne un cent. |
| RQAP employeur | Même salaire admissible RQAP; cotisation RQAP employeur antérieure | 0,602%; plafond 620,06 $ | `min(620,06 − cumul, 0,00602 × assiette)`; arrondi au cent TP-1015.F p.42, sans minimum spécial d’un cent. |
| AE salarié QC | Revenu assurable AE par période; prime AE salarié antérieure chez cet employeur | 1,30%; maximum assurable 68 900 $; plafond 895,70 $ | `min(895,70 − cumul, 0,0130 × assiette)`; arrondi au cent T4127 ch.7 p.31. |
| AE employeur QC | Revenu assurable AE par période; prime AE employeur antérieure chez cet employeur | 1,820%; plafond 1 253,98 $ | `min(1 253,98 − cumul, 0,01820 × assiette)`; arrondi au cent. Ne pas calculer comme 1,4 fois le montant salarié déjà arrondi. |

Le plafond annuel assurable est établi par le cumul documenté; le calculateur n’infère ni l’assiette ni le cumul à partir d’autres lignes. Si un cumul est au maximum avant la période, la cotisation correspondante est zéro. TP-1015.F p.42 indique exactement : « Lorsque la cotisation maximale de l’employée ou de l’employé au RQAP pour l’année est atteinte, la cotisation maximale de l’employeur au RQAP pour l’année est aussi atteinte. » Cette note impose le sens salarié → employeur; elle n’exige pas l’inverse. Les formules et arrondis distincts peuvent donc laisser le cumul salarié à un cent du plafond après que le cumul employeur a atteint le sien. Le RQAP requiert une confirmation d’assiette salaire en argent; les avantages en nature ne sont généralement pas salaire RQAP selon la TP-1015.F.

## Provenance officielle

- Revenu Québec, TP-1015.F (2026-01), pages 7, 41–42, SHA-256 `a65675dc6ad2bfc6c4fe2695d4914a57f381eccc9b8b1e1c581b7c9c8a18e72b`. Pages 41–42 prescrivent les calculs et arrondis RQAP salarié/employeur distincts.
- ARC, T4127, 122e édition (janvier 2026), ch.7 p.31 et tableau 8.7 p.34, SHA-256 `c715b8e6d33e0887119e0462b9a4cf8915370c56381932f1d7ba3a32385ddd8c`. La règle générale imprimée p.3 dit exactement : “When the employee’s or employer’s EI premium for the pay period has three or more digits after the decimal point, increase the second digit by one if the third digit is five or more, and drop the third digit.” Ainsi, le taux employeur 1,820% de la table est arrondi indépendamment selon la règle primaire; le montant employeur n’est jamais dérivé du montant salarié déjà arrondi.
- ARC, T4127, 123e édition (juillet 2026), ch.7, SHA-256 `69d86d952cb14c786fdcc0321ec293f66db1529276ef310217b3ade47db25671`. La formule AE reste inchangée; le document de juillet s’applique pour ses autres paramètres à compter du 1er juillet.
- CRA, « EI premium rates and maximums », capture consultée le 2 octobre 2026, SHA-256 `b72d19f75f50e8b9515404226d73b2e6896fb8e749adc6854a12683c582ada35`. La table T4127 fournit le taux employeur QC 1,820%; CRA confirme la relation employeur 1,4× le taux/prime salarié. T4127 demande d’arrondir au cent les primes EI salarié ou employeur.

Documents officiels publics consultés; aucun code externe n’est repris. La capture et le snapshot ne qualifient pas le catalogue M5 : `sources_regles_paie.v1.yaml` demeure hors de cette tranche. Le millésime 2026 de ces paramètres ne vaut pas validation juridique d’un dossier réel.

## Vecteurs arithmétiques et vérification

Les vecteurs ci-dessous sont des calculs directs des formules officielles, pas des exemples de paie ni des observations terrain :

| Assiette période | Cumuls avant salarié / employeur | RQAP salarié / employeur | AE QC salarié / employeur |
|---:|---:|---:|---:|
| 1 000,00 $ | 0,00 $ / 0,00 $ | 4,30 $ / 6,02 $ | 13,00 $ / 18,20 $ |
| 0,01 $ | 0,00 $ / 0,00 $ | 0,01 $ / 0,00 $ | 0,00 $ / 0,00 $ |
| 1 000,00 $ (période 20, 2026-09-15) | proche du plafond : 442,89 $ / 620,05 $ RQAP; 895,69 $ / 1 253,97 $ AE | 0,01 $ / 0,01 $ | 0,01 $ / 0,01 $ |

Contrôle d’arrondi AE distinct : avec une assiette `1,00 $`, 1,30% donne `0,013` et la prime salarié arrondie est `0,01 $`; 1,820% donne `0,0182` et la prime employeur est `0,02 $`. Le résultat employeur serait incorrect si l’on prenait 1,4 fois `0,01 $` déjà arrondi puis arrondissait à nouveau. Les cas aux limites .005 et au cumul de période 1 sont séparément couverts par les tests.

Contrôle de plafonds RQAP issu des calculs des formules arrondies période par période : un cumul documenté de `442,89 $` salarié et `620,06 $` employeur est admissible avant la dernière paie si l’assiette courante donne `0,01 $` salarié et `0,00 $` employeur. À l’inverse, le maximum salarié déjà atteint avec un cumul employeur inférieur est refusé comme contraire à la note p.42. Ce contrôle respecte l’implication source sans exiger une égalité simultanée dans les deux sens.

Les tests de composition appellent RRQ et R42 par leurs fonctions publiques réelles : le `CSA` de sortie RRQ remplace le `CSA` initial fourni par l’appelant à R42. Ils vérifient aussi le déterminisme sous un contexte Decimal perturbé, les refus structurels et de périmètre, l’atteinte séparée des plafonds et l’absence de net/total incomplet.

Cette tranche ne raccorde aucun outil, runtime, registre ou catalogue, ne modifie pas les formules RRQ/R42 et ne met pas les règles en production. Un calcul préparatoire réussi ne prouve ni l’assujettissement ni la classification d’un salarié. Le fédéral de l’impôt sur le revenu, les cotisations employeur autres, la qualification juridique et la paie finale nécessitent des tranches distinctes.
