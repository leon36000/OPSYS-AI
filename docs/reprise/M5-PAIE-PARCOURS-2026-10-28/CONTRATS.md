# Contrats

## 1. Consommation des heures M4 (lecture seule, aucune modification M4)

- **Symbole** : `lecteur_heures_m4(technicien_id, debut, fin, fuseau)` injecté dans `m5_financecore.outils.outils()` par
  `Capacites._lecteur_heures_m4` ; il appelle l'outil M4 `m4_lire_heures_regulieres_validees` sous le contexte M5 + owner console.
- **Forme (version actuelle de la base)** : enveloppe `{ok, resultat:{accepte, resultat:{technicien_id, periode{debut,fin,fuseau},
  minutes_regulieres, ligne_id, revision, empreinte_sources, couverture_complete, classification_reguliere_confirmee}}}`.
- **Unités / précision** : `minutes_regulieres` entier 0 ≤ n ≤ minutes physiques de la période locale (jours de 23/25 h respectés) ;
  aucun arrondi côté M4→M5. M5 calcule `brut = taux_horaire(centimes) × minutes / 60`, centime demi supérieur, `Decimal`.
- **Période / fuseau** : dates locales inclusives ISO + fuseau IANA, 14 jours pour le dossier ; la projection doit renvoyer exactement la période demandée.
- **Références** : `ligne_id` et `empreinte_sources` (64 hex), `revision ≥ 1` ; conservées dans la version figée, comparées à chaque vérification.
- **Refus** : projection absente, mal formée, couverture incomplète, classification non confirmée, période différente, employé non actif → `SOURCE-REFUSEE`,
  aucun brut, aucune version. Tout pointage ambigu reste refusé côté M4 ; M5 n'affecte jamais d'heures « par proximité ».
- **Confidentialité** : lecture réservée au propriétaire console ; les minutes et le brut ne sont conservés que dans le journal chiffré.
- **Compatibilité** : les visites multiples de la mission M4 parallèle ne sont pas consommées ici ; le contrat ci-dessus est celui de la base `3ab7692f`. Le
  coordinateur doit rejouer `test_console_paie_dossier.py` sur la tête M4 (ancien cas préservé, deux visites sans durée fantôme, source corrigée détectée, dossier historique conservé).
- **Tests** : `test_console_paie_dossier.py` (vraies heures validées par approbation N4, dérive après snapshot), `test_pont_heures_paie.py` (existant).

## 2. Sources et calculs

| Poste | Source | Date de lecture | Statut de capture |
|---|---|---|---|
| RRQ, impôt QC, RQAP | Revenu Québec TP-1015.F 2026-01 (SHA épinglé dans les moteurs existants) | existant | PDF épinglés par l'admission serveur ; **non re-hachés ici (réseau 403)** |
| AE, fédéral | ARC T4127 122e (janv. 2026) et 123e (juill. 2026) | existant | idem |
| RRQ employeur | TP-1015.F 2026-01 p. 7, partie 3.2 p. 40 | 2026-10-28 | texte officiel lu, sans octets |
| FSS | TP-1015.F partie 5 pp. 43-45 ; TP-1015.G partie 6 pp. 67-70 | 2026-10-28 | idem ; règle d'arrondi lue (`D2 = W × S2`, cent, 3e décimale ≥ 5 vers le haut) |
| Normes du travail | TP-1015.G partie 7 p. 74 (0,06 %, max 103 000 $) | 2026-10-28 | idem |
| FDRCMO | TP-1015.G partie 8 p. 75 (> 2 M$, 1 %) | 2026-10-28 | idem |
| CNESST | Guide « Calcul du versement périodique » 2026 §2, 2.1, 2.2 ; salaire max 103 000 $ | 2026-10-28 | idem ; taux = déclaration de l'employeur (aucun défaut) |

Niveau de vérification des règles employeur (lecture par un service tiers, jamais par octets) : formule et arrondi FSS (D2 = W × S2) relus
**directement** à la source par l'auteur du lot (TP-1015.F partie 5) ; maximum normes du travail 103 000 $ confirmé deux fois (sous-agent de recherche
et lecture directe de TP-1015.G) ; taux 0,06 %, seuil FDRCMO 2 M$ / 1 %, maximum et mode de calcul CNESST, RRQ employeur : une seule lecture (sous-agent
de recherche, citations courtes consignées dans l'instantané). À faire relire par le CPA avant tout usage.

Snapshot haché : `cotisations_employeur_2026.HASH_PARAMETRES` ; paramètres fédéraux : `hash_parametres_federal` ; sortie des moteurs : `empreinte_sortie_moteurs`.
Conventions d'implémentation non prescrites par la source : arrondi au cent demi supérieur pour CNESST et normes par période (documenté dans l'instantané).
Aucune reconduction 2026 → 2027 : une date de paie hors 2026 rend les postes inconnus.

## 3. Confidentialité

Voir `departments/m05-financecore/contracts/dossier_paie_preparatoire.v1.yaml` (section `confidentialite`). Aucun NAS, compte bancaire, adresse ni pièce RH brute ;
export : référence OPSYS de l'employé seulement, jamais le taux horaire ; fixtures `fictif: true`.
