# M5.4.f — calcul préparatoire RRQ régulier, Québec, 2026

`m5_financecore.cotisations_rrq_regulieres.calculer_cotisation_rrq_preparatoire` est une fonction pure et non raccordée. Elle calcule `C` (RRQ de base plus première cotisation supplémentaire), `C2` (deuxième cotisation supplémentaire) et `CSA` pour un salarié QC, emploi continu, salaire régulier fixe et 26 périodes bihebdomadaires 2026. Elle n’appelle aucun outil, registre, M4, service fiscal ni R42. Chaque rapport porte `PREPARATOIRE`, `NON_QUALIFIEE_POUR_PAIE`, `preuve_authenticite=NON_VERIFIEE`, `statut_ccq=UNKNOWN`, actions bloquées, et net/DAS/coût employeur global à `null`.

## Sources et version exécutées

Le jeu de paramètres est l’objet `_PARAMETRES` canonique du module. Chaque rapport inclut une copie JSON de cet objet et son SHA-256, calculé sur JSON UTF-8 trié et compact; le hash peut donc être recomputé par le lecteur. C’est l’empreinte des paramètres exacts exécutés, pas seulement le libellé de version. Elle lie taux, plafonds, nombre de périodes/mois, bornes de montants, politique d’arrondi, édition et empreintes des sources. Les PDF Revenu Québec référencés sont TP-1015.F 2026-01 (SHA-256 `a65675dc6ad2bfc6c4fe2695d4914a57f381eccc9b8b1e1c581b7c9c8a18e72b`) et TP-1015.TR.26 2026-01 (SHA-256 `2079c958132de69216157b5c16c0296c89556e6deb69ad1854c9ebddf680c321`).

La formule TP-1015.F §3.1, pages imprimées 37–38, avec paramètres 2026 page 7, définit :

- `C = min(4 479,30 × PM/12 − A5, 0,0630 × [S3 − 3 500/P])`; le calcul est planché à zéro conformément à la table A de TP-1015.TR.26 qui donne 0,00 $ sous ou à 134,61 $ pour 26 périodes.
- `C2 = max(0, min(416 × PM/12 − A8, 0,04 × [S5 + S3 − W]))`, avec `W=max(S5, 74 600 × PM/12)`.
- `P=26`, `PM=12` (attestation d’entrée requise), exemption de période `3 500/26` tronquée au cent inférieur : 134,61 $. `S3` est l’assiette de la période; `S5`, `A5`, `A8` sont les cumuls avant la période.
- TP-1015.F §3.2 page 40 dit que la cotisation employeur RRQ égale la cotisation salariée. Cette égalité RRQ ne représente aucune charge employeur autre.
- RRQ `C` et `C2` sont arrondies séparément selon TP-1015.F page 40 : la fraction sous 0,005 $ est écartée, sinon un cent est compté; tout montant positif inférieur à un cent devient un cent. La table A vérifie 134,61 $ → 0,00 $, 134,62 $ → 0,01 $, 134,84 $ → 0,01 $ et 134,85 $ → 0,02 $.

TP-1015.F §2.1.1, page 13, définit la déduction supplémentaire : `CS=C×(0,01/0,0630)+C2`; la variable `CSA` sépare les gains réguliers des gratifications/rétroactifs (voir aussi page 29). Comme cette tranche refuse ces paiements forfaitaires, `CSA=CS`. Le résultat `CSA` est sérialisé au cent, demi vers le haut, choix d’implémentation documenté et aligné sur l’exemple régulier TP-1015.F annexe 1 page 46 (`CSA=38,65 $`). La sortie contient également la valeur exacte avant cet arrondi; le point p.51 `CSA=71,23 $` est dérivé des `C/C2` officiels de l’annexe 3 et de la formule p.29, pas imprimé comme vecteur autonome.

L’annexe 3 TP-1015.F pages 51–52 fournit un scénario de 4 000 $ aux deux semaines : après 18 périodes `S5=72 000,00`, `A5=4 383,36`, `A8=0`; période 19 `C=95,94`, `C2=56,00`; période 20, avec cumuls `S5=76 000,00`, `A5=4 479,30`, `A8=56,00`, `C=0,00`, `C2=160,00`. L’annexe 1 page 46 donne indépendamment pour le salaire régulier de 4 000 $ et 26 périodes `CSA=38,65 $`.

## Entrées et preuves déclaratives

La fonction reçoit seulement des mots-clés fermés; tout champ inconnu ou omis est refusé. Les dates ISO doivent appartenir à 2026, le rang doit être un `int` exact de 1 à 26, `True` n’est pas un rang; l’appelant associe date et rang à un calendrier bihebdomadaire et transmet son identifiant/hash. Le module ne vérifie pas le calendrier, ne consulte pas l’horloge et ne déduit aucun rang de date.

L’appelant fournit aussi booléens stricts : emploi continu, salaire régulier fixe, aucune gratification/rétroactif, aucun transfert RPC vers RRQ, aucune exemption spéciale et assujettissement QC confirmé. Pour cette première portée, tout cas contraire ou inconnu est refusé. `PM=12` doit être donné avec une référence/hash d’attestation. Aucun âge/date de naissance n’est collecté ou inféré. Les références d’assiette, de cumuls, d’attestation PM et de calendrier sont des assertions d’entrée; elles sont affichées, mais ni leur authenticité ni la véracité du salarié, du calendrier, du montant et de l’assujettissement ne sont vérifiées. Le statut CCQ est toujours `UNKNOWN`; aucune règle salariale ou cotisation CCQ n’est appliquée.

Les quatre montants — assiette RRQ courante, assiette cumulée avant, `A5` et `A8` — doivent être des chaînes décimales canoniques non négatives ou des `Decimal` finis, au plus deux décimales, sous la borne M5. Float, bool, exponent notation textuelle, NaN, infinité, montants négatifs et précision d’entrée excessive sont refusés. Avant la période 1, les cumuls antérieurs doivent être nuls; `A5`/`A8` dépassant leurs plafonds annuels sont refusés.

Les calculs utilisent un `decimal.Context` neuf, avec précision, bornes d’exposant, `clamp`, mode d’arrondi et politique de pièges inclus dans le snapshot hashé. Le contexte ambiant du processus, y compris `Emin`, `Emax` et `clamp`, ne modifie donc ni le résultat ni les indicateurs du contexte appelant.

Le module ne construit pas l’assiette depuis un brut M4, taux horaire, WCT, chantier, photo ou facture. Le préparateur doit fournir une assiette RRQ prouvée séparément. Les références/hashes n’authentifient rien à elles seules.

## Sortie, refus et limites

Les montants rapportés sont des chaînes (`cotisation_palier1`, `cotisation_palier2`, `cotisation_rrq_totale`, `CSA`, exemption); `CSA` n’est jamais confondue avec `C+C2`. Les états fiscaux nets, DAS, coût employeur complet, déclaration, paiement et écriture de paie ne sont pas calculés. La source TP-1015.F et ses tables disponibles hors runtime ne transforment pas le catalogue M5 actuel `NON_QUALIFIEE` en source runtime qualifiée.

Les exclusions comprennent emploi discontinu/irrégulier, fréquence autre que 26, période de moins de 12 mois/PM autre, transfert RPC-RRQ, gratification/rétroactif, exemptions spéciales, âge ou assujettissement non établi, correction/cumul provenant de plusieurs employeurs, assiette d’avantages inconnue, toutes règles CCQ, RQAP/AE/FSS/CNESST, impôts, net, paie finale, outil et raccord automatique à R42. Une version annuelle future sera nouvelle et immuable; elle ne remplace pas silencieusement les valeurs 2026.
