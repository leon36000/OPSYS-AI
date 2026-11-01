# Base de règles fiscales, validation de la paie, subventions et garde investissement (M5)

Statut : tranche 1 (2026-11-01). Code : `departments/m05-financecore/src/m5_financecore/` (`base_fiscale.py`,
`validation_paie.py`, `catalogue_subventions.py`, `garde_investissement.py`, `outils_base_fiscale.py`,
`verdicts_fiscal.py`). Données : `departments/m05-financecore/contracts/regles_fiscales.v1.yaml`,
`.../contracts/catalogue_subventions.v1.yaml`, `.../validation_paie/`. Tests : `tests/test_base_fiscale*.py`,
`test_validation_paie.py`, `test_catalogue_subventions.py`, `test_garde_investissement.py`, `test_outils_base_fiscale.py`
(dans `departments/m05-financecore/tests/`).

Décisions d'origine : feuille de route technologique (R6) — « base fiscale versionnée par date d'effet (YAML sourcé,
2 réviseurs) ; moteur de paie validé contre ≥ 300 cas WebRAS/PDOC à 0,00 $ ; subventions : catalogue curé et sourcé +
appariement règles → explication citée + revue humaine ; investissement : garde-fou en code bloquant toute
recommandation personnalisée de titres (NC 31-103) ».

## Statut honnête (ce qui est vrai aujourd'hui)

| Élément | Statut |
|---|---|
| Base de règles : valeurs renseignées | **62** (migrées des constantes du dépôt), toutes `brouillon` : **0/62 approuvées** par deux réviseurs |
| Base de règles : paramètres non renseignés | **9**, « source officielle requise » (voir plus bas) |
| Calculateurs de paie | **Inchangés** : ils lisent encore leurs constantes ; la base est exposée **en parallèle** (équivalence valeur par valeur testée) |
| Validation de la paie | Harnais livré. **« campagne officielle : 0/300 »** : aucun cas officiel (WebRAS/PDOC) n'existe dans le dépôt. Les règles restent `NON_QUALIFIEE_POUR_PAIE` |
| Catalogue de subventions | Structure et moteur livrés. **Catalogue vide** : aucune mesure réelle |
| Garde investissement | Filtre de texte déterministe, testé sur des formulations hostiles ; **pas** une compréhension du langage |

Rien ici n'est un avis fiscal ou comptable : **À valider auprès d'un comptable (CPA) / professionnel qualifié.**

## Audit : ce que M5 avait déjà et où vivent les paramètres

M5 portait déjà une fiscalité et une paie *préparatoires* : TPS/TVQ (`taxes.py`, taux dans
`contracts/taux_fiscaux.v1.yaml`, lus par `taux_fiscaux.charger_taux_fiscaux` — la seule base de taux qui était déjà
une DONNÉE), le calendrier fiscal TPS/TVQ (`calendrier_fiscal.py` + `contracts/calendrier_fiscal.v1.yaml`, sources
citées), un catalogue de références de règles de paie (`sources_regles_paie.py` + `contracts/sources_regles_paie.v1.yaml`,
sans aucune valeur de calcul) et quatre calculateurs préparatoires 2026 pour le Québec : RRQ (`cotisations_rrq_regulieres.py`),
RQAP et AE (`cotisations_rqap_ae_2026.py`), impôt du Québec (`impot_quebec_regulier.py`) et retenue fédérale
(`impot_federal_qc_2026.py`), composés par `paie_qc_preparatoire.py`. Chaque sortie dit `NON_QUALIFIEE_POUR_PAIE` et
`actions_financieres_bloquees`. Le moteur de calcul (`moteur_calcul.py`) ne porte aucun paramètre fiscal : il calcule sur
les hypothèses de l'appelant et refuse déjà un placement en titres (`REJ-CALC-OBJET-HORS-PERIMETRE`).

