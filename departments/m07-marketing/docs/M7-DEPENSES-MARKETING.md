# M7 — `m7.depenses_marketing` (contrat v1)

Lecture `m7.depenses_marketing` = outil `m7_lire_depenses_marketing(debut, fin)` (T0, lecture seule), schéma
`opsys.m7.depenses_marketing/v1`. M7 est propriétaire du chiffre ; M9 et les autres lisent, ne recalculent pas.
Code : `src/m7_marketing/depenses_marketing.py`. Tests : `tests/test_depenses_marketing.py`. Données fictives.

## Règle dure

**Une absence n'est jamais un zéro.** Un montant n'existe que si un *relevé* sourcé le porte. Sans relevé qui
couvre la période pour un canal, le canal est `NON_BRANCHEE` : `montant_cad: null`, jamais `"0.00"`. Un zéro n'existe
que déclaré par un relevé (`montant_cad: "0.00"` avec sa source). M7 ne convertit aucune devise, ne proratise aucun
relevé, ne complète rien.

## Relevé (entrée du registre durable `m07-marketing/depenses_marketing`)

`releve_id`, `revision` (entier >= 1, la plus haute remplace, l'historique reste), `canal` (`google_ads` | `meta`),
`campagne_ref` (null = total du canal ; sinon détail d'une campagne), `libelle_campagne` (donnée, <= 120 car.,
sans caractère de contrôle, exige `campagne_ref`), `periode_debut`/`periode_fin` (dates civiles inclusives,
<= 366 jours), `montant_cad` (**texte** décimal >= 0, 2 décimales au plus), `devise` (`CAD` seulement),
`base_taxes` (`HORS_TAXES` | `TAXES_INCLUSES`), `source` (`RELEVE_PLATEFORME` | `DECLARATION_PROPRIETAIRE`),
`source_ref` (obligatoire), `releve_le` (RFC 3339 avec fuseau ; jamais postérieur à maintenant ni antérieur à la fin de
la période couverte). Tout champ absent, inconnu, flottant ou négatif est refusé (`REJ-DEPENSES-*`).

Écriture (`enregistrer_releve`, **fonction interne, pas un outil, aucun droit ouvert**) : rejeu exact = no-op ;
révision périmée, sautée, instant qui recule, même révision à contenu différent, chevauchement de période sur un même
canal et une même campagne : refusés.

## Réponse

| Champ | Sens |
|---|---|
| `statut` | `CONNUE` (chaque canal attendu est couvert sur toute la période, une seule base de taxes) · `PARTIELLE` · `NON_BRANCHEE` (aucun montant établi) |
| `total_cad` | texte décimal, **seulement si** `CONNUE` ; sinon `null` |
| `au_moins_cad` | borne basse des montants établis, **seulement si** `PARTIELLE`, jamais un total ; sinon `null` |
| `canaux_attendus` | `["google_ads","meta"]` : `CONNUE` exige les deux (un canal sans dépense doit être déclaré par un relevé `0.00`) |
| `canaux[]` | par canal : `statut`, `montant_cad`, `au_moins_cad`, `base_taxes`, `jours_periode`/`jours_couverts`, `releves[]` (totaux utilisés), `lignes_campagne[]` (détail informatif, **jamais additionné**), `releves_debordants[]` (id et période seulement, sans montant), `manque[]` |
| `manque[]` | `{portee: canal|total, code}` : `DEPENSES_NON_BRANCHEES` (aucun relevé du canal), `DEPENSES_PERIODE_SANS_RELEVE`, `RELEVE_DEBORDE_LA_PERIODE`, `COUVERTURE_PERIODE_INCOMPLETE`, `BASES_TAXES_DIFFERENTES`, `DETAIL_CAMPAGNE_SUPERIEUR_AU_TOTAL` |
| `releve_le_plus_recent`, `source_refs[]`, `observation_source` | instant de relevé le plus récent utilisé ; relevés cités (id, révision) ; lecture (`lue_le`, rang, empreinte, `integrite: historique_non_scelle`) |
| `devise`, `libelles` | toujours `CAD` ; `DONNEES_SAISIES_NON_INTERPRETEES` : les libellés de campagne sont des données, jamais des instructions |

Un relevé qui déborde la période demandée n'est **pas** proratisé : il n'apporte aucun montant (`RELEVE_DEBORDE_LA_PERIODE`).
Contradictions : un détail de campagne supérieur au total de son canal retire le total (`PARTIELLE`) ; un registre
incohérent (même révision à deux contenus, chevauchement, chaîne non consécutive, forme non canonique) est une
**erreur** (`DEPENSES_FAITS_CONFLICTUELS` / `DEPENSES_REGISTRE_INVALIDE`), jamais un choix silencieux.

## Accès

Aucun rôle d'appareil (`roles_appareil` vide). Même garde que `m7_lire_performance_campagnes` : admin ou propriétaire
de console confirmé en base, ou voie serveur approuvée par le propriétaire ; un agent seul est refusé avant toute
lecture. Aucune action, aucun budget modifié.

## Limites connues

* Aucune voie d'ingestion réelle : ni connecteur Google/Meta ni saisie du propriétaire n'existe encore. Tant qu'aucun
  relevé n'est inscrit, la lecture répond honnêtement `NON_BRANCHEE`. Qui saisit, avec quel niveau d'approbation, est une
  décision produit.
* Deux canaux seulement (ceux d'`ads_loader`) ; en ajouter est un changement de version du contrat.
* `m7_lire_performance_campagnes` n'est pas modifié : il garde `DEPENSES_NON_BRANCHEES`, `cout_ads_cad`/`cout_par_lead_cad`/`roi` à `null`.