Côté stockage, il y avait donc deux régimes : les taux TPS/TVQ en **données** (YAML versionné, sans date d'effet ni
statut de revue), et tous les paramètres de paie en **code** (un dictionnaire `_PARAMETRES` par calculateur, avec un
hachage SHA-256 émis dans chaque résultat). Ces cinq fichiers de paie, plus `validation.py`, `contrats.py` et
`__init__.py`, sont de plus **épinglés par empreinte** dans `contracts/admission_paie_preparatoire.v1.json` : les
modifier fait tomber le diagnostic d'admission de la paie.

Consommation : `outils.py` lit `taux_fiscaux.v1.yaml` à chaque appel (`m5_calculer_taxes_tps_tvq`, la facturation, les
brouillons comptables, le rapprochement du grand livre) et passe le dictionnaire à `taxes.calculer_taxes` ; les
calculateurs de paie lisent leurs constantes de module ; `paie_qc_preparatoire.py` les compose ; le dossier WebRAS
(`m5_preparer_dossier_webras`) laisse FSS, CNESST et DAS à `UNKNOWN`. Aucun paramètre n'avait de date d'effet, de statut de
revue ni d'empreinte par valeur — c'est ce que cette tranche ajoute.

## La base de règles (`contracts/regles_fiscales.v1.yaml`)

Format choisi : **YAML**, lu par `yaml.safe_load` comme tous les autres contrats de M5 (aucune dépendance nouvelle). Le
chargeur est un `SafeLoader` qui **refuse les clés dupliquées** (sinon la dernière gagnerait en silence). Une valeur est
toujours un **texte décimal** (`'0.09975'`), jamais un nombre YAML (un `0.1` flottant est refusé).

```yaml
schema: opsys.regles-fiscales/v1
parametres:
- id: qc.tvq.taux                 # <juridiction>.<domaine>.<nom>, minuscules
  juridiction: QC                 # FED | QC
  libelle: 'TVQ : taux'
  valeur: '0.09975'               # Decimal en texte ; null = non renseigné
  unite: ratio                    # CAD | ratio (fraction 0..1) | nombre
  effet: {debut: '2026-01-01', fin: '2026-12-31'}   # fin: null = jusqu'à nouvel ordre
  sources:                        # au moins une pour une valeur renseignée
  - organisme: Revenu Québec
    titre: Loi sur la taxe de vente du Québec
    url: null                     # https:// obligatoire dès qu'une revue existe
    consulte_le: null             # AAAA-MM-JJ, obligatoire dès qu'une revue existe
    # facultatifs : reference (pages), sha256 (capture hors dépôt)
  saisie: {par: migration.depot, le: '2026-11-01'}
  revues: []                      # [{reviewer, le, decision: approuve, empreinte}]
  statut: brouillon               # brouillon | revu_1 | approuve — PROUVÉ par les revues
  empreinte: <sha256>
  note: ...                       # facultatif
  non_renseigne: {raison, source_requise}   # exigé si valeur: null, interdit sinon
```

### Ce que le chargeur refuse (`base_fiscale.charger_base`, tous testés)

Clé inconnue ou manquante, schéma inconnu, clé YAML dupliquée, fichier démesuré ou hors UTF-8 ; valeur non décimale
canonique (`0,05`, `1e-2`, `NaN`, espaces, flottant YAML), ratio hors de 0..1, négatif ; date impossible, période inversée ;
**trou** de dates entre deux versions d'un même paramètre ; **chevauchement** (même d'un jour, ou version après une version
ouverte) ; valeur renseignée **sans source** ; source sans organisme ou titre ; **modification silencieuse** (empreinte
recalculée ≠ empreinte écrite) ; statut déclaré différent de celui que les revues prouvent ; revue mal formée ou antérieure à
la saisie ; valeur revue dont une source n'a pas d'URL https et de date de consultation. `diagnostiquer()` liste tous les
refus d'un contenu, pas seulement le premier.

### Résolution « paramètre en vigueur à la date D »

`resoudre(base, id, date, mode=…)` rend la version dont la période contient D (bornes incluses) ou un refus typé :
`REJ-BASEFISC-PARAMETRE-INCONNU`, `-HORS-COUVERTURE` (aucune version ce jour-là : **jamais** la dernière valeur connue),
`-NON-RENSEIGNE`, `-NON-APPROUVE` (mode officiel), `-DATE-INVALIDE`, `-MODE-INVALIDE`. La base ne couvre que 2026 : le
1er janvier 2027, tout est « hors couverture — source officielle requise ».

## Gouvernance : deux réviseurs distincts

`approuve` n'est pas une étiquette qu'on écrit : c'est ce que les revues **prouvent**. Le chargeur compte les réviseurs
VALIDES d'un paramètre :

- chaque revue porte l'**empreinte courante** du paramètre (changer la valeur, une date ou une source change l'empreinte :
  les revues antérieures ne comptent plus) ;
- les réviseurs doivent être **distincts** (la casse est ignorée : `Marie` et `marie` sont la même personne) ;
- l'**auteur de la saisie** ne peut pas être l'un des deux (quatre yeux) ;
- 0 revue valide = `brouillon`, 1 = `revu_1`, ≥ 2 = `approuve` ; un statut déclaré qui diffère est refusé
  (`REJ-BASEFISC-STATUT-INCOHERENT`), aussi bien trop haut que trop bas.

Procédure pour changer ou ajouter une valeur : (1) modifier le paramètre (ou ajouter une version avec ses dates, sans trou
ni chevauchement) en citant une source officielle complète (organisme, titre, URL https, date de consultation, pages ;
`sha256` d'une capture conservée hors dépôt si possible) ; (2) recalculer l'empreinte :
`python -m m5_financecore.base_fiscale empreintes contracts/regles_fiscales.v1.yaml` ; (3) vérifier :
`python -m m5_financecore.base_fiscale verifier …` (le statut retombe à `brouillon`) ; (4) deux personnes, autres que l'auteur,
vérifient la valeur contre le document officiel et ajoutent chacune une revue avec l'empreinte et la date, puis le statut
passe à `approuve` ; (5) la modification passe par une revue Git (CODEOWNERS du dépôt). Le **nom** d'un réviseur est
déclaratif dans le fichier : il n'est authentifié que par la revue Git, pas par OPSYS (voir « Limites »).

## Deux modes, jamais de mode par défaut

| | `officiel` | `essai` |
|---|---|---|
| Sert | un paramètre `approuve` seulement | brouillon, `revu_1`, `approuve` |
| Résultat | `essai: false` | `essai: true` + avertissement « MODE ESSAI… » |
| Paramètre non renseigné | refus | refus |

Tout reçu qui consomme la base porte `marquage_recu` : le mode, les empreintes et statuts des paramètres utilisés, et
l'avertissement dès qu'un paramètre n'est pas approuvé (un seul suffit à rendre le reçu entier « essai »). Le pont TPS/TVQ
(`calculer_taxes_selon_base`) alimente `taxes.calculer_taxes` — qui reste le seul endroit multipliant un montant par un
taux — et rend les mêmes montants au cent que le chemin historique (testé sur 400+ montants, dont les demi-cents).

## Ce qui est migré, ce qui attend une source officielle

**Migré (62 valeurs, `brouillon`)** — chaque valeur provient d'une constante déjà dans le dépôt, pas de la mémoire :

| Groupe | Paramètres | Origine dans le dépôt |
|---|---|---|
| TPS, TVQ | `fed.tps.taux`, `qc.tvq.taux` | `contracts/taux_fiscaux.v1.yaml` |
| RRQ | 8 : MGA, exemption, taux palier 1, 1re supplémentaire, max palier 1, MSGA, taux et max palier 2 | `cotisations_rrq_regulieres._PARAMETRES` |
| RQAP | 5 : revenu max, taux et max salarié, taux et max employeur | `cotisations_rqap_ae_2026._PARAMETRES` |
| AE (Québec) | 5 : idem | idem |
| Impôt du Québec | déduction travailleur (2), 4 tranches (3 bornes, 4 taux, 4 constantes), crédits E et Q, plafond FTQ/Fondaction | `impot_quebec_regulier._PARAMETRES` |
| Impôt fédéral (QC) | 5 tranches (4 bornes, 5 taux, 5 constantes), crédit personnel, K2Q (7), K4 (2), abattement du Québec, LCF | `impot_federal_qc_2026._PARAMETRES` |

Non migrés, avec leur raison : conventions d'arrondi et contexte décimal (logique de calcul, pas un paramètre fiscal),
nombre de périodes (26) et PM=12 (structure du calcul), bornes de validation d'entrée, identifiants d'édition.
`test_toute_feuille_numerique_des_snapshots_est_migree_ou_exclue_avec_sa_raison` ferme la porte : toute nouvelle feuille
numérique d'un snapshot doit entrer dans la base ou être exclue avec sa raison.

**Sans source vérifiable — à fournir par l'humain / le CPA** :

1. Les **9 paramètres non renseignés** (aucune valeur dans le dépôt ; le dossier WebRAS les laisse `UNKNOWN`) :
   `qc.fss.taux_employeur`, `qc.cnesst.taux_cotisation`, `qc.ccq.taux_cotisation_employeur` (statut CCQ à déterminer),
   `qc.normes_travail.salaire_minimum_general`, `qc.normes_travail.seuil_heures_supplementaires`,
   `qc.normes_travail.majoration_heures_supplementaires`, `qc.normes_travail.indemnite_vacances_taux`,
   `fed.impot.montant_personnel_de_base` (TD1), `qc.impot.montant_personnel_de_base` (TP-1015.3).
2. **TPS et TVQ** : le dépôt cite l'organisme et la loi, mais ni URL ni date de consultation ; le réviseur doit les ajouter
   avant toute revue. La **date légale d'entrée en vigueur** des taux n'est pas renseignée (la période 2026 est celle du
   millésime « 2026-v1 » du fichier du dépôt).
3. **AE (5 valeurs)** : la source ARC « taux et maximums » est citée par URL et empreinte, **sans date de consultation**.
4. Les valeurs de paie portent une URL et une empreinte de capture, mais **les captures PDF ne sont pas dans le dépôt**
   (elles sont archivées hors runtime, voir `sources_regles_paie.v1.yaml`) : la vérification contre le document reste à faire
   par les réviseurs.
5. **Toute autre année que 2026** et toute date d'effet intra-annuelle non documentée.

## Plan de bascule (de l'exposition en parallèle à la dépendance)

1. *(fait)* Base en parallèle + équivalence valeur par valeur + pont TPS/TVQ identique au cent.
2. Les réviseurs complètent les sources, recalculent les empreintes, ajoutent les revues : la base passe à `approuve`.
3. Brancher `outils.py` (TPS/TVQ) sur `calculer_taxes_selon_base(mode=officiel)` ; le test d'équivalence au cent est déjà là.
4. Régénérer `contracts/admission_paie_preparatoire.v1.json` (les fichiers de paie sont épinglés par empreinte) **dans la
   même révision** que le changement des calculateurs, pour que les calculateurs lisent la base au lieu de `_PARAMETRES`
   (mêmes valeurs ⇒ mêmes résultats, prouvé par les ≥ 300 cas officiels de la campagne ci-dessous).
5. Supprimer les constantes, garder le test d'équivalence contre l'historique git.

Les étapes 3 et 4 **ne sont pas faites** : elles exigent des valeurs approuvées et la campagne de paie.

## Harnais de validation de la paie (`cas_paie.v1`)

Un fichier YAML `schema: cas_paie.v1` + `cas: [...]`. Chaque cas : `id`, `nature` (`officiel` ou
`fictif_pour_tests_du_harnais`), `entrees` (année, date de paie, province, fréquence, période annuelle, salaire brut,
crédit personnel TD1 fédéral, `exemptions` — cinq booléens explicites —, `cumuls_avant` — sept cumuls), `attendu.lignes`
(par ligne de retenue : `rrq_palier1`, `rrq_palier2`, `rqap_salarie`, `rqap_employeur`, `ae_salarie`, `ae_employeur`,
`impot_federal`, `impot_quebec` ; chacune avec son montant et l'**outil** qui l'a produit), `source` (type, et pour un cas
officiel les `executions` : outil WebRAS ou PDOC, version, date d'exécution, URL d'un hôte officiel, capture avec SHA-256),
`saisie` (auteur, date) et `revue` (réviseur, date).

- **Rejeu** : `rejouer_cas` appelle le moteur actuel (`calculer_retenue_federale_qc_preparatoire`, qui recalcule RRQ, RQAP,
  AE et impôt du Québec) et rapporte, **ligne par ligne**, attendu, obtenu, écart en dollars et en cents. Seuil d'acceptation
  **0,00 $** : un cent d'écart sur une ligne d'un cas est un écart. Un cas que le moteur refuse (hors périmètre) est
  `MOTEUR_REFUSE`, jamais un succès.
- **Provenance vérifiée** (`verifier_provenance`) : exécution nommée (outil WebRAS/PDOC, version, date ≤ saisie, URL https de
  `revenuquebec.ca` ou `canada.ca`, sans identifiant « utilisateur@ »), capture présente sous la racine confinée et
  d'empreinte SHA-256 identique (liens symboliques et chemins `..` refusés), chaque ligne attribuée à un outil documenté,
  réviseur ≠ auteur, revue ≥ saisie.
- **Qualification** (`qualifier_campagne`) : refuse tout cas fictif ; exige **≥ 300 cas officiels**, tous à provenance
  vérifiée, tous à écart 0,00 $, à entrées distinctes (un cas copié est un doublon refusé au chargement). Même qualifiée,
  la campagne ne rend pas les règles « qualifiées pour la paie » : cela reste la décision du CPA.
- **Statut** : `statut_campagne` / `m5_lire_statut_campagne_paie` → **« campagne officielle : 0/300 »**.

Livré : `validation_paie/cas_demonstration/demonstration_fictif.yaml` — 18 cas **fictifs** (salaires arbitraires, cumuls
simulés sur une année de paies, valeurs produites par le moteur lui-même). Ils prouvent que le harnais rejoue et détecte un
écart ; ils ne prouvent PAS que le moteur est juste, et le mode de qualification les refuse. `validation_paie/cas_officiels/`
est vide (`.gitkeep`) ; `validation_paie/captures/` recevra les captures.

## Catalogue de subventions et de crédits

`contracts/catalogue_subventions.v1.yaml` : un vocabulaire fermé de **faits** (province, nombre d'employés, chiffre
d'affaires, SCIAN, société privée canadienne, projet démarré, date de début) et `mesures: []` — **vide**. Une mesure
déclare : organisme, programme, titre, juridiction, type, `admissibilite` (critères déclaratifs : champ, opérateur —
`eq ne in not_in gte gt lte lt between vrai faux` selon le type —, valeur, **source citée** par critère ; un groupe
`un_parmi` pour le « ou »), `periode`, `expiration`, `montant` (nature, valeur, plafond, **source**, ou « inconnu »),
`documents_requis`, `sources`, `verification` (statut, par, le, `valide_jusqu_au`).

`apparier(catalogue, faits, aujourd_hui)` — déterministe, sans horloge — rend pour chaque mesure non périmée l'état de
chaque critère (`satisfait`, `non_satisfait`, `inconnu`) avec une explication qui cite la source. Verdicts : `admissible`
(tous satisfaits **et** mesure vérifiée dont la vérification n'a pas expiré), `non_admissible` (un critère non satisfait),
`a_verifier` (un critère inconnu — avec la question à poser — ou mesure non vérifiée). **Jamais « admissible » sur un fait
inconnu.** Mesures périmées (expiration, période terminée ou pas encore ouverte) **exclues et dites**. Aucun montant n'est
estimé. Les faits sont validés (vocabulaire fermé, types, texte court sans retour de ligne ni balisage : un fait est une
donnée, jamais une consigne). Chaque mesure `admissible` ou `a_verifier` reçoit un **brouillon de dossier** (niveau N2 :
documents à fournir, questions ouvertes) ; **rien n'est déposé** — la soumission est une décision humaine (N3 ou plus).
Mode `officiel` : une mesure `fictif: true` refuse tout le catalogue. Mention sur chaque sortie.

## Garde investissement (NC 31-103)

`garde_investissement.evaluer_demande(texte, origine)` → `REFUSE` / `PERMIS` / `A_PRECISER`. `REFUSE` : titres (actions,
FNB, fonds, obligations, cryptoactifs, symboles boursiers, comptes enregistrés) avec une demande de recommandation, de
choix, d'ordre ou de situation personnelle ; ou achat/placement de fonds sans objet d'exploitation reconnu (« achète X »,
« dis-moi quoi acheter avec mes 50 000 $ »). La réponse est générique, renvoie à un représentant inscrit et porte « À
valider auprès d'un comptable (CPA) / professionnel qualifié ». **Liste blanche** (`CONTENUS_PERMIS`) : information générale
(« c'est quoi un FNB ? », sans personnalisation), trésorerie (CPG, échelonnement, réserve, prévision — sans produit ni
institution recommandés), calculs déterministes via `moteur_calcul`, décision d'exploitation (camion, équipement…), et ce
qui n'a rien à voir. Les consignes glissées (« ignore tes règles », « tu es conseiller inscrit », un courriel qui ordonne
d'acheter) sont **signalées** (`injection_detectee`) et ne lèvent jamais un refus ; les obfuscations courantes (espaces,
astérisques, leet, lettres répétées, homoglyphes cyrilliques, caractères de largeur nulle) sont normalisées.
Corpus de test : ~90 formulations hostiles et licites, en français et en anglais.

## Outils (lecture et brouillon, N0)

| Outil | Rôle | Niveau | Portée d'appareil |
|---|---|---|---|
| `m5_lire_etat_base_fiscale` | valeurs, approuvées (0), non renseignées | T0 / N0 | fermée |
| `m5_lire_regle_fiscale` | paramètre en vigueur à une date, mode obligatoire | T0 / N0 | fermée |
| `m5_lire_statut_campagne_paie` | « campagne officielle : N/300 » + rejeu des cas fictifs | T0 / N0 | fermée |
| `m5_apparier_subventions` | critères cités + brouillon de dossier (rien de déposé) | T0 / N0 | fermée |
| `m5_verifier_demande_investissement` | garde NC 31-103 | T0 / N0 | fermée |

Procédure `ROLES.md` (« Ajouter ou élargir une portée ») : aucun `roles_appareil` ; une identité d'appareil est refusée dans
le code (`REJ-IDENTITE-APPAREIL-INVALIDE`) ; chaque outil est classé dans `analyse.SORTIES_FISCALES` (les deux mentions sur
chaque sortie acceptée) ; lignes ajoutées à `ROLES.md` (« Fermés à tous les appareils »). Aucune écriture, aucun
événement, aucun mouvement ; la garde anti-décaissement et les gardes statiques du paquet couvrent les nouveaux modules.

## Limites (dites sans euphémisme)

- Aucune valeur n'est **approuvée** : la base n'a jamais été relue par deux personnes ; le mode officiel refuse tout.
- Aucun calculateur de paie ne lit la base : l'équivalence est testée, la dépendance ne l'est pas encore.
- **Aucun cas officiel** : le harnais n'a jamais été exercé contre WebRAS ni PDOC. Les 18 cas fictifs sont circulaires
  (valeurs du moteur). L'authenticité des captures n'est pas prouvée (empreinte = intégrité, pas origine).
- Les noms de réviseurs, d'auteurs et de vérificateurs sont déclaratifs dans les fichiers : l'authentification réelle est la
  revue Git, pas OPSYS. Rien n'empêche techniquement un éditeur du dépôt d'écrire deux faux réviseurs.
- Le moteur de paie ne couvre que : 2026, Québec, bihebdomadaire, paie régulière fixe, un employeur, PM=12 ; tout le reste est
  un refus moteur, pas un cas du harnais.
- Le catalogue de subventions est vide : l'appariement est prouvé sur des mesures fictives de test seulement.
- La garde investissement est un filtre de motifs : une langue non couverte, une paraphrase inédite ou un code convenu peut
  passer ; elle complète la liste fermée d'objets de `moteur_calcul`, elle ne la remplace pas.
- Rien n'a été testé contre un service réel : aucun réseau, aucune API officielle.
